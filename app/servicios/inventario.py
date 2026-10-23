"""Inventario: kardex, existencias por sucursal, compras, mermas, ajustes y traslados.

Reglas:
- ``existencias`` solo cambia dentro de ``aplicar_movimiento``, que escribe el
  movimiento de kardex en la misma transacción. Nadie edita el stock a mano.
- Una operación que deje el stock negativo se rechaza (y además la base de datos
  lo impide con un CHECK).
- El descuento usa un UPDATE condicional, así dos operaciones simultáneas no
  pueden vender o sacar la misma última unidad.
- Costeo: promedio ponderado. Cada compra recalcula el costo promedio del producto
  con el stock total de todas las sucursales y deja el cambio en el historial.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.modelos import (
    Compra,
    CompraDetalle,
    Existencia,
    MovimientoInventario,
    Producto,
    Proveedor,
    Sucursal,
    Traslado,
    Usuario,
)
from app.servicios.auditoria import registrar
from app.servicios.catalogo import a_dinero, actualizar_costo_promedio
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import exigir_permiso

CENTAVO = Decimal("0.01")
_EXISTENCIAS = Existencia.__table__

# tipo -> signo: 1 solo entra, -1 solo sale, 0 el signo lo da la cantidad (ajuste).
TIPOS: dict[str, int] = {
    "entrada": 1,
    "salida": -1,
    "merma": -1,
    "ajuste": 0,
    "devolucion": 1,
    "anulacion": 1,
    "traslado_entrada": 1,
    "traslado_salida": -1,
}


# ---- utilidades -------------------------------------------------------------------


def _cantidad(valor: Any, campo: str, minimo: int = 1) -> int:
    if isinstance(valor, bool):
        raise ErrorDeNegocio(f"El campo {campo} debe ser un número entero.")
    try:
        numero = int(str(valor).strip())
    except ValueError:
        raise ErrorDeNegocio(f"El campo {campo} debe ser un número entero.") from None
    if numero < minimo:
        raise ErrorDeNegocio(
            f"El campo {campo} debe ser {'mayor que cero' if minimo == 1 else f'al menos {minimo}'}."
        )
    return numero


def _texto(valor: Any, campo: str, largo: int, obligatorio: bool = False) -> str | None:
    texto = "" if valor is None else str(valor).strip()
    if not texto:
        if obligatorio:
            raise ErrorDeNegocio(f"El campo {campo} es obligatorio.")
        return None
    if len(texto) > largo:
        raise ErrorDeNegocio(f"El campo {campo} admite como máximo {largo} caracteres.")
    return texto


def _producto(sesion: Session, producto_id: int | None) -> Producto:
    producto = None if producto_id is None else sesion.get(Producto, producto_id)
    if producto is None:
        raise ErrorDeNegocio("El producto no existe.")
    return producto


def _sucursal(sesion: Session, sucursal_id: int) -> Sucursal:
    sucursal = sesion.get(Sucursal, sucursal_id)
    if sucursal is None:
        raise ErrorDeNegocio("La sucursal no existe.")
    if not sucursal.activa:
        raise ErrorDeNegocio(f"La sucursal '{sucursal.nombre}' está desactivada.")
    return sucursal


def stock_actual(sesion: Session, producto_id: int, sucursal_id: int | None = None) -> int:
    """Existencias de un producto en una sucursal, o en total si no se indica sucursal."""
    consulta = select(func.coalesce(func.sum(Existencia.cantidad), 0)).where(
        Existencia.producto_id == producto_id
    )
    if sucursal_id is not None:
        consulta = consulta.where(Existencia.sucursal_id == sucursal_id)
    return int(sesion.scalar(consulta) or 0)


def costo_promedio_ponderado(
    stock: int, costo_actual: Decimal, cantidad: int, costo_compra: Decimal
) -> Decimal:
    """Nuevo costo promedio al entrar ``cantidad`` unidades a ``costo_compra``."""
    if stock <= 0:
        return costo_compra
    total = Decimal(stock) * costo_actual + Decimal(cantidad) * costo_compra
    return (total / Decimal(stock + cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


# ---- núcleo: único punto que modifica las existencias --------------------------------


def _aplicar_delta(sesion: Session, producto_id: int, sucursal_id: int, delta: int) -> int:
    """Suma ``delta`` a la existencia y devuelve el saldo resultante.

    Si el resultado fuera negativo lanza ``ErrorDeNegocio`` sin cambiar nada.
    """
    donde = (_EXISTENCIAS.c.producto_id == producto_id) & (_EXISTENCIAS.c.sucursal_id == sucursal_id)
    actualizadas = sesion.execute(
        update(_EXISTENCIAS)
        .where(donde, _EXISTENCIAS.c.cantidad + delta >= 0)
        .values(cantidad=_EXISTENCIAS.c.cantidad + delta)
    ).rowcount

    if not actualizadas:
        actual = sesion.scalar(select(_EXISTENCIAS.c.cantidad).where(donde))
        if actual is None and delta > 0:
            try:
                with sesion.begin_nested():
                    sesion.execute(
                        insert(_EXISTENCIAS).values(
                            producto_id=producto_id, sucursal_id=sucursal_id, cantidad=delta
                        )
                    )
            except IntegrityError:
                # Otra operación creó la fila a la vez: reintenta como actualización.
                return _aplicar_delta(sesion, producto_id, sucursal_id, delta)
        else:
            disponible = actual or 0
            raise ErrorDeNegocio(
                f"Stock insuficiente: hay {disponible} unidad(es) y se necesitan {-delta}."
            )
    return int(sesion.scalar(select(_EXISTENCIAS.c.cantidad).where(donde)))


def aplicar_movimiento(
    sesion: Session,
    *,
    usuario_id: int,
    producto_id: int,
    sucursal_id: int,
    tipo: str,
    cantidad: int,
    costo_unitario: Decimal | None = None,
    motivo: str | None = None,
    referencia_tipo: str | None = None,
    referencia_id: int | None = None,
) -> MovimientoInventario:
    """Registra un movimiento de kardex y actualiza la existencia, de forma atómica.

    NO comprueba permisos: la llaman otros servicios (compras, ventas, traslados)
    después de haber comprobado los suyos. ``cantidad`` es positiva, salvo en el
    tipo ``ajuste``, donde el signo indica si entra o sale.
    """
    if tipo not in TIPOS:
        raise ErrorDeNegocio(f"Tipo de movimiento desconocido: {tipo}.")
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad == 0:
        raise ErrorDeNegocio("La cantidad debe ser un número entero distinto de cero.")
    signo = TIPOS[tipo]
    if signo != 0 and cantidad < 0:
        raise ErrorDeNegocio("La cantidad debe ser positiva; el tipo de movimiento define el sentido.")
    delta = cantidad * signo if signo != 0 else cantidad

    producto = _producto(sesion, producto_id)
    _sucursal(sesion, sucursal_id)
    saldo = _aplicar_delta(sesion, producto_id, sucursal_id, delta)

    movimiento = MovimientoInventario(
        producto_id=producto_id,
        sucursal_id=sucursal_id,
        tipo=tipo,
        cantidad=delta,
        saldo_despues=saldo,
        costo_unitario=producto.costo_promedio if costo_unitario is None else costo_unitario,
        motivo=motivo,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        usuario_id=usuario_id,
    )
    sesion.add(movimiento)
    sesion.flush()
    return movimiento


# ---- sucursales y proveedores -------------------------------------------------------


def crear_sucursal(sesion: Session, actor: Usuario, nombre: str, direccion: str | None = None) -> Sucursal:
    exigir_permiso(sesion, actor, "inventario", "crear")
    nombre = _texto(nombre, "nombre", 100, obligatorio=True)
    if sesion.scalar(select(Sucursal.id).where(Sucursal.nombre.ilike(nombre))) is not None:
        raise ErrorDeNegocio(f"Ya existe la sucursal '{nombre}'.")
    sucursal = Sucursal(nombre=nombre, direccion=_texto(direccion, "dirección", 200))
    sesion.add(sucursal)
    sesion.flush()
    registrar(
        sesion, "sucursal_creada", usuario_id=actor.id, entidad="sucursales",
        entidad_id=sucursal.id, detalle={"nombre": nombre},
    )
    return sucursal


def listar_sucursales(sesion: Session, actor: Usuario, incluir_inactivas: bool = False) -> list[dict]:
    exigir_permiso(sesion, actor, "inventario", "ver")
    consulta = select(Sucursal).order_by(Sucursal.id)
    if not incluir_inactivas:
        consulta = consulta.where(Sucursal.activa.is_(True))
    return [{"id": s.id, "nombre": s.nombre, "activa": s.activa} for s in sesion.scalars(consulta)]


def crear_proveedor(sesion: Session, actor: Usuario, nombre: str, contacto: str | None = None) -> Proveedor:
    exigir_permiso(sesion, actor, "inventario", "crear")
    nombre = _texto(nombre, "nombre", 120, obligatorio=True)
    if sesion.scalar(select(Proveedor.id).where(Proveedor.nombre.ilike(nombre))) is not None:
        raise ErrorDeNegocio(f"Ya existe el proveedor '{nombre}'.")
    proveedor = Proveedor(nombre=nombre, contacto=_texto(contacto, "contacto", 200))
    sesion.add(proveedor)
    sesion.flush()
    registrar(
        sesion, "proveedor_creado", usuario_id=actor.id, entidad="proveedores",
        entidad_id=proveedor.id, detalle={"nombre": nombre},
    )
    return proveedor


def listar_proveedores(sesion: Session, actor: Usuario, incluir_inactivos: bool = False) -> list[dict]:
    exigir_permiso(sesion, actor, "inventario", "ver")
    consulta = select(Proveedor).order_by(Proveedor.nombre)
    if not incluir_inactivos:
        consulta = consulta.where(Proveedor.activo.is_(True))
    return [
        {"id": p.id, "nombre": p.nombre, "contacto": p.contacto, "activo": p.activo}
        for p in sesion.scalars(consulta)
    ]


def editar_proveedor(
    sesion: Session, actor: Usuario, proveedor_id: int, nombre: str, contacto: str | None = None
) -> Proveedor:
    exigir_permiso(sesion, actor, "inventario", "editar")
    proveedor = sesion.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise ErrorDeNegocio("El proveedor no existe.")
    nombre = _texto(nombre, "nombre", 120, obligatorio=True)
    otro = sesion.scalar(
        select(Proveedor.id).where(Proveedor.nombre.ilike(nombre), Proveedor.id != proveedor_id)
    )
    if otro is not None:
        raise ErrorDeNegocio(f"Ya existe el proveedor '{nombre}'.")
    proveedor.nombre = nombre
    proveedor.contacto = _texto(contacto, "contacto", 200)
    registrar(
        sesion, "proveedor_editado", usuario_id=actor.id, entidad="proveedores", entidad_id=proveedor.id,
        detalle={"nombre": nombre},
    )
    return proveedor


def establecer_proveedor_activo(sesion: Session, actor: Usuario, proveedor_id: int, activo: bool) -> None:
    exigir_permiso(sesion, actor, "inventario", "editar")
    proveedor = sesion.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise ErrorDeNegocio("El proveedor no existe.")
    if proveedor.activo == activo:
        return
    proveedor.activo = activo
    registrar(
        sesion, "proveedor_activado" if activo else "proveedor_desactivado",
        usuario_id=actor.id, entidad="proveedores", entidad_id=proveedor.id,
    )


# ---- operaciones de inventario -------------------------------------------------------


def registrar_compra(
    sesion: Session,
    actor: Usuario,
    *,
    sucursal_id: int,
    proveedor_id: int,
    lineas: list[dict[str, Any]],
    nota: str | None = None,
) -> Compra:
    """Compra a un proveedor: entra stock y recalcula el costo promedio ponderado.

    Cada línea es ``{"producto_id", "cantidad", "costo_unitario"}``.
    """
    exigir_permiso(sesion, actor, "inventario", "crear")
    _sucursal(sesion, sucursal_id)
    proveedor = sesion.get(Proveedor, proveedor_id)
    if proveedor is None or not proveedor.activo:
        raise ErrorDeNegocio("El proveedor no existe o está desactivado.")
    if not lineas:
        raise ErrorDeNegocio("La compra debe tener al menos un producto.")

    # Se valida todo antes de tocar nada.
    validadas: list[tuple[Producto, int, Decimal]] = []
    for linea in lineas:
        producto = _producto(sesion, linea.get("producto_id"))
        if not producto.activo:
            raise ErrorDeNegocio(f"El producto {producto.sku} está desactivado.")
        cantidad = _cantidad(linea.get("cantidad"), f"cantidad de {producto.sku}")
        costo = a_dinero(linea.get("costo_unitario"), f"costo de {producto.sku}")
        validadas.append((producto, cantidad, costo))

    # Todo o nada: si algo falla a mitad, se deshace la compra completa.
    with sesion.begin_nested():
        compra = Compra(
            proveedor_id=proveedor.id,
            sucursal_id=sucursal_id,
            usuario_id=actor.id,
            nota=_texto(nota, "nota", 200),
        )
        sesion.add(compra)
        sesion.flush()

        total = Decimal("0")
        for producto, cantidad, costo in validadas:
            existente = stock_actual(sesion, producto.id)  # todas las sucursales, antes de entrar
            nuevo_costo = costo_promedio_ponderado(existente, producto.costo_promedio, cantidad, costo)
            aplicar_movimiento(
                sesion,
                usuario_id=actor.id,
                producto_id=producto.id,
                sucursal_id=sucursal_id,
                tipo="entrada",
                cantidad=cantidad,
                costo_unitario=costo,
                motivo=f"Compra a {proveedor.nombre}",
                referencia_tipo="compra",
                referencia_id=compra.id,
            )
            actualizar_costo_promedio(sesion, producto, nuevo_costo, actor.id)
            sesion.add(
                CompraDetalle(compra_id=compra.id, producto_id=producto.id, cantidad=cantidad, costo_unitario=costo)
            )
            total += Decimal(cantidad) * costo
        compra.total = total.quantize(CENTAVO, rounding=ROUND_HALF_UP)

        registrar(
            sesion, "compra_registrada", usuario_id=actor.id, entidad="compras", entidad_id=compra.id,
            detalle={"proveedor": proveedor.nombre, "sucursal_id": sucursal_id, "lineas": len(validadas), "total": str(compra.total)},
        )
    return compra


def registrar_merma(
    sesion: Session, actor: Usuario, *, producto_id: int, sucursal_id: int, cantidad: Any, motivo: str
) -> MovimientoInventario:
    """Baja de stock por pérdida, daño o vencimiento. El motivo es obligatorio."""
    exigir_permiso(sesion, actor, "inventario", "crear")
    motivo = _texto(motivo, "motivo", 200, obligatorio=True)
    cantidad = _cantidad(cantidad, "cantidad")
    movimiento = aplicar_movimiento(
        sesion, usuario_id=actor.id, producto_id=producto_id, sucursal_id=sucursal_id,
        tipo="merma", cantidad=cantidad, motivo=motivo,
    )
    registrar(
        sesion, "merma_registrada", usuario_id=actor.id, entidad="productos", entidad_id=producto_id,
        detalle={"sucursal_id": sucursal_id, "cantidad": cantidad, "motivo": motivo},
    )
    return movimiento


def ajustar_stock(
    sesion: Session, actor: Usuario, *, producto_id: int, sucursal_id: int, conteo_fisico: Any, motivo: str
) -> MovimientoInventario | None:
    """Deja el stock igual al conteo físico, registrando la diferencia. Motivo obligatorio.

    Devuelve ``None`` si el conteo coincide con el sistema (no hay nada que ajustar).
    """
    exigir_permiso(sesion, actor, "inventario", "editar")
    motivo = _texto(motivo, "motivo", 200, obligatorio=True)
    conteo = _cantidad(conteo_fisico, "conteo físico", minimo=0)
    _producto(sesion, producto_id)
    _sucursal(sesion, sucursal_id)
    actual = stock_actual(sesion, producto_id, sucursal_id)
    diferencia = conteo - actual
    if diferencia == 0:
        return None
    movimiento = aplicar_movimiento(
        sesion, usuario_id=actor.id, producto_id=producto_id, sucursal_id=sucursal_id,
        tipo="ajuste", cantidad=diferencia, motivo=motivo,
    )
    registrar(
        sesion, "ajuste_inventario", usuario_id=actor.id, entidad="productos", entidad_id=producto_id,
        detalle={"sucursal_id": sucursal_id, "antes": actual, "despues": conteo, "motivo": motivo},
    )
    return movimiento


def trasladar(
    sesion: Session,
    actor: Usuario,
    *,
    producto_id: int,
    origen_id: int,
    destino_id: int,
    cantidad: Any,
    nota: str | None = None,
) -> Traslado:
    """Pasa stock de una sucursal a otra. Si el origen no tiene suficiente, no pasa nada."""
    exigir_permiso(sesion, actor, "inventario", "crear")
    cantidad = _cantidad(cantidad, "cantidad")
    if origen_id == destino_id:
        raise ErrorDeNegocio("La sucursal de origen y la de destino deben ser distintas.")
    _producto(sesion, producto_id)
    origen = _sucursal(sesion, origen_id)
    destino = _sucursal(sesion, destino_id)

    with sesion.begin_nested():  # todo o nada: no queda un traslado a medias
        traslado = Traslado(
            producto_id=producto_id, cantidad=cantidad, origen_id=origen_id, destino_id=destino_id,
            usuario_id=actor.id, nota=_texto(nota, "nota", 200),
        )
        sesion.add(traslado)
        sesion.flush()
        for tipo, sucursal, texto in (
            ("traslado_salida", origen, f"Traslado a {destino.nombre}"),
            ("traslado_entrada", destino, f"Traslado desde {origen.nombre}"),
        ):
            aplicar_movimiento(
                sesion, usuario_id=actor.id, producto_id=producto_id, sucursal_id=sucursal.id,
                tipo=tipo, cantidad=cantidad, motivo=texto, referencia_tipo="traslado", referencia_id=traslado.id,
            )
        registrar(
            sesion, "traslado_registrado", usuario_id=actor.id, entidad="traslados", entidad_id=traslado.id,
            detalle={"producto_id": producto_id, "cantidad": cantidad, "origen": origen.nombre, "destino": destino.nombre},
        )
    return traslado


# ---- consultas -----------------------------------------------------------------------


def _consultar_existencias(
    sesion: Session,
    sucursal_id: int | None,
    texto: str,
    solo_bajo_minimo: bool,
    incluir_inactivos: bool,
) -> list[dict]:
    suma = select(Existencia.producto_id, func.sum(Existencia.cantidad).label("stock")).group_by(
        Existencia.producto_id
    )
    if sucursal_id is not None:
        suma = suma.where(Existencia.sucursal_id == sucursal_id)
    suma = suma.subquery()
    stock = func.coalesce(suma.c.stock, 0)

    consulta = (
        select(Producto, stock)
        .outerjoin(suma, suma.c.producto_id == Producto.id)
        .options(joinedload(Producto.categoria))
        .order_by(Producto.nombre)
    )
    texto = (texto or "").strip()
    if texto:
        patron = f"%{texto}%"
        consulta = consulta.where(
            or_(Producto.nombre.ilike(patron), Producto.sku.ilike(patron), Producto.codigo_barras.ilike(patron))
        )
    if not incluir_inactivos:
        consulta = consulta.where(Producto.activo.is_(True))
    if solo_bajo_minimo:
        consulta = consulta.where(Producto.stock_minimo > 0, stock <= Producto.stock_minimo)

    filas = []
    for producto, cantidad in sesion.execute(consulta).unique():
        cantidad = int(cantidad)
        filas.append(
            {
                "producto_id": producto.id,
                "sku": producto.sku,
                "nombre": producto.nombre,
                "categoria": producto.categoria.nombre,
                "stock": cantidad,
                "stock_minimo": producto.stock_minimo,
                "costo": producto.costo_promedio,
                "valor": (Decimal(cantidad) * producto.costo_promedio).quantize(CENTAVO),
                "bajo_minimo": producto.stock_minimo > 0 and cantidad <= producto.stock_minimo,
                "activo": producto.activo,
            }
        )
    return filas


def existencias(
    sesion: Session,
    actor: Usuario,
    sucursal_id: int | None = None,
    texto: str = "",
    solo_bajo_minimo: bool = False,
    incluir_inactivos: bool = False,
) -> list[dict]:
    """Stock por producto en una sucursal (o el total si no se indica)."""
    exigir_permiso(sesion, actor, "inventario", "ver")
    return _consultar_existencias(sesion, sucursal_id, texto, solo_bajo_minimo, incluir_inactivos)


def alertas_stock_bajo(sesion: Session, actor: Usuario, sucursal_id: int | None = None) -> list[dict]:
    """Productos con stock mínimo configurado cuyo stock es menor o igual a ese mínimo."""
    return existencias(sesion, actor, sucursal_id, solo_bajo_minimo=True)


def _consultar_kardex(
    sesion: Session,
    producto_id: int,
    sucursal_id: int | None,
    desde: datetime | None,
    hasta: datetime | None,
) -> list[dict]:
    consulta = (
        select(MovimientoInventario, Sucursal.nombre, Usuario.nombre)
        .join(Sucursal, Sucursal.id == MovimientoInventario.sucursal_id)
        .join(Usuario, Usuario.id == MovimientoInventario.usuario_id)
        .where(MovimientoInventario.producto_id == producto_id)
        .order_by(MovimientoInventario.id)
    )
    if sucursal_id is not None:
        consulta = consulta.where(MovimientoInventario.sucursal_id == sucursal_id)
    if desde is not None:
        consulta = consulta.where(MovimientoInventario.creado_en >= desde)
    if hasta is not None:
        consulta = consulta.where(MovimientoInventario.creado_en <= hasta)
    return [
        {
            "id": m.id,
            "fecha": m.creado_en,
            "sucursal": sucursal,
            "tipo": m.tipo,
            "cantidad": m.cantidad,
            "saldo": m.saldo_despues,
            "costo": m.costo_unitario,
            "motivo": m.motivo,
            "referencia": f"{m.referencia_tipo} #{m.referencia_id}" if m.referencia_tipo else "",
            "usuario": usuario,
        }
        for m, sucursal, usuario in sesion.execute(consulta)
    ]


def kardex(
    sesion: Session,
    actor: Usuario,
    producto_id: int,
    sucursal_id: int | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> list[dict]:
    """Movimientos de un producto, del más antiguo al más reciente, con saldo."""
    exigir_permiso(sesion, actor, "inventario", "ver")
    _producto(sesion, producto_id)
    return _consultar_kardex(sesion, producto_id, sucursal_id, desde, hasta)


def verificar_consistencia(sesion: Session) -> list[dict]:
    """Compara cada existencia con la suma de sus movimientos y con el último saldo.

    Devuelve la lista de diferencias; vacía significa que el kardex y el stock coinciden.
    """
    sumas = {
        (p, s): int(total)
        for p, s, total in sesion.execute(
            select(
                MovimientoInventario.producto_id,
                MovimientoInventario.sucursal_id,
                func.sum(MovimientoInventario.cantidad),
            ).group_by(MovimientoInventario.producto_id, MovimientoInventario.sucursal_id)
        )
    }
    actuales = {
        (p, s): int(c)
        for p, s, c in sesion.execute(
            select(Existencia.producto_id, Existencia.sucursal_id, Existencia.cantidad)
        )
    }
    ultimos = {}
    for p, s, saldo in sesion.execute(
        select(
            MovimientoInventario.producto_id,
            MovimientoInventario.sucursal_id,
            MovimientoInventario.saldo_despues,
        ).order_by(MovimientoInventario.id)
    ):
        ultimos[(p, s)] = int(saldo)

    diferencias = []
    for clave in sorted(set(sumas) | set(actuales)):
        esperado = sumas.get(clave, 0)
        real = actuales.get(clave, 0)
        ultimo = ultimos.get(clave, 0)
        if esperado != real or ultimo != real:
            diferencias.append(
                {
                    "producto_id": clave[0],
                    "sucursal_id": clave[1],
                    "suma_movimientos": esperado,
                    "existencia": real,
                    "ultimo_saldo": ultimo,
                }
            )
    return diferencias


# ---- exportación ---------------------------------------------------------------------


def _a_csv(encabezados: list[str], filas: list[list[Any]]) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    escritor.writerows(filas)
    return salida.getvalue()


def exportar_existencias_csv(sesion: Session, actor: Usuario, sucursal_id: int | None = None) -> str:
    exigir_permiso(sesion, actor, "inventario", "exportar")
    filas = _consultar_existencias(sesion, sucursal_id, "", False, False)
    return _a_csv(
        ["SKU", "Producto", "Categoría", "Stock", "Stock mínimo", "Costo promedio", "Valor", "Stock bajo"],
        [
            [f["sku"], f["nombre"], f["categoria"], f["stock"], f["stock_minimo"], f"{f['costo']:.2f}",
             f"{f['valor']:.2f}", "sí" if f["bajo_minimo"] else "no"]
            for f in filas
        ],
    )


def exportar_kardex_csv(
    sesion: Session, actor: Usuario, producto_id: int, sucursal_id: int | None = None
) -> str:
    exigir_permiso(sesion, actor, "inventario", "exportar")
    _producto(sesion, producto_id)
    movimientos = _consultar_kardex(sesion, producto_id, sucursal_id, None, None)
    return _a_csv(
        ["Fecha (UTC)", "Sucursal", "Tipo", "Cantidad", "Saldo", "Costo unitario", "Motivo", "Referencia", "Usuario"],
        [
            [f"{m['fecha']:%Y-%m-%d %H:%M:%S}", m["sucursal"], m["tipo"], m["cantidad"], m["saldo"],
             f"{m['costo']:.2f}", m["motivo"] or "", m["referencia"], m["usuario"]]
            for m in movimientos
        ],
    )


# ---- versiones públicas de utilidades internas (las usan otros servicios) -------------


def obtener_sucursal_activa(sesion: Session, sucursal_id: int) -> Sucursal:
    return _sucursal(sesion, sucursal_id)


def cantidad_entera(valor: Any, campo: str, minimo: int = 1) -> int:
    return _cantidad(valor, campo, minimo)
