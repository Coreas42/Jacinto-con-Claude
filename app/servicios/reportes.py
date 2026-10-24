"""Reportes: ventas agrupadas, utilidad bruta, inventario valorizado y exportación CSV.

Reglas:
- Requieren ``reportes.ver`` (y ``reportes.exportar`` para el CSV).
- Alcance: quien solo tiene ``ventas.ver`` recibe únicamente sus propias ventas y NO ve
  costos ni utilidad (esos campos llegan como ``None``). Con ``ventas.ver_todas`` (contador,
  administrador) se ve todo.
- Solo cuentan las ventas completadas; las anuladas se informan aparte.
- Ingreso = precio × cantidad − descuento de línea − parte proporcional del descuento
  general. El reparto se hace al centavo, así la suma de las líneas siempre coincide con
  el total de la venta.
- Utilidad bruta = ingreso − costo congelado al vender (no cambia si el costo cambia luego).
- Se agrega en Python sobre las líneas del periodo: pensado para decenas de miles de
  líneas, no millones. Para volúmenes mayores habrá que pasar la agregación a SQL.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import Categoria, Producto, Sucursal, Usuario, Venta, VentaDetalle
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import _celda, existencias
from app.servicios.permisos import exigir_permiso, puede_ver_costos
from app.servicios.ventas import _ve_todas, formatear_numero

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
AGRUPACIONES = ("dia", "vendedor", "producto", "categoria", "sucursal")


# ---- fechas ------------------------------------------------------------------------


def rango_local(desde: date | None, hasta: date | None) -> tuple[datetime | None, datetime | None]:
    """Convierte días del calendario local (``hasta`` incluido) al rango UTC de la base.

    Devuelve ``(inicio, fin)`` con ``fin`` exclusivo: usar ``creado_en >= inicio`` y ``< fin``.
    """

    def a_utc(momento: datetime) -> datetime:
        return momento.astimezone(timezone.utc).replace(tzinfo=None)

    inicio = a_utc(datetime.combine(desde, time.min)) if desde else None
    fin = a_utc(datetime.combine(hasta + timedelta(days=1), time.min)) if hasta else None
    return inicio, fin


def _dia_local(fecha: datetime) -> str:
    return fecha.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d")


# ---- núcleo: líneas de venta con el descuento general repartido ----------------------


def _repartir(descuento: Decimal, netos: list[Decimal]) -> list[Decimal]:
    """Reparte ``descuento`` proporcionalmente entre importes netos; la última línea absorbe el resto."""
    subtotal = sum(netos, Decimal("0"))
    if descuento == 0 or subtotal == 0:
        return [CERO] * len(netos)
    partes: list[Decimal] = []
    acumulado = Decimal("0")
    for indice, neto in enumerate(netos):
        if indice == len(netos) - 1:
            parte = descuento - acumulado
        else:
            parte = (descuento * neto / subtotal).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        partes.append(parte)
        acumulado += parte
    return partes


def _condiciones(
    todas: bool, actor: Usuario, desde: datetime | None, hasta: datetime | None,
    sucursal_id: int | None, vendedor_id: int | None,
) -> list[Any]:
    condiciones: list[Any] = []
    if not todas:
        condiciones.append(Venta.vendedor_id == actor.id)  # el filtro por vendedor no amplía el alcance
    elif vendedor_id is not None:
        condiciones.append(Venta.vendedor_id == vendedor_id)
    if desde is not None:
        condiciones.append(Venta.creado_en >= desde)
    if hasta is not None:
        condiciones.append(Venta.creado_en < hasta)
    if sucursal_id is not None:
        condiciones.append(Venta.sucursal_id == sucursal_id)
    return condiciones


def _lineas(
    sesion: Session, actor: Usuario, desde: datetime | None, hasta: datetime | None,
    sucursal_id: int | None, vendedor_id: int | None,
) -> tuple[list[dict], dict, bool]:
    """Líneas de ventas completadas, resumen de anuladas y si se pueden mostrar costos."""
    exigir_permiso(sesion, actor, "reportes", "ver")
    todas = _ve_todas(sesion, actor)
    condiciones = _condiciones(todas, actor, desde, hasta, sucursal_id, vendedor_id)

    consulta = (
        select(Venta, VentaDetalle, Producto, Categoria.nombre, Usuario.nombre, Sucursal.nombre)
        .join(VentaDetalle, VentaDetalle.venta_id == Venta.id)
        .join(Producto, Producto.id == VentaDetalle.producto_id)
        .join(Categoria, Categoria.id == Producto.categoria_id)
        .join(Usuario, Usuario.id == Venta.vendedor_id)
        .join(Sucursal, Sucursal.id == Venta.sucursal_id)
        .where(Venta.estado == "completada", *condiciones)
        .order_by(Venta.id, VentaDetalle.id)
    )
    por_venta: dict[int, list[tuple]] = {}
    for fila in sesion.execute(consulta):
        por_venta.setdefault(fila[0].id, []).append(fila)

    lineas: list[dict] = []
    for filas in por_venta.values():
        venta = filas[0][0]
        netos = [
            (Decimal(d.cantidad) * d.precio_unitario - d.descuento_linea).quantize(CENTAVO) for _, d, *_ in filas
        ]
        partes = _repartir(venta.descuento, netos)
        for (_, detalle, producto, categoria, vendedor, sucursal), neto, parte in zip(filas, netos, partes):
            costo = (Decimal(detalle.cantidad) * detalle.costo_unitario).quantize(CENTAVO)
            ingreso = neto - parte
            lineas.append(
                {
                    "venta_id": venta.id,
                    "fecha": venta.creado_en,
                    "dia": _dia_local(venta.creado_en),
                    "vendedor": vendedor,
                    "sucursal": sucursal,
                    "producto_id": producto.id,
                    "producto": f"{producto.sku} · {producto.nombre}",
                    "categoria": categoria,
                    "cantidad": detalle.cantidad,
                    "ingreso": ingreso,
                    "costo": costo,
                }
            )

    anuladas = sesion.execute(
        select(func.count(), func.coalesce(func.sum(Venta.total), 0)).where(Venta.estado == "anulada", *condiciones)
    ).one()
    return lineas, {"cantidad": int(anuladas[0]), "total": Decimal(anuladas[1]).quantize(CENTAVO)}, todas


def _margen(utilidad: Decimal, ingreso: Decimal) -> Decimal | None:
    if ingreso == 0:
        return None
    return (utilidad * 100 / ingreso).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---- reportes de ventas --------------------------------------------------------------


def resumen_ventas(
    sesion: Session, actor: Usuario, desde: datetime | None = None, hasta: datetime | None = None,
    sucursal_id: int | None = None, vendedor_id: int | None = None,
) -> dict:
    """Totales del periodo. ``costo``, ``utilidad`` y ``margen`` son ``None`` si no se pueden ver."""
    lineas, anuladas, todas = _lineas(sesion, actor, desde, hasta, sucursal_id, vendedor_id)
    ingreso = sum((l["ingreso"] for l in lineas), CERO)
    costo = sum((l["costo"] for l in lineas), CERO)
    ventas = len({l["venta_id"] for l in lineas})
    return {
        "ventas": ventas,
        "unidades": sum(l["cantidad"] for l in lineas),
        "ingreso": ingreso,
        "ticket_promedio": (ingreso / ventas).quantize(CENTAVO, rounding=ROUND_HALF_UP) if ventas else CERO,
        "costo": costo if todas else None,
        "utilidad": ingreso - costo if todas else None,
        "margen": _margen(ingreso - costo, ingreso) if todas else None,
        "anuladas": anuladas["cantidad"],
        "total_anuladas": anuladas["total"],
    }


def ventas_agrupadas(
    sesion: Session, actor: Usuario, por: str, desde: datetime | None = None, hasta: datetime | None = None,
    sucursal_id: int | None = None, vendedor_id: int | None = None, limite: int | None = None,
) -> list[dict]:
    """Ventas agrupadas por ``dia``, ``vendedor``, ``producto``, ``categoria`` o ``sucursal``.

    Se ordena por ingreso (mayor primero); por día, cronológicamente. ``limite`` recorta el resultado.
    """
    if por not in AGRUPACIONES:
        raise ErrorDeNegocio(f"Agrupación no válida. Usa: {', '.join(AGRUPACIONES)}.")
    lineas, _, todas = _lineas(sesion, actor, desde, hasta, sucursal_id, vendedor_id)

    grupos: dict[str, dict] = {}
    for l in lineas:
        g = grupos.setdefault(
            l[por], {"clave": l[por], "ventas": set(), "unidades": 0, "ingreso": CERO, "costo": CERO}
        )
        g["ventas"].add(l["venta_id"])
        g["unidades"] += l["cantidad"]
        g["ingreso"] += l["ingreso"]
        g["costo"] += l["costo"]

    filas = []
    for g in grupos.values():
        utilidad = g["ingreso"] - g["costo"]
        filas.append(
            {
                "clave": g["clave"],
                "ventas": len(g["ventas"]),
                "unidades": g["unidades"],
                "ingreso": g["ingreso"],
                "costo": g["costo"] if todas else None,
                "utilidad": utilidad if todas else None,
                "margen": _margen(utilidad, g["ingreso"]) if todas else None,
            }
        )
    if por == "dia":
        filas.sort(key=lambda f: f["clave"])
    else:
        filas.sort(key=lambda f: (-f["ingreso"], f["clave"]))
    return filas[:limite] if limite else filas


def resultado_del_periodo(
    sesion: Session, actor: Usuario, desde: date | None = None, hasta: date | None = None,
    sucursal_id: int | None = None,
) -> dict:
    """Utilidad bruta menos gastos = utilidad neta, por días del calendario local.

    Exige poder ver costos (``ventas.ver_todas``) y ``gastos.ver``. Al filtrar por sucursal
    solo entran los gastos asignados a ella (los gastos generales quedan fuera).
    """
    from app.servicios.gastos import total_gastos

    inicio, fin = rango_local(desde, hasta)
    resumen = resumen_ventas(sesion, actor, inicio, fin, sucursal_id)
    if resumen["utilidad"] is None:
        raise PermisoDenegado("ventas", "ver_todas")
    gastos = total_gastos(sesion, actor, desde, hasta, sucursal_id=sucursal_id)
    neta = resumen["utilidad"] - gastos
    return {
        "ingreso": resumen["ingreso"],
        "costo": resumen["costo"],
        "utilidad_bruta": resumen["utilidad"],
        "gastos": gastos,
        "utilidad_neta": neta,
        "margen_neto": _margen(neta, resumen["ingreso"]),
    }


# ---- inventario valorizado -----------------------------------------------------------


def inventario_valorizado(sesion: Session, actor: Usuario, sucursal_id: int | None = None) -> dict:
    """Stock × costo promedio por producto, con totales y subtotales por categoría."""
    exigir_permiso(sesion, actor, "reportes", "ver")
    if not puede_ver_costos(sesion, actor):
        raise PermisoDenegado("ventas", "ver_todas")  # el valor del inventario se calcula con costos
    filas = [f for f in existencias(sesion, actor, sucursal_id) if f["stock"] > 0]
    por_categoria: dict[str, dict] = {}
    for f in filas:
        c = por_categoria.setdefault(f["categoria"], {"categoria": f["categoria"], "unidades": 0, "valor": CERO})
        c["unidades"] += f["stock"]
        c["valor"] += f["valor"]
    return {
        "filas": filas,
        "total_unidades": sum(f["stock"] for f in filas),
        "total_valor": sum((f["valor"] for f in filas), CERO),
        "por_categoria": sorted(por_categoria.values(), key=lambda c: (-c["valor"], c["categoria"])),
    }


# ---- exportación ---------------------------------------------------------------------


def _a_csv(encabezados: list[str], filas: list[list[Any]]) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    escritor.writerows([[_celda(c) for c in fila] for fila in filas])
    return salida.getvalue()


def _dinero(valor: Decimal | None) -> str:
    return "" if valor is None else f"{valor:.2f}"


def exportar_ventas_agrupadas_csv(
    sesion: Session, actor: Usuario, por: str, desde: datetime | None = None, hasta: datetime | None = None,
    sucursal_id: int | None = None, vendedor_id: int | None = None,
) -> str:
    exigir_permiso(sesion, actor, "reportes", "exportar")
    filas = ventas_agrupadas(sesion, actor, por, desde, hasta, sucursal_id, vendedor_id)
    registrar(sesion, "reporte_exportado", usuario_id=actor.id, entidad="reportes", detalle={"reporte": f"ventas_por_{por}"})
    return _a_csv(
        [por.capitalize(), "Ventas", "Unidades", "Ingreso", "Costo", "Utilidad", "Margen %"],
        [
            [f["clave"], f["ventas"], f["unidades"], _dinero(f["ingreso"]), _dinero(f["costo"]),
             _dinero(f["utilidad"]), "" if f["margen"] is None else f"{f['margen']}"]
            for f in filas
        ],
    )


def exportar_detalle_ventas_csv(
    sesion: Session, actor: Usuario, desde: datetime | None = None, hasta: datetime | None = None,
    sucursal_id: int | None = None, vendedor_id: int | None = None,
) -> str:
    """Una fila por venta (completadas y anuladas), con quién la hizo y quién la anuló."""
    exigir_permiso(sesion, actor, "reportes", "exportar")
    exigir_permiso(sesion, actor, "reportes", "ver")
    todas = _ve_todas(sesion, actor)
    anulador = Usuario.__table__.alias("anulador")
    consulta = (
        select(Venta, Usuario.nombre, Sucursal.nombre, anulador.c.nombre)
        .join(Usuario, Usuario.id == Venta.vendedor_id)
        .join(Sucursal, Sucursal.id == Venta.sucursal_id)
        .outerjoin(anulador, anulador.c.id == Venta.anulada_por)
        .where(*_condiciones(todas, actor, desde, hasta, sucursal_id, vendedor_id))
        .order_by(Venta.id)
    )
    filas = [
        [
            formatear_numero(v.numero), f"{v.creado_en:%Y-%m-%d %H:%M:%S}", sucursal, vendedor, v.metodo_pago,
            _dinero(v.subtotal), _dinero(v.descuento), _dinero(v.total), v.estado, anula or "",
            v.motivo_anulacion or "",
        ]
        for v, vendedor, sucursal, anula in sesion.execute(consulta)
    ]
    registrar(sesion, "reporte_exportado", usuario_id=actor.id, entidad="reportes", detalle={"reporte": "detalle_ventas"})
    return _a_csv(
        ["Venta", "Fecha (UTC)", "Sucursal", "Vendedor", "Pago", "Subtotal", "Descuento", "Total", "Estado",
         "Anulada por", "Motivo"],
        filas,
    )


def exportar_valorizado_csv(sesion: Session, actor: Usuario, sucursal_id: int | None = None) -> str:
    exigir_permiso(sesion, actor, "reportes", "exportar")
    datos = inventario_valorizado(sesion, actor, sucursal_id)
    registrar(sesion, "reporte_exportado", usuario_id=actor.id, entidad="reportes", detalle={"reporte": "inventario_valorizado"})
    filas = [
        [f["sku"], f["nombre"], f["categoria"], f["stock"], _dinero(f["costo"]), _dinero(f["valor"])]
        for f in datos["filas"]
    ]
    filas.append(["", "TOTAL", "", datos["total_unidades"], "", _dinero(datos["total_valor"])])
    return _a_csv(["SKU", "Producto", "Categoría", "Stock", "Costo promedio", "Valor"], filas)
