"""Pruebas de la Fase 7d: capas de costo y costeo PEPS configurable."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import create_engine, delete, inspect, select, text

from app.migraciones import _config_alembic
from app.modelos import CapaCosto, VentaDetalle
from app.servicios.catalogo import crear_categoria, crear_producto
from app.servicios.configuracion import guardar_configuracion, metodo_costeo, valores_actuales
from app.servicios.devoluciones import registrar_devolucion
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import (
    ajustar_stock,
    capas_de_producto,
    crear_proveedor,
    crear_sucursal,
    existencias,
    registrar_compra,
    registrar_merma,
    stock_actual,
    trasladar,
    verificar_capas,
)
from app.servicios.ventas import anular_venta, registrar_venta


@pytest.fixture()
def t(sesion_servicios, administrador):
    """Producto P1 sin stock, dos sucursales y un proveedor."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    norte = crear_sucursal(s, administrador, "Norte")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id, precio="10", costo="4")
    s.commit()
    return SimpleNamespace(principal=principal, norte=norte, proveedor=proveedor, p1=p1)


def comprar(s, actor, t, cantidad, costo, sucursal=None):
    registrar_compra(
        s, actor, sucursal_id=(sucursal or t.principal).id, proveedor_id=t.proveedor.id,
        lineas=[{"producto_id": t.p1.id, "cantidad": cantidad, "costo_unitario": str(costo)}],
    )
    s.commit()


def vender(s, actor, t, cantidad):
    venta = registrar_venta(
        s, actor, sucursal_id=t.principal.id,
        lineas=[{"producto_id": t.p1.id, "cantidad": cantidad}], metodo_pago="efectivo",
    )
    s.commit()
    return venta


def costo_de_venta(s, venta):
    return s.scalar(select(VentaDetalle.costo_unitario).where(VentaDetalle.venta_id == venta.id))


def restantes(s, t, sucursal=None):
    consulta = select(CapaCosto.cantidad_restante).where(CapaCosto.producto_id == t.p1.id)
    if sucursal is not None:
        consulta = consulta.where(CapaCosto.sucursal_id == sucursal.id)
    return list(s.scalars(consulta.order_by(CapaCosto.id)))


def usar_peps(s, actor):
    guardar_configuracion(s, actor, {"metodo_costeo": "peps"})
    s.commit()


# ---- esquema y configuración ---------------------------------------------------------


def test_la_migracion_crea_la_tabla(motor):
    assert "capas_costo" in set(inspect(motor).get_table_names())


def test_la_migracion_siembra_capas_con_el_stock_existente(url_bd):
    config = _config_alembic(url_bd)
    command.upgrade(config, "0009")
    motor = create_engine(url_bd)

    def insertar(conexion, tabla, **valores):
        # Rellena con valores neutros las columnas obligatorias sin valor por defecto.
        for col in conexion.execute(text(f"PRAGMA table_info({tabla})")).mappings():
            if col["name"] in valores or col["pk"] or not col["notnull"] or col["dflt_value"] is not None:
                continue
            tipo = (col["type"] or "").upper()
            valores[col["name"]] = (
                0 if ("INT" in tipo or "BOOL" in tipo) else "2026-01-01 00:00:00" if ("DATE" in tipo or "TIME" in tipo) else "x"
            )
        columnas = ", ".join(valores)
        marcas = ", ".join(f":{k}" for k in valores)
        conexion.execute(text(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})"), valores)

    with motor.begin() as c:
        insertar(c, "sucursales", id=1, nombre="Principal", activa=1)
        insertar(c, "categorias", id=1, nombre="General")
        insertar(c, "productos", id=1, sku="P1", nombre="P1", categoria_id=1, costo_promedio="6.50")
        insertar(c, "existencias", producto_id=1, sucursal_id=1, cantidad=7)
        insertar(c, "productos", id=2, sku="P2", nombre="P2", categoria_id=1, costo_promedio="3.00")
        insertar(c, "existencias", producto_id=2, sucursal_id=1, cantidad=0)
    motor.dispose()

    command.upgrade(config, "head")
    motor = create_engine(url_bd)
    with motor.connect() as c:
        filas = c.execute(
            text("SELECT producto_id, sucursal_id, cantidad_inicial, cantidad_restante, costo_unitario, origen FROM capas_costo")
        ).all()
    motor.dispose()
    assert len(filas) == 1  # el producto sin stock no genera capa
    producto, sucursal, inicial, restante, costo, origen = filas[0]
    assert (producto, sucursal, inicial, restante, origen) == (1, 1, 7, 7, "inicial")
    assert Decimal(str(costo)) == Decimal("6.50")


def test_el_metodo_por_defecto_es_promedio_y_se_puede_cambiar(sesion_servicios, administrador):
    s = sesion_servicios
    assert metodo_costeo(s) == "promedio"
    assert valores_actuales(s)["metodo_costeo"] == "promedio"
    usar_peps(s, administrador)
    assert metodo_costeo(s) == "peps"


def test_un_metodo_invalido_se_rechaza(sesion_servicios, administrador):
    with pytest.raises(ErrorDeNegocio):
        guardar_configuracion(sesion_servicios, administrador, {"metodo_costeo": "lifo"})


# ---- capas y salidas -----------------------------------------------------------------


def test_las_compras_crean_capas(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    capas = capas_de_producto(s, administrador, t.p1.id, t.principal.id)
    assert [(c["restante"], c["costo"]) for c in capas] == [(10, Decimal("4.00")), (10, Decimal("6.00"))]
    assert verificar_capas(s) == []


def test_peps_vende_primero_lo_mas_antiguo(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    usar_peps(s, administrador)

    venta = vender(s, administrador, t, 12)  # 10 a 4.00 + 2 a 6.00 = 52.00 / 12
    assert costo_de_venta(s, venta) == Decimal("4.33")
    assert restantes(s, t) == [0, 8]

    venta = vender(s, administrador, t, 5)  # solo queda la capa de 6.00
    assert costo_de_venta(s, venta) == Decimal("6.00")
    assert restantes(s, t) == [0, 3]
    assert verificar_capas(s) == []


def test_promedio_usa_el_costo_promedio(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    venta = vender(s, administrador, t, 12)
    assert costo_de_venta(s, venta) == Decimal("5.00")
    assert verificar_capas(s) == []  # las capas se mantienen aunque el método sea promedio


def test_cambiar_de_metodo_no_altera_ventas_anteriores(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    antes = vender(s, administrador, t, 5)
    usar_peps(s, administrador)
    despues = vender(s, administrador, t, 5)
    assert costo_de_venta(s, antes) == Decimal("5.00")
    assert costo_de_venta(s, despues) == Decimal("4.00")  # PEPS: 5 de las 10 a 4.00 que quedaban


def test_la_merma_consume_lo_mas_antiguo_con_peps(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    usar_peps(s, administrador)
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=4, motivo="Daño")
    s.commit()
    assert restantes(s, t) == [6, 10]
    assert verificar_capas(s) == []


def test_ajuste_positivo_crea_capa_y_negativo_consume(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    ajustar_stock(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, conteo_fisico=15, motivo="Conteo")
    s.commit()
    assert sum(restantes(s, t)) == 15
    ajustar_stock(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, conteo_fisico=12, motivo="Conteo")
    s.commit()
    assert sum(restantes(s, t)) == 12
    assert verificar_capas(s) == []


def test_el_traslado_conserva_las_capas_y_sus_costos(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    usar_peps(s, administrador)
    trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=12)
    s.commit()
    assert restantes(s, t, t.principal) == [0, 8]
    destino = capas_de_producto(s, administrador, t.p1.id, t.norte.id)
    assert [(c["restante"], c["costo"]) for c in destino] == [(10, Decimal("4.00")), (2, Decimal("6.00"))]
    assert verificar_capas(s) == []


def test_anular_una_venta_devuelve_las_unidades_al_costo_congelado(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    usar_peps(s, administrador)
    venta = vender(s, administrador, t, 12)
    anular_venta(s, administrador, venta.id, "Error de captura")
    s.commit()
    assert stock_actual(s, t.p1.id, t.principal.id) == 20
    assert sum(restantes(s, t)) == 20
    assert verificar_capas(s) == []


def test_una_devolucion_parcial_regresa_unidades_a_las_capas(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    usar_peps(s, administrador)
    venta = vender(s, administrador, t, 6)
    detalle_id = s.scalar(select(VentaDetalle.id).where(VentaDetalle.venta_id == venta.id))
    registrar_devolucion(s, administrador, venta.id, [{"detalle_id": detalle_id, "cantidad": 2}], "Defecto")
    s.commit()
    assert stock_actual(s, t.p1.id, t.principal.id) == 6
    assert sum(restantes(s, t)) == 6
    assert verificar_capas(s) == []


# ---- valoración ----------------------------------------------------------------------


def test_el_valorizado_depende_del_metodo(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    comprar(s, administrador, t, 10, 6)
    vender(s, administrador, t, 12)  # quedan 8
    fila = next(f for f in existencias(s, administrador, t.principal.id) if f["sku"] == "P1")
    assert fila["valor"] == Decimal("40.00")  # promedio 5.00 × 8
    usar_peps(s, administrador)
    fila = next(f for f in existencias(s, administrador, t.principal.id) if f["sku"] == "P1")
    # Las capas se consumen igual con ambos métodos: quedan 0 a 4.00 y 8 a 6.00.
    assert fila["valor"] == Decimal("48.00")
    assert fila["costo"] == Decimal("6.00")


def test_el_vendedor_no_ve_el_costo_de_las_capas(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    vendedor = crear_con_rol("vendedor")
    capas = capas_de_producto(s, vendedor, t.p1.id, t.principal.id)
    assert capas and all(c["costo"] is None and c["valor"] is None for c in capas)


# ---- salud y tolerancia --------------------------------------------------------------


def test_verificar_capas_detecta_diferencias(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    capa = s.scalars(select(CapaCosto)).first()
    capa.cantidad_restante = 7
    s.commit()
    diferencias = verificar_capas(s)
    assert diferencias == [
        {"producto_id": t.p1.id, "sucursal_id": t.principal.id, "en_capas": 7, "existencia": 10}
    ]


def test_sin_capas_la_venta_no_se_bloquea_y_se_reporta(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, 10, 4)
    usar_peps(s, administrador)
    s.execute(delete(CapaCosto))
    s.commit()
    venta = vender(s, administrador, t, 3)
    assert costo_de_venta(s, venta) == Decimal("4.00")  # cae al costo promedio del producto
    assert stock_actual(s, t.p1.id, t.principal.id) == 7
    assert verificar_capas(s) != []
