"""Pruebas de la Fase 5: reportes de ventas, utilidad, inventario valorizado y exportación CSV."""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modelos import BitacoraAuditoria
from app.servicios.catalogo import crear_categoria, crear_producto
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import crear_proveedor, crear_sucursal, registrar_compra
from app.servicios.reportes import (
    _celda,
    _repartir,
    exportar_detalle_ventas_csv,
    exportar_valorizado_csv,
    exportar_ventas_agrupadas_csv,
    inventario_valorizado,
    rango_local,
    resumen_ventas,
    ventas_agrupadas,
)
from app.servicios.ventas import anular_venta, registrar_venta


@pytest.fixture()
def t(sesion_servicios, administrador, crear_con_rol):
    """Tienda con ventas conocidas.

    P1 (General, precio 10, costo 4, 20 u.) y P2 (Otros, precio 5, costo 2, 50 u.).
    - Venta A (vendedor): 3×P1 + 2×P2, descuento general 4  -> total 36, costo 16
    - Venta B (administrador): 1×P1                          -> total 10, costo 4
    - Venta C (administrador): 2×P1, anulada                 -> no cuenta
    """
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    principal = crear_sucursal(s, administrador, "Principal")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    general = crear_categoria(s, administrador, "General")
    otros = crear_categoria(s, administrador, "Otros")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=general.id, precio="10", costo="4")
    p2 = crear_producto(s, administrador, sku="P2", nombre="Producto 2", categoria_id=otros.id, precio="5", costo="2")
    for producto, cantidad, costo in ((p1, 20, "4"), (p2, 50, "2")):
        registrar_compra(
            s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
            lineas=[{"producto_id": producto.id, "cantidad": cantidad, "costo_unitario": costo}],
        )

    def vender(actor, lineas, **extra):
        return registrar_venta(s, actor, sucursal_id=principal.id, lineas=lineas, metodo_pago="efectivo", **extra)

    a = vender(vendedor, [{"producto_id": p1.id, "cantidad": 3}, {"producto_id": p2.id, "cantidad": 2}], descuento="4")
    b = vender(administrador, [{"producto_id": p1.id, "cantidad": 1}])
    c = vender(administrador, [{"producto_id": p1.id, "cantidad": 2}])
    anular_venta(s, administrador, c.id, "Prueba de anulación")
    s.commit()
    return SimpleNamespace(principal=principal, p1=p1, p2=p2, vendedor=vendedor, a=a, b=b, c=c)


def por(filas):
    return {f["clave"]: f for f in filas}


# ---- resumen y utilidad --------------------------------------------------------------


def test_resumen_cuenta_solo_completadas_y_calcula_utilidad(sesion_servicios, administrador, t):
    r = resumen_ventas(sesion_servicios, administrador)
    assert r["ventas"] == 2 and r["unidades"] == 6
    assert r["ingreso"] == Decimal("46.00")
    assert r["costo"] == Decimal("20.00") and r["utilidad"] == Decimal("26.00")
    assert r["margen"] == Decimal("56.5")
    assert r["ticket_promedio"] == Decimal("23.00")
    assert r["anuladas"] == 1 and r["total_anuladas"] == Decimal("20.00")


def test_utilidad_usa_el_costo_congelado_aunque_el_costo_cambie_despues(sesion_servicios, administrador, t):
    s = sesion_servicios
    from app.servicios.catalogo import editar_producto

    editar_producto(s, administrador, t.p1.id, {"costo": "9", "precio": "50"})
    s.commit()
    assert resumen_ventas(s, administrador)["utilidad"] == Decimal("26.00")


def test_descuento_general_se_reparte_y_las_agrupaciones_cuadran_con_el_total(sesion_servicios, administrador, t):
    s = sesion_servicios
    resumen = resumen_ventas(s, administrador)
    producto = por(ventas_agrupadas(s, administrador, "producto"))
    # Venta A: líneas 30 y 10, descuento 4 -> 3 y 1. P1: 27 + 10; P2: 9.
    assert producto["P1 · Producto 1"]["ingreso"] == Decimal("37.00")
    assert producto["P2 · Producto 2"]["ingreso"] == Decimal("9.00")
    for agrupacion in ("dia", "vendedor", "producto", "categoria", "sucursal"):
        filas = ventas_agrupadas(s, administrador, agrupacion)
        assert sum(f["ingreso"] for f in filas) == resumen["ingreso"], agrupacion
        assert sum(f["utilidad"] for f in filas) == resumen["utilidad"], agrupacion


def test_el_reparto_del_descuento_nunca_pierde_centavos():
    netos = [Decimal("10.00")] * 3
    partes = _repartir(Decimal("0.10"), netos)
    assert sum(partes) == Decimal("0.10") and len(partes) == 3
    assert _repartir(Decimal("0"), netos) == [Decimal("0.00")] * 3
    assert _repartir(Decimal("5"), [Decimal("0")]) == [Decimal("0.00")]


def test_agrupar_por_vendedor_categoria_sucursal_y_dia(sesion_servicios, administrador, t):
    s = sesion_servicios
    vendedores = por(ventas_agrupadas(s, administrador, "vendedor"))
    assert vendedores["Usuario vendedor"]["ingreso"] == Decimal("36.00")
    assert vendedores["Admin"]["ingreso"] == Decimal("10.00")
    assert vendedores["Usuario vendedor"]["ventas"] == 1

    categorias = por(ventas_agrupadas(s, administrador, "categoria"))
    assert categorias["General"]["ingreso"] == Decimal("37.00") and categorias["Otros"]["ingreso"] == Decimal("9.00")
    assert categorias["General"]["unidades"] == 4 and categorias["Otros"]["unidades"] == 2

    assert [f["clave"] for f in ventas_agrupadas(s, administrador, "sucursal")] == ["Principal"]
    dias = ventas_agrupadas(s, administrador, "dia")
    assert len(dias) == 1 and dias[0]["ventas"] == 2


def test_orden_y_limite(sesion_servicios, administrador, t):
    filas = ventas_agrupadas(sesion_servicios, administrador, "producto", limite=1)
    assert [f["clave"] for f in filas] == ["P1 · Producto 1"]  # mayor ingreso primero


def test_agrupacion_invalida(sesion_servicios, administrador, t):
    with pytest.raises(ErrorDeNegocio, match="Agrupación"):
        ventas_agrupadas(sesion_servicios, administrador, "color")


def test_filtros_de_fecha_vendedor_y_sucursal(sesion_servicios, administrador, t):
    s = sesion_servicios
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    assert resumen_ventas(s, administrador, desde=ahora + timedelta(days=1))["ventas"] == 0
    assert resumen_ventas(s, administrador, hasta=ahora - timedelta(days=1))["ventas"] == 0
    assert resumen_ventas(s, administrador, desde=ahora - timedelta(days=1), hasta=ahora + timedelta(days=1))["ventas"] == 2
    assert resumen_ventas(s, administrador, vendedor_id=t.vendedor.id)["ingreso"] == Decimal("36.00")
    assert resumen_ventas(s, administrador, sucursal_id=t.principal.id)["ventas"] == 2
    assert resumen_ventas(s, administrador, sucursal_id=9999)["ventas"] == 0


def test_periodo_vacio_no_divide_por_cero(sesion_servicios, administrador, t):
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    r = resumen_ventas(sesion_servicios, administrador, desde=ahora + timedelta(days=1))
    assert r["ingreso"] == 0 and r["ticket_promedio"] == 0 and r["margen"] is None


def test_rango_local():
    assert rango_local(None, None) == (None, None)
    inicio, fin = rango_local(date(2026, 6, 10), date(2026, 6, 10))  # el día "hasta" queda incluido
    assert timedelta(hours=23) <= fin - inicio <= timedelta(hours=25)
    assert inicio.tzinfo is None and fin.tzinfo is None


# ---- permisos y alcance --------------------------------------------------------------


def test_vendedor_solo_ve_lo_suyo_y_sin_costos(sesion_servicios, administrador, t):
    s = sesion_servicios
    r = resumen_ventas(s, t.vendedor)
    assert r["ventas"] == 1 and r["ingreso"] == Decimal("36.00")
    assert r["costo"] is None and r["utilidad"] is None and r["margen"] is None
    for agrupacion in ("producto", "vendedor", "dia"):
        for fila in ventas_agrupadas(s, t.vendedor, agrupacion):
            assert fila["costo"] is None and fila["utilidad"] is None and fila["margen"] is None
    # pedir las ventas de otro vendedor no amplía el alcance
    assert resumen_ventas(s, t.vendedor, vendedor_id=administrador.id)["ingreso"] == Decimal("36.00")
    assert por(ventas_agrupadas(s, t.vendedor, "vendedor")).keys() == {"Usuario vendedor"}


def test_contador_ve_todo_con_utilidad(sesion_servicios, crear_con_rol, t):
    contador = crear_con_rol("contador")
    r = resumen_ventas(sesion_servicios, contador)
    assert r["ventas"] == 2 and r["utilidad"] == Decimal("26.00")


def test_sin_permisos_no_hay_reportes(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    bodeguero = crear_con_rol("bodeguero")  # tiene reportes.ver pero no ventas
    with pytest.raises(PermisoDenegado):
        resumen_ventas(s, bodeguero)
    s.rollback()
    with pytest.raises(PermisoDenegado):
        ventas_agrupadas(s, bodeguero, "producto")


def test_usuario_sin_reportes_ver_es_rechazado(sesion_servicios, administrador, crear_con_rol, t):
    from app.servicios.usuarios import establecer_permiso_individual

    s = sesion_servicios
    establecer_permiso_individual(s, administrador, t.vendedor.id, "reportes", "ver", False)
    s.commit()
    with pytest.raises(PermisoDenegado):
        resumen_ventas(s, t.vendedor)
    with pytest.raises(PermisoDenegado):
        inventario_valorizado(s, t.vendedor)


# ---- inventario valorizado -----------------------------------------------------------


def test_inventario_valorizado(sesion_servicios, administrador, t):
    d = inventario_valorizado(sesion_servicios, administrador)
    filas = {f["sku"]: f for f in d["filas"]}
    # P1: 20 - 3 - 1 = 16 (la venta anulada devolvió su stock) × 4; P2: 50 - 2 = 48 × 2
    assert filas["P1"]["stock"] == 16 and filas["P1"]["valor"] == Decimal("64.00")
    assert filas["P2"]["stock"] == 48 and filas["P2"]["valor"] == Decimal("96.00")
    assert d["total_unidades"] == 64 and d["total_valor"] == Decimal("160.00")
    assert [c["categoria"] for c in d["por_categoria"]] == ["Otros", "General"]  # mayor valor primero
    assert sum(c["valor"] for c in d["por_categoria"]) == d["total_valor"]


def test_valorizado_por_sucursal_y_sin_stock(sesion_servicios, administrador, t):
    s = sesion_servicios
    vacia = crear_sucursal(s, administrador, "Vacía")
    s.commit()
    d = inventario_valorizado(s, administrador, vacia.id)
    assert d["filas"] == [] and d["total_valor"] == 0 and d["por_categoria"] == []
    assert inventario_valorizado(s, administrador, t.principal.id)["total_valor"] == Decimal("160.00")


# ---- exportación ---------------------------------------------------------------------


def leer(texto):
    return list(csv.reader(io.StringIO(texto)))


def test_exportaciones_exigen_permiso_de_exportar(sesion_servicios, t):
    s = sesion_servicios
    with pytest.raises(PermisoDenegado):
        exportar_ventas_agrupadas_csv(s, t.vendedor, "producto")
    s.rollback()
    with pytest.raises(PermisoDenegado):
        exportar_detalle_ventas_csv(s, t.vendedor)
    s.rollback()
    with pytest.raises(PermisoDenegado):
        exportar_valorizado_csv(s, t.vendedor)


def test_exportar_ventas_agrupadas(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    contador = crear_con_rol("contador")
    filas = leer(exportar_ventas_agrupadas_csv(s, contador, "producto"))
    assert filas[0] == ["Producto", "Ventas", "Unidades", "Ingreso", "Costo", "Utilidad", "Margen %"]
    assert filas[1][:4] == ["P1 · Producto 1", "2", "4", "37.00"]
    assert filas[1][4:] == ["16.00", "21.00", "56.8"]
    eventos = s.scalars(select(BitacoraAuditoria.accion).where(BitacoraAuditoria.accion == "reporte_exportado")).all()
    assert len(eventos) == 1


def test_exportar_detalle_incluye_anuladas_con_quien_y_por_que(sesion_servicios, administrador, t):
    filas = leer(exportar_detalle_ventas_csv(sesion_servicios, administrador))
    assert filas[0][0] == "Venta" and len(filas) == 4  # encabezado + 3 ventas
    por_venta = {f[0]: f for f in filas[1:]}
    anulada = por_venta["V-000003"]
    assert anulada[8] == "anulada" and anulada[9] == "Admin" and anulada[10] == "Prueba de anulación"
    assert por_venta["V-000001"][3] == "Usuario vendedor" and por_venta["V-000001"][7] == "36.00"


def test_exportar_valorizado_termina_con_total(sesion_servicios, administrador, t):
    filas = leer(exportar_valorizado_csv(sesion_servicios, administrador))
    assert filas[-1] == ["", "TOTAL", "", "64", "", "160.00"]


def test_csv_no_permite_inyeccion_de_formulas():
    assert _celda("=HYPERLINK(\"http://malo\")") == "'=HYPERLINK(\"http://malo\")"
    assert _celda("+1") == "'+1" or _celda("+1") == "+1"  # un número con signo no es peligroso; ambos son aceptables
    assert _celda("@SUM(A1)") == "'@SUM(A1)"
    assert _celda("-cmd|' /C calc'!A0") == "'-cmd|' /C calc'!A0"
    assert _celda("-5.00") == "-5.00"  # un número negativo no se altera
    assert _celda("Producto") == "Producto" and _celda(7) == 7 and _celda("") == ""
