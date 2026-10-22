"""Ventas (punto de venta): venta atómica, anulación, clientes y consultas.

Reglas:
- El vendedor es siempre el usuario de la sesión (``actor``); no hay forma de elegirlo.
- Precio y costo salen del producto en el momento de vender y se congelan en el detalle.
  El cliente de la función no puede fijar el precio, solo aplicar descuentos.
- Verificar stock, descontarlo y registrar la venta ocurre en la misma transacción
  (con savepoint): o se guarda todo o no queda nada.
- Las ventas no se borran, se anulan con motivo, usuario y fecha; la anulación
  devuelve el stock con movimientos de kardex (tipo ``anulacion``).
- ``ventas.ver`` permite ver las ventas propias; ``ventas.ver_todas``, las de todos.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import ahora_utc
from app.modelos import Cliente, Producto, Sucursal, Usuario, Venta, VentaDetalle
from app.servicios.auditoria import registrar
from app.servicios.catalogo import a_dinero
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import (
    aplicar_movimiento,
    cantidad_entera,
    obtener_sucursal_activa,
    stock_actual,
)
from app.servicios.permisos import exigir_permiso, permisos_efectivos

CENTAVO = Decimal("0.01")
METODOS_PAGO = ("efectivo", "tarjeta", "transferencia", "otro")


def formatear_numero(numero: int) -> str:
    return f"V-{numero:06d}"


def _texto(valor: Any, campo: str, largo: int, obligatorio: bool = False) -> str | None:
    texto = "" if valor is None else str(valor).strip()
    if not texto:
        if obligatorio:
            raise ErrorDeNegocio(f"El campo {campo} es obligatorio.")
        return None
    if len(texto) > largo:
        raise ErrorDeNegocio(f"El campo {campo} admite como máximo {largo} caracteres.")
    return texto


# ---- clientes -----------------------------------------------------------------------


def crear_cliente(
    sesion: Session, actor: Usuario, nombre: str, telefono: str | None = None, correo: str | None = None
) -> Cliente:
    exigir_permiso(sesion, actor, "ventas", "crear")
    cliente = Cliente(
        nombre=_texto(nombre, "nombre", 120, obligatorio=True),
        telefono=_texto(telefono, "teléfono", 30),
        correo=_texto(correo, "correo", 150),
    )
    sesion.add(cliente)
    sesion.flush()
    registrar(
        sesion, "cliente_creado", usuario_id=actor.id, entidad="clientes", entidad_id=cliente.id,
        detalle={"nombre": cliente.nombre},
    )
    return cliente


def listar_clientes(sesion: Session, actor: Usuario) -> list[dict]:
    exigir_permiso(sesion, actor, "ventas", "ver")
    consulta = select(Cliente).where(Cliente.activo.is_(True)).order_by(Cliente.nombre)
    return [
        {"id": c.id, "nombre": c.nombre, "telefono": c.telefono, "correo": c.correo}
        for c in sesion.scalars(consulta)
    ]


# ---- búsqueda de productos para vender -----------------------------------------------


def _producto_vendible(sesion: Session, producto: Producto, sucursal_id: int) -> dict:
    return {
        "id": producto.id,
        "sku": producto.sku,
        "nombre": producto.nombre,
        "precio": producto.precio,
        "stock": stock_actual(sesion, producto.id, sucursal_id),
    }


def producto_para_venta(sesion: Session, actor: Usuario, codigo: str, sucursal_id: int) -> dict | None:
    """Coincidencia exacta por código de barras o SKU (lo que envía un lector USB).

    Solo productos activos. Devuelve precio y stock de la sucursal, o ``None``.
    """
    exigir_permiso(sesion, actor, "ventas", "crear")
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    producto = sesion.scalar(
        select(Producto).where(
            or_(Producto.codigo_barras == codigo, Producto.sku == codigo.upper()),
            Producto.activo.is_(True),
        )
    )
    return _producto_vendible(sesion, producto, sucursal_id) if producto else None


def buscar_para_venta(
    sesion: Session, actor: Usuario, texto: str, sucursal_id: int, limite: int = 20
) -> list[dict]:
    """Búsqueda por nombre, SKU, código o marca entre los productos activos."""
    exigir_permiso(sesion, actor, "ventas", "crear")
    texto = (texto or "").strip()
    if not texto:
        return []
    patron = f"%{texto}%"
    productos = sesion.scalars(
        select(Producto)
        .where(
            Producto.activo.is_(True),
            or_(
                Producto.nombre.ilike(patron),
                Producto.sku.ilike(patron),
                Producto.codigo_barras.ilike(patron),
                Producto.marca.ilike(patron),
            ),
        )
        .order_by(Producto.nombre)
        .limit(limite)
    )
    return [_producto_vendible(sesion, p, sucursal_id) for p in productos]


# ---- registrar una venta -------------------------------------------------------------


def _siguiente_numero(sesion: Session) -> int:
    return int(sesion.scalar(select(func.coalesce(func.max(Venta.numero), 0))) or 0) + 1


def registrar_venta(
    sesion: Session,
    actor: Usuario,
    *,
    sucursal_id: int,
    lineas: list[dict[str, Any]],
    metodo_pago: str,
    cliente_id: int | None = None,
    descuento: Any = 0,
    nota: str | None = None,
) -> Venta:
    """Registra una venta y descuenta el stock de forma atómica.

    Cada línea es ``{"producto_id", "cantidad"}`` con ``"descuento"`` opcional (monto
    en dinero para esa línea). ``descuento`` es un monto sobre el total de la venta.
    """
    exigir_permiso(sesion, actor, "ventas", "crear")
    obtener_sucursal_activa(sesion, sucursal_id)

    metodo = str(metodo_pago or "").strip().lower()
    if metodo not in METODOS_PAGO:
        raise ErrorDeNegocio(f"Método de pago no válido. Usa: {', '.join(METODOS_PAGO)}.")
    if cliente_id is not None:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None or not cliente.activo:
            raise ErrorDeNegocio("El cliente no existe o está desactivado.")
    if not lineas:
        raise ErrorDeNegocio("La venta debe tener al menos un producto.")

    # Se valida todo y se calculan los importes antes de tocar el inventario.
    validadas: list[tuple[Producto, int, Decimal, Decimal]] = []
    subtotal = Decimal("0")
    for linea in lineas:
        producto_id = linea.get("producto_id")
        producto = None if producto_id is None else sesion.get(Producto, producto_id)
        if producto is None:
            raise ErrorDeNegocio("Hay un producto que no existe.")
        if not producto.activo:
            raise ErrorDeNegocio(f"El producto {producto.sku} está desactivado y no se puede vender.")
        cantidad = cantidad_entera(linea.get("cantidad"), f"cantidad de {producto.sku}")
        descuento_linea = a_dinero(linea.get("descuento") or 0, f"descuento de {producto.sku}")
        bruto = Decimal(cantidad) * producto.precio
        if descuento_linea > bruto:
            raise ErrorDeNegocio(f"El descuento de {producto.sku} no puede superar el importe de la línea.")
        validadas.append((producto, cantidad, descuento_linea, producto.precio))
        subtotal += bruto - descuento_linea

    descuento_total = a_dinero(descuento or 0, "descuento")
    if descuento_total > subtotal:
        raise ErrorDeNegocio("El descuento no puede ser mayor que el subtotal de la venta.")
    subtotal = subtotal.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    total = (subtotal - descuento_total).quantize(CENTAVO, rounding=ROUND_HALF_UP)

    for intento in range(5):
        try:
            with sesion.begin_nested():  # todo o nada
                venta = Venta(
                    numero=_siguiente_numero(sesion),
                    sucursal_id=sucursal_id,
                    vendedor_id=actor.id,  # siempre el usuario de la sesión
                    cliente_id=cliente_id,
                    metodo_pago=metodo,
                    subtotal=subtotal,
                    descuento=descuento_total,
                    total=total,
                    nota=_texto(nota, "nota", 200),
                )
                sesion.add(venta)
                sesion.flush()
                for producto, cantidad, descuento_linea, precio in validadas:
                    costo = producto.costo_promedio
                    try:
                        aplicar_movimiento(
                            sesion,
                            usuario_id=actor.id,
                            producto_id=producto.id,
                            sucursal_id=sucursal_id,
                            tipo="salida",
                            cantidad=cantidad,
                            costo_unitario=costo,
                            motivo=f"Venta {formatear_numero(venta.numero)}",
                            referencia_tipo="venta",
                            referencia_id=venta.id,
                        )
                    except ErrorDeNegocio as error:
                        raise ErrorDeNegocio(f"{producto.sku} · {producto.nombre}: {error}") from None
                    sesion.add(
                        VentaDetalle(
                            venta_id=venta.id,
                            producto_id=producto.id,
                            cantidad=cantidad,
                            precio_unitario=precio,
                            costo_unitario=costo,
                            descuento_linea=descuento_linea,
                        )
                    )
                registrar(
                    sesion, "venta_registrada", usuario_id=actor.id, entidad="ventas", entidad_id=venta.id,
                    detalle={"numero": venta.numero, "total": str(total), "metodo_pago": metodo, "lineas": len(validadas)},
                )
            return venta
        except IntegrityError:
            # Dos ventas tomaron el mismo número a la vez: se reintenta con el siguiente.
            if intento == 4:
                raise ErrorDeNegocio("No se pudo asignar el número de venta. Intenta de nuevo.") from None
    raise AssertionError("inalcanzable")  # pragma: no cover


# ---- anulación ---------------------------------------------------------------------


def anular_venta(sesion: Session, actor: Usuario, venta_id: int, motivo: str) -> Venta:
    """Anula una venta completada y devuelve el stock. Deja usuario, fecha y motivo."""
    exigir_permiso(sesion, actor, "ventas", "anular")
    motivo = _texto(motivo, "motivo", 200, obligatorio=True)
    venta = sesion.get(Venta, venta_id)
    if venta is None:
        raise ErrorDeNegocio("La venta no existe.")
    if venta.estado == "anulada":
        raise ErrorDeNegocio(f"La venta {formatear_numero(venta.numero)} ya está anulada.")

    with sesion.begin_nested():
        venta.estado = "anulada"
        venta.anulada_por = actor.id
        venta.anulada_en = ahora_utc()
        venta.motivo_anulacion = motivo
        detalles = sesion.scalars(
            select(VentaDetalle).where(VentaDetalle.venta_id == venta.id).order_by(VentaDetalle.id)
        ).all()
        for detalle in detalles:
            aplicar_movimiento(
                sesion,
                usuario_id=actor.id,
                producto_id=detalle.producto_id,
                sucursal_id=venta.sucursal_id,
                tipo="anulacion",
                cantidad=detalle.cantidad,
                costo_unitario=detalle.costo_unitario,  # el costo con el que salió
                motivo=f"Anulación de {formatear_numero(venta.numero)}: {motivo}",
                referencia_tipo="venta",
                referencia_id=venta.id,
            )
        registrar(
            sesion, "venta_anulada", usuario_id=actor.id, entidad="ventas", entidad_id=venta.id,
            detalle={"numero": venta.numero, "total": str(venta.total), "motivo": motivo},
        )
    return venta


# ---- consultas -----------------------------------------------------------------------


def _ve_todas(sesion: Session, actor: Usuario) -> bool:
    """``True`` si ve las ventas de todos; ``False`` si solo las propias. Sin permiso: 403."""
    efectivos = permisos_efectivos(sesion, actor)
    if ("ventas", "ver_todas") in efectivos:
        return True
    if ("ventas", "ver") in efectivos:
        return False
    raise PermisoDenegado("ventas", "ver")


def obtener_venta(sesion: Session, actor: Usuario, venta_id: int) -> dict:
    """Venta con sus líneas (para el comprobante). No incluye costos."""
    todas = _ve_todas(sesion, actor)
    venta = sesion.get(Venta, venta_id)
    if venta is None:
        raise ErrorDeNegocio("La venta no existe.")
    if not todas and venta.vendedor_id != actor.id:
        raise PermisoDenegado("ventas", "ver_todas")

    vendedor = sesion.get(Usuario, venta.vendedor_id)
    cliente = sesion.get(Cliente, venta.cliente_id) if venta.cliente_id else None
    sucursal = sesion.get(Sucursal, venta.sucursal_id)
    anulador = sesion.get(Usuario, venta.anulada_por) if venta.anulada_por else None
    lineas = []
    filas = sesion.execute(
        select(VentaDetalle, Producto)
        .join(Producto, Producto.id == VentaDetalle.producto_id)
        .where(VentaDetalle.venta_id == venta.id)
        .order_by(VentaDetalle.id)
    )
    for detalle, producto in filas:
        lineas.append(
            {
                "sku": producto.sku,
                "nombre": producto.nombre,
                "cantidad": detalle.cantidad,
                "precio": detalle.precio_unitario,
                "descuento": detalle.descuento_linea,
                "total": (Decimal(detalle.cantidad) * detalle.precio_unitario - detalle.descuento_linea).quantize(CENTAVO),
            }
        )
    return {
        "id": venta.id,
        "numero": venta.numero,
        "codigo": formatear_numero(venta.numero),
        "fecha": venta.creado_en,
        "sucursal": sucursal.nombre if sucursal else "",
        "vendedor": vendedor.nombre if vendedor else "",
        "cliente": cliente.nombre if cliente else None,
        "metodo_pago": venta.metodo_pago,
        "subtotal": venta.subtotal,
        "descuento": venta.descuento,
        "total": venta.total,
        "estado": venta.estado,
        "nota": venta.nota,
        "anulada_por": anulador.nombre if anulador else None,
        "anulada_en": venta.anulada_en,
        "motivo_anulacion": venta.motivo_anulacion,
        "lineas": lineas,
    }


def listar_ventas(
    sesion: Session,
    actor: Usuario,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    vendedor_id: int | None = None,
    estado: str | None = None,
    sucursal_id: int | None = None,
    limite: int = 200,
) -> list[dict]:
    """Ventas más recientes primero. Quien solo tiene ``ver`` recibe únicamente las suyas."""
    todas = _ve_todas(sesion, actor)
    consulta = (
        select(Venta, Usuario.nombre, Cliente.nombre)
        .join(Usuario, Usuario.id == Venta.vendedor_id)
        .outerjoin(Cliente, Cliente.id == Venta.cliente_id)
        .order_by(Venta.id.desc())
        .limit(limite)
    )
    if not todas:
        consulta = consulta.where(Venta.vendedor_id == actor.id)
    elif vendedor_id is not None:
        consulta = consulta.where(Venta.vendedor_id == vendedor_id)
    if desde is not None:
        consulta = consulta.where(Venta.creado_en >= desde)
    if hasta is not None:
        consulta = consulta.where(Venta.creado_en <= hasta)
    if estado:
        consulta = consulta.where(Venta.estado == estado)
    if sucursal_id is not None:
        consulta = consulta.where(Venta.sucursal_id == sucursal_id)
    return [
        {
            "id": v.id,
            "numero": v.numero,
            "codigo": formatear_numero(v.numero),
            "fecha": v.creado_en,
            "vendedor": vendedor,
            "cliente": cliente,
            "metodo_pago": v.metodo_pago,
            "total": v.total,
            "estado": v.estado,
            "sucursal_id": v.sucursal_id,
        }
        for v, vendedor, cliente in sesion.execute(consulta)
    ]
