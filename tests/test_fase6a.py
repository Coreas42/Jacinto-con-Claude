"""Pruebas de servicios: productos que se venden sin controlar existencias."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select

from app.modelos import MovimientoInventario, Venta, VentaDetalle
from app.servicios.catalogo import buscar_productos, crear_categoria, crear_producto, editar_producto
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import (
    aplicar_movimiento,
    alertas_stock_bajo,
    crear_proveedor,
    crear_sucursal,
    existencias,
    registrar_compra,
    verificar_consistencia,
)
from app.servicios.reportes import inventario_valorizado, resumen_ventas, ventas_agrupadas
from app.servicios.ventas import anular_venta, buscar_para_venta, producto_para_venta, registrar_venta


@pytest.fixture()
def t(sesion_servicios, administrador):
    """P1: producto con 10 u. (precio 10, costo 4). S1: servicio «Polarizado» (precio 40, costo 15)."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id, precio="10", costo="4", stock_minimo=50)
    s1 = crear_producto(
        s, administrador, sku="S1", nombre="Polarizado", categoria_id=categoria.id, precio="40", costo="15",
        stock_minimo=5, es_servicio=True,
    )
    registrar_compra(
        s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
        lineas=[{"producto_id": p1.id, "cantidad": 10, "costo_unitario": "4"}],
    )
    s.commit()
    return SimpleNamespace(principal=principal, proveedor=proveedor, p1=p1, s1=s1)


def vender(s, actor, t, lineas):
    return registrar_venta(s, actor, sucursal_id=t.principal.id, lineas=lineas, metodo_pago="efectivo")


def movimientos(s, producto_id):
    return s.scalar(select(func.count()).select_from(MovimientoInventario).where(MovimientoInventario.producto_id == producto_id))


def test_la_migracion_agrega_la_columna(motor):
    columnas = {c["name"]: c for c in inspect(motor).get_columns("productos")}
    assert "es_servicio" in columnas


def test_crear_servicio_ignora_el_stock_minimo(sesion_servicios, administrador, t):
    assert t.s1.es_servicio is True and t.s1.stock_minimo == 0
    assert t.p1.es_servicio is False and t.p1.stock_minimo == 50
    por_sku = {p["sku"]: p for p in buscar_productos(sesion_servicios, administrador, "")}
    assert por_sku["S1"]["es_servicio"] is True and por_sku["P1"]["es_servicio"] is False


def test_editar_servicio(sesion_servicios, administrador, t):
    s = sesion_servicios
    assert editar_producto(s, administrador, t.s1.id, {"precio": "45", "costo": "18"}) == ["costo", "precio"]
    assert editar_producto(s, administrador, t.s1.id, {"stock_minimo": "0"}) == []
    with pytest.raises(ErrorDeNegocio, match="servicio"):
        editar_producto(s, administrador, t.s1.id, {"stock_minimo": "3"})
    with pytest.raises(ErrorDeNegocio, match="No se puede editar"):
        editar_producto(s, administrador, t.p1.id, {"es_servicio": True})  # el tipo no cambia después


def test_los_servicios_no_aparecen_en_inventario_alertas_ni_valorizado(sesion_servicios, administrador, t):
    s = sesion_servicios
    assert [f["sku"] for f in existencias(s, administrador)] == ["P1"]
    assert [f["sku"] for f in alertas_stock_bajo(s, administrador)] == ["P1"]  # 10 <= 50
    assert [f["sku"] for f in inventario_valorizado(s, administrador)["filas"]] == ["P1"]


def test_un_servicio_no_admite_movimientos_de_inventario(sesion_servicios, administrador, t):
    s = sesion_servicios
    with pytest.raises(ErrorDeNegocio, match="servicio"):
        aplicar_movimiento(
            s, usuario_id=administrador.id, producto_id=t.s1.id, sucursal_id=t.principal.id, tipo="entrada", cantidad=5,
        )
    with pytest.raises(ErrorDeNegocio, match="servicio"):
        registrar_compra(
            s, administrador, sucursal_id=t.principal.id, proveedor_id=t.proveedor.id,
            lineas=[{"producto_id": t.s1.id, "cantidad": 1, "costo_unitario": "1"}],
        )
    s.rollback()
    assert movimientos(s, t.s1.id) == 0


def test_venta_mixta_descuenta_solo_el_producto_y_congela_el_costo_del_servicio(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}, {"producto_id": t.s1.id, "cantidad": 2}])
    s.commit()
    assert venta.total == Decimal("90.00")
    assert existencias(s, administrador)[0]["stock"] == 9
    assert movimientos(s, t.s1.id) == 0
    detalle = s.scalars(select(VentaDetalle).where(VentaDetalle.producto_id == t.s1.id)).one()
    assert (detalle.cantidad, detalle.precio_unitario, detalle.costo_unitario) == (2, Decimal("40.00"), Decimal("15.00"))
    r = resumen_ventas(s, administrador)
    assert (r["ingreso"], r["costo"], r["utilidad"]) == (Decimal("90.00"), Decimal("34.00"), Decimal("56.00"))
    assert "S1 · Polarizado" in [f["clave"] for f in ventas_agrupadas(s, administrador, "producto")]
    assert verificar_consistencia(s) == []


def test_se_pueden_vender_muchos_servicios_sin_existencias(sesion_servicios, administrador, t):
    s = sesion_servicios
    vender(s, administrador, t, [{"producto_id": t.s1.id, "cantidad": 50}])
    s.commit()
    assert s.scalar(select(func.count()).select_from(Venta)) == 1
    assert verificar_consistencia(s) == []


def test_si_falla_el_producto_no_queda_ni_el_servicio(sesion_servicios, administrador, t):
    s = sesion_servicios
    with pytest.raises(ErrorDeNegocio, match="P1"):
        vender(s, administrador, t, [{"producto_id": t.s1.id, "cantidad": 1}, {"producto_id": t.p1.id, "cantidad": 99}])
    s.rollback()
    assert s.scalar(select(func.count()).select_from(Venta)) == 0
    assert s.scalar(select(func.count()).select_from(VentaDetalle)) == 0


def test_anular_venta_mixta_devuelve_solo_el_producto(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 3}, {"producto_id": t.s1.id, "cantidad": 1}])
    s.commit()
    anular_venta(s, administrador, venta.id, "Cliente canceló")
    s.commit()
    assert venta.estado == "anulada"
    assert existencias(s, administrador)[0]["stock"] == 10
    assert movimientos(s, t.s1.id) == 0
    assert verificar_consistencia(s) == []


def test_la_caja_ve_el_servicio_sin_stock(sesion_servicios, administrador, t):
    s = sesion_servicios
    servicio = producto_para_venta(s, administrador, "s1", t.principal.id)
    assert servicio["es_servicio"] is True and servicio["stock"] is None and servicio["precio"] == Decimal("40.00")
    producto = producto_para_venta(s, administrador, "P1", t.principal.id)
    assert producto["es_servicio"] is False and producto["stock"] == 10
    encontrados = {p["sku"]: p for p in buscar_para_venta(s, administrador, "o", t.principal.id)}
    assert encontrados["S1"]["stock"] is None and encontrados["P1"]["stock"] == 10
