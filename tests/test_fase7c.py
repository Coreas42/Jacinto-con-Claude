"""Pruebas de la Fase 7c: pagos mixtos y devoluciones parciales."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select

from app.modelos import BitacoraAuditoria, Devolucion, MovimientoInventario, PagoVenta, Venta
from app.servicios.catalogo import crear_categoria, crear_producto
from app.servicios.comprobante import comprobante_html, comprobante_texto
from app.servicios.devoluciones import previsualizar_devolucion, registrar_devolucion
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import (
    crear_proveedor,
    crear_sucursal,
    registrar_compra,
    stock_actual,
    verificar_consistencia,
)
from app.servicios.permisos import MATRIZ_BASE
from app.servicios.reportes import resumen_ventas
from app.servicios.ventas import anular_venta, obtener_venta, registrar_venta


@pytest.fixture()
def t(sesion_servicios, administrador):
    """P1 (precio 10, costo 4, 20 u.), P2 (precio 20, costo 8, 20 u.) y S1 servicio (precio 40, costo 15)."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id, precio="10", costo="4")
    p2 = crear_producto(s, administrador, sku="P2", nombre="Producto 2", categoria_id=categoria.id, precio="20", costo="8")
    s1 = crear_producto(
        s, administrador, sku="S1", nombre="Polarizado", categoria_id=categoria.id, precio="40", costo="15", es_servicio=True
    )
    registrar_compra(
        s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
        lineas=[
            {"producto_id": p1.id, "cantidad": 20, "costo_unitario": "4"},
            {"producto_id": p2.id, "cantidad": 20, "costo_unitario": "8"},
        ],
    )
    s.commit()
    return SimpleNamespace(principal=principal, p1=p1, p2=p2, s1=s1)


def vender(s, actor, t, lineas, **extra):
    if "pagos" not in extra:
        extra.setdefault("metodo_pago", "efectivo")
    return registrar_venta(s, actor, sucursal_id=t.principal.id, lineas=lineas, **extra)


def stock(s, t, producto):
    return stock_actual(s, producto.id, t.principal.id)


def detalle_de(s, actor, venta, sku):
    datos = obtener_venta(s, actor, venta.id)
    return next(l for l in datos["lineas"] if l["sku"] == sku)


# ---- esquema y permisos --------------------------------------------------------------


def test_la_migracion_crea_las_tablas(motor):
    tablas = set(inspect(motor).get_table_names())
    assert {"ventas_pagos", "devoluciones", "devoluciones_detalle"} <= tablas


def test_solo_el_administrador_puede_devolver_por_defecto():
    assert "devolver" in MATRIZ_BASE["administrador"]["ventas"]
    for rol in ("vendedor", "contador", "bodeguero"):
        assert "devolver" not in MATRIZ_BASE[rol].get("ventas", [])


# ---- pagos mixtos --------------------------------------------------------------------


def test_pago_unico_deja_una_fila_de_pago(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}], metodo_pago="tarjeta")
    s.commit()
    datos = obtener_venta(s, administrador, venta.id)
    assert venta.metodo_pago == "tarjeta"
    assert [(p["metodo"], p["monto"]) for p in datos["pagos"]] == [("tarjeta", Decimal("20.00"))]
    assert s.scalar(select(func.count()).select_from(PagoVenta)) == 1


def test_pago_mixto_suma_exacta(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(
        s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}, {"producto_id": t.p2.id, "cantidad": 1}],
        pagos=[{"metodo": "efectivo", "monto": "10"}, {"metodo": "tarjeta", "monto": "20"}],
    )
    s.commit()
    assert venta.metodo_pago == "mixto" and venta.total == Decimal("30.00")
    datos = obtener_venta(s, administrador, venta.id)
    assert [(p["metodo"], p["monto"]) for p in datos["pagos"]] == [
        ("efectivo", Decimal("10.00")), ("tarjeta", Decimal("20.00"))
    ]


def test_efectivo_recibido_calcula_el_cambio(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(
        s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}],
        pagos=[{"metodo": "efectivo", "monto": "20", "recibido": "50"}],
    )
    s.commit()
    pago = obtener_venta(s, administrador, venta.id)["pagos"][0]
    assert pago["recibido"] == Decimal("50.00") and pago["cambio"] == Decimal("30.00")
    assert "Cambio" in comprobante_texto(obtener_venta(s, administrador, venta.id), "Tienda")
    assert "cambio 30.00" in comprobante_html(obtener_venta(s, administrador, venta.id), "Tienda")


@pytest.mark.parametrize(
    "pagos, mensaje",
    [
        ([{"metodo": "efectivo", "monto": "10"}, {"metodo": "tarjeta", "monto": "10"}], "suman 20.00"),
        ([{"metodo": "efectivo", "monto": "10"}, {"metodo": "efectivo", "monto": "20"}], "repetida"),
        ([{"metodo": "cheque", "monto": "30"}], "no válido"),
        ([], "al menos una forma de pago"),
        ([{"metodo": "efectivo", "monto": "0"}, {"metodo": "tarjeta", "monto": "30"}], "mayor que cero"),
        ([{"metodo": "tarjeta", "monto": "30", "recibido": "40"}], "Solo el efectivo"),
        ([{"metodo": "efectivo", "monto": "30", "recibido": "20"}], "menor que el monto"),
    ],
)
def test_pagos_invalidos_se_rechazan_sin_tocar_el_stock(sesion_servicios, administrador, t, pagos, mensaje):
    s = sesion_servicios
    antes = stock(s, t, t.p1)
    with pytest.raises(ErrorDeNegocio, match=mensaje):
        vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}, {"producto_id": t.p2.id, "cantidad": 1}], pagos=pagos)
    s.rollback()
    assert stock(s, t, t.p1) == antes
    assert s.scalar(select(func.count()).select_from(Venta)) == 0


def test_pago_mixto_con_descuento_usa_el_total_final(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(
        s, administrador, t, [{"producto_id": t.p2.id, "cantidad": 1}], descuento="5",
        pagos=[{"metodo": "efectivo", "monto": "5"}, {"metodo": "transferencia", "monto": "10"}],
    )
    assert venta.total == Decimal("15.00")


# ---- devoluciones --------------------------------------------------------------------


def test_devolucion_parcial_regresa_stock_y_reembolsa_proporcional(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 4}], descuento="4")  # cobrado 36
    s.commit()
    assert stock(s, t, t.p1) == 16
    linea = detalle_de(s, administrador, venta, "P1")

    previa = previsualizar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}])
    assert previa["total"] == Decimal("9.00")
    assert stock(s, t, t.p1) == 16  # la vista previa no guarda nada

    resultado = registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "Salió defectuoso")
    s.commit()
    assert resultado["total"] == Decimal("9.00") and resultado["codigo"].startswith("D-")
    assert stock(s, t, t.p1) == 17

    datos = obtener_venta(s, administrador, venta.id)
    assert datos["total_devuelto"] == Decimal("9.00")
    assert datos["lineas"][0]["devuelta"] == 1 and datos["lineas"][0]["disponible"] == 3
    assert datos["devoluciones"][0]["motivo"] == "Salió defectuoso"
    assert datos["estado"] == "completada"

    mov = s.scalars(select(MovimientoInventario).where(MovimientoInventario.tipo == "devolucion")).one()
    assert mov.cantidad == 1 and mov.costo_unitario == Decimal("4.00") and mov.referencia_tipo == "devolucion"
    assert verificar_consistencia(s) == []


def test_devolver_todo_reembolsa_exactamente_lo_cobrado_sin_perder_centavos(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 3}], descuento="20")  # cobrado 10.00
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    montos = []
    for _ in range(3):
        r = registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "Cambio de opinión")
        montos.append(r["total"])
    s.commit()
    assert montos == [Decimal("3.33"), Decimal("3.34"), Decimal("3.33")]
    assert sum(montos) == Decimal("10.00") == obtener_venta(s, administrador, venta.id)["total_devuelto"]
    assert stock(s, t, t.p1) == 20


def test_no_se_puede_devolver_mas_de_lo_vendido(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}])
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "x")
    with pytest.raises(ErrorDeNegocio, match="solo se pueden devolver 1"):
        registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 2}], "x")
    # pedir la misma línea dos veces en una sola devolución también suma
    with pytest.raises(ErrorDeNegocio, match="solo se pueden devolver 1"):
        registrar_devolucion(
            s, administrador, venta.id,
            [{"detalle_id": linea["detalle_id"], "cantidad": 1}, {"detalle_id": linea["detalle_id"], "cantidad": 1}], "x",
        )


def test_una_linea_de_otra_venta_se_rechaza(sesion_servicios, administrador, t):
    s = sesion_servicios
    a = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    b = vender(s, administrador, t, [{"producto_id": t.p2.id, "cantidad": 1}])
    s.commit()
    linea_b = detalle_de(s, administrador, b, "P2")
    with pytest.raises(ErrorDeNegocio, match="no pertenece"):
        registrar_devolucion(s, administrador, a.id, [{"detalle_id": linea_b["detalle_id"], "cantidad": 1}], "x")


def test_validaciones_basicas(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}])
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    una = [{"detalle_id": linea["detalle_id"], "cantidad": 1}]
    with pytest.raises(ErrorDeNegocio, match="motivo"):
        registrar_devolucion(s, administrador, venta.id, una, "  ")
    with pytest.raises(ErrorDeNegocio, match="no válida"):
        registrar_devolucion(s, administrador, venta.id, una, "x", metodo_reembolso="cheque")
    with pytest.raises(ErrorDeNegocio, match="qué productos"):
        registrar_devolucion(s, administrador, venta.id, [], "x")
    with pytest.raises(ErrorDeNegocio):
        registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 0}], "x")
    with pytest.raises(ErrorDeNegocio, match="no existe"):
        registrar_devolucion(s, administrador, 9999, una, "x")
    assert s.scalar(select(func.count()).select_from(Devolucion)) == 0


def test_una_devolucion_invalida_no_deja_nada_a_medias(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}, {"producto_id": t.p2.id, "cantidad": 1}])
    s.commit()
    l1 = detalle_de(s, administrador, venta, "P1")
    l2 = detalle_de(s, administrador, venta, "P2")
    with pytest.raises(ErrorDeNegocio):
        registrar_devolucion(
            s, administrador, venta.id,
            [{"detalle_id": l1["detalle_id"], "cantidad": 1}, {"detalle_id": l2["detalle_id"], "cantidad": 5}], "x",
        )
    s.rollback()
    assert s.scalar(select(func.count()).select_from(Devolucion)) == 0
    assert stock(s, t, t.p1) == 18


def test_servicios_se_devuelven_sin_mover_stock(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.s1.id, "cantidad": 1}])
    s.commit()
    movimientos_antes = s.scalar(select(func.count()).select_from(MovimientoInventario))
    linea = detalle_de(s, administrador, venta, "S1")
    r = registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "No quedó bien")
    s.commit()
    assert r["total"] == Decimal("40.00")
    assert s.scalar(select(func.count()).select_from(MovimientoInventario)) == movimientos_antes


def test_venta_anulada_no_admite_devoluciones_y_venta_con_devoluciones_no_se_anula(sesion_servicios, administrador, t):
    s = sesion_servicios
    anulada = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    parcial = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}])
    s.commit()
    linea_a = detalle_de(s, administrador, anulada, "P1")
    linea_p = detalle_de(s, administrador, parcial, "P1")
    anular_venta(s, administrador, anulada.id, "Error")
    with pytest.raises(ErrorDeNegocio, match="anulada"):
        registrar_devolucion(s, administrador, anulada.id, [{"detalle_id": linea_a["detalle_id"], "cantidad": 1}], "x")
    registrar_devolucion(s, administrador, parcial.id, [{"detalle_id": linea_p["detalle_id"], "cantidad": 1}], "x")
    with pytest.raises(ErrorDeNegocio, match="ya tiene devoluciones"):
        anular_venta(s, administrador, parcial.id, "Error")


def test_permisos_de_devolucion(sesion_servicios, administrador, t, crear_con_rol):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    for rol in ("vendedor", "contador", "bodeguero"):
        usuario = crear_con_rol(rol)
        with pytest.raises(PermisoDenegado):
            registrar_devolucion(s, usuario, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "x")
        with pytest.raises(PermisoDenegado):
            previsualizar_devolucion(s, usuario, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}])


def test_la_devolucion_queda_en_la_bitacora(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "Defecto")
    s.commit()
    evento = s.scalars(select(BitacoraAuditoria).where(BitacoraAuditoria.accion == "devolucion_registrada")).one()
    assert evento.usuario_id == administrador.id and evento.detalle["motivo"] == "Defecto"


# ---- reportes y comprobante ------------------------------------------------------------


def test_los_reportes_restan_las_devoluciones(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 4}])  # 40, costo 16
    s.commit()
    antes = resumen_ventas(s, administrador)
    assert antes["ingreso"] == Decimal("40.00") and antes["unidades"] == 4 and antes["utilidad"] == Decimal("24.00")

    linea = detalle_de(s, administrador, venta, "P1")
    registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "x")
    s.commit()
    despues = resumen_ventas(s, administrador)
    assert despues["ingreso"] == Decimal("30.00")
    assert despues["unidades"] == 3
    assert despues["costo"] == Decimal("12.00")
    assert despues["utilidad"] == Decimal("18.00")
    assert despues["ventas"] == 1  # la devolución no cuenta como otra venta


def test_comprobante_muestra_pagos_y_devoluciones(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(
        s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}],
        pagos=[{"metodo": "efectivo", "monto": "5"}, {"metodo": "tarjeta", "monto": "15"}],
    )
    s.commit()
    linea = detalle_de(s, administrador, venta, "P1")
    registrar_devolucion(s, administrador, venta.id, [{"detalle_id": linea["detalle_id"], "cantidad": 1}], "Defecto", "tarjeta")
    s.commit()
    datos = obtener_venta(s, administrador, venta.id)
    texto = comprobante_texto(datos, "Tienda")
    assert "Pagos:" in texto and "Efectivo" in texto and "Tarjeta" in texto
    assert "DEVOLUCIONES" in texto and "Defecto" in texto and "NETO" in texto
    html = comprobante_html(datos, "Tienda")
    assert "Devoluciones" in html and "Defecto" in html
