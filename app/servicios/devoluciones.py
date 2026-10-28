"""Devoluciones parciales o totales de una venta completada.

Reglas:
- Permiso ``ventas.devolver``. Quien no ve todas las ventas solo devuelve las propias.
- Solo ventas completadas. Una venta con devoluciones ya no se puede anular (se devuelve lo que falta).
- Cada línea se puede devolver varias veces mientras queden unidades.
- Reembolso por línea = ingreso de la línea (con descuentos prorrateados) × unidades devueltas /
  unidades vendidas, redondeado al centavo de forma acumulada: al devolver todo se reembolsa
  exactamente lo cobrado por esa línea.
- El stock vuelve a la sucursal de la venta (movimiento ``devolucion``) al costo con que salió.
  Los servicios no mueven existencias.
- Todo o nada: si algo falla no queda nada a medias.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos import Devolucion, DevolucionDetalle, Producto, Usuario, Venta, VentaDetalle
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import aplicar_movimiento, cantidad_entera
from app.servicios.permisos import exigir_permiso
from app.servicios.ventas import (
    CENTAVO,
    METODOS_PAGO,
    _texto,
    _ve_todas,
    formatear_devolucion,
    formatear_numero,
    ingresos_por_linea,
)


def _decimal(valor: Any) -> Decimal:
    return Decimal(str(valor or 0))


def _preparar(sesion: Session, actor: Usuario, venta_id: int, lineas: list[dict[str, Any]]):
    """Valida y calcula. Devuelve ``(venta, [(detalle, cantidad, monto)], total)``."""
    exigir_permiso(sesion, actor, "ventas", "devolver")
    venta = sesion.get(Venta, venta_id)
    if venta is None:
        raise ErrorDeNegocio("La venta no existe.")
    if not _ve_todas(sesion, actor) and venta.vendedor_id != actor.id:
        raise PermisoDenegado("ventas", "ver_todas")
    if venta.estado != "completada":
        raise ErrorDeNegocio(f"La venta {formatear_numero(venta.numero)} está anulada y no admite devoluciones.")
    if not lineas:
        raise ErrorDeNegocio("Indica qué productos se devuelven.")

    pedidas: dict[int, int] = {}
    for linea in lineas:
        detalle_id = linea.get("detalle_id")
        if isinstance(detalle_id, bool) or not isinstance(detalle_id, int):
            raise ErrorDeNegocio("Hay una línea de devolución no válida.")
        cantidad = cantidad_entera(linea.get("cantidad"), "cantidad a devolver")
        pedidas[detalle_id] = pedidas.get(detalle_id, 0) + cantidad

    detalles = list(sesion.scalars(select(VentaDetalle).where(VentaDetalle.venta_id == venta.id).order_by(VentaDetalle.id)))
    por_id = {d.id: d for d in detalles}
    ingresos = dict(zip((d.id for d in detalles), ingresos_por_linea(venta, detalles)))
    previas = sesion.execute(
        select(DevolucionDetalle.detalle_id, func.sum(DevolucionDetalle.cantidad), func.sum(DevolucionDetalle.monto))
        .join(Devolucion, Devolucion.id == DevolucionDetalle.devolucion_id)
        .where(Devolucion.venta_id == venta.id)
        .group_by(DevolucionDetalle.detalle_id)
    ).all()
    cantidad_previa = {i: int(c) for i, c, _ in previas}
    monto_previo = {i: _decimal(m).quantize(CENTAVO, rounding=ROUND_HALF_UP) for i, _, m in previas}

    calculadas: list[tuple[VentaDetalle, int, Decimal]] = []
    total = Decimal("0.00")
    for detalle_id, cantidad in pedidas.items():
        detalle = por_id.get(detalle_id)
        if detalle is None:
            raise ErrorDeNegocio("Una de las líneas no pertenece a esta venta.")
        ya = cantidad_previa.get(detalle_id, 0)
        disponibles = detalle.cantidad - ya
        if cantidad > disponibles:
            sku = sesion.get(Producto, detalle.producto_id).sku
            raise ErrorDeNegocio(f"{sku}: solo se pueden devolver {disponibles} unidad(es); ya se devolvieron {ya}.")
        acumuladas = ya + cantidad
        if acumuladas == detalle.cantidad:
            reembolso_acumulado = ingresos[detalle_id]
        else:
            reembolso_acumulado = (ingresos[detalle_id] * acumuladas / detalle.cantidad).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        monto = max(reembolso_acumulado - monto_previo.get(detalle_id, Decimal("0")), Decimal("0.00"))
        calculadas.append((detalle, cantidad, monto))
        total += monto
    return venta, calculadas, total


def previsualizar_devolucion(sesion: Session, actor: Usuario, venta_id: int, lineas: list[dict[str, Any]]) -> dict:
    """Cuánto se reembolsaría, sin guardar nada."""
    _, calculadas, total = _preparar(sesion, actor, venta_id, lineas)
    return {
        "lineas": [{"detalle_id": d.id, "cantidad": c, "monto": m} for d, c, m in calculadas],
        "total": total,
    }


def registrar_devolucion(
    sesion: Session,
    actor: Usuario,
    venta_id: int,
    lineas: list[dict[str, Any]],
    motivo: str,
    metodo_reembolso: str = "efectivo",
) -> dict:
    """Registra la devolución, regresa el stock y deja usuario, fecha y motivo.

    Cada línea es ``{"detalle_id", "cantidad"}`` (``detalle_id`` sale de ``obtener_venta``).
    """
    motivo = _texto(motivo, "motivo", 200, obligatorio=True)
    metodo = str(metodo_reembolso or "").strip().lower()
    if metodo not in METODOS_PAGO:
        raise ErrorDeNegocio(f"Forma de reembolso no válida. Usa: {', '.join(METODOS_PAGO)}.")
    venta, calculadas, total = _preparar(sesion, actor, venta_id, lineas)

    with sesion.begin_nested():  # todo o nada
        devolucion = Devolucion(
            venta_id=venta.id, usuario_id=actor.id, motivo=motivo, metodo_reembolso=metodo, total=total
        )
        sesion.add(devolucion)
        sesion.flush()
        codigo = formatear_devolucion(devolucion.id)
        for detalle, cantidad, monto in calculadas:
            producto = sesion.get(Producto, detalle.producto_id)
            if producto is not None and not producto.es_servicio:
                aplicar_movimiento(
                    sesion,
                    usuario_id=actor.id,
                    producto_id=detalle.producto_id,
                    sucursal_id=venta.sucursal_id,
                    tipo="devolucion",
                    cantidad=cantidad,
                    costo_unitario=detalle.costo_unitario,  # el costo con el que salió
                    motivo=f"Devolución {codigo} de {formatear_numero(venta.numero)}: {motivo}",
                    referencia_tipo="devolucion",
                    referencia_id=devolucion.id,
                )
            sesion.add(
                DevolucionDetalle(
                    devolucion_id=devolucion.id,
                    detalle_id=detalle.id,
                    cantidad=cantidad,
                    monto=monto,
                    costo_unitario=detalle.costo_unitario,
                )
            )
        registrar(
            sesion, "devolucion_registrada", usuario_id=actor.id, entidad="devoluciones", entidad_id=devolucion.id,
            detalle={
                "venta": formatear_numero(venta.numero), "total": str(total), "motivo": motivo,
                "metodo_reembolso": metodo, "lineas": len(calculadas),
            },
        )
    return {"id": devolucion.id, "codigo": codigo, "total": total, "venta": formatear_numero(venta.numero)}
