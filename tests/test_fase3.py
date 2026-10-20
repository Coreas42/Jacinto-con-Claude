"""Pruebas de la Fase 3: inventario, kardex, costo promedio, traslados y alertas."""

import csv
import io
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from app.modelos import (
    BitacoraAuditoria,
    Compra,
    Existencia,
    MovimientoInventario,
    Sucursal,
    Traslado,
    Usuario,
)
from app.servicios.catalogo import (
    crear_categoria,
    crear_producto,
    establecer_activo,
    historial_producto,
)
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import (
    aplicar_movimiento,
    ajustar_stock,
    alertas_stock_bajo,
    costo_promedio_ponderado,
    crear_proveedor,
    crear_sucursal,
    establecer_proveedor_activo,
    existencias,
    exportar_existencias_csv,
    exportar_kardex_csv,
    kardex,
    listar_proveedores,
    listar_sucursales,
    registrar_compra,
    registrar_merma,
    stock_actual,
    trasladar,
    verificar_consistencia,
)
from seed import STOCK_INICIAL_EJEMPLO, sembrar


@pytest.fixture()
def t(sesion_servicios, administrador):
    """Tienda de prueba: 2 sucursales, 1 proveedor y 2 productos (P1 con mínimo 10, P2 sin mínimo)."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    norte = crear_sucursal(s, administrador, "Norte")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(
        s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id,
        precio="2", costo="1", stock_minimo=10, codigo_barras="111",
    )
    p2 = crear_producto(
        s, administrador, sku="P2", nombre="Producto 2", categoria_id=categoria.id, precio="5", costo="3",
    )
    s.commit()
    return SimpleNamespace(principal=principal, norte=norte, proveedor=proveedor, p1=p1, p2=p2)


def comprar(s, actor, t, producto, cantidad, costo, sucursal=None):
    return registrar_compra(
        s, actor, sucursal_id=(sucursal or t.principal).id, proveedor_id=t.proveedor.id,
        lineas=[{"producto_id": producto.id, "cantidad": cantidad, "costo_unitario": costo}],
    )


def contar(s, modelo):
    return s.scalar(select(func.count()).select_from(modelo))


# ---- esquema -----------------------------------------------------------------------


def test_migracion_crea_tablas_de_inventario(motor):
    assert {
        "proveedores", "existencias", "movimientos_inventario", "compras", "compras_detalle", "traslados",
    } <= set(inspect(motor).get_table_names())


def test_la_base_rechaza_existencias_negativas(sesion_servicios, t):
    with pytest.raises(IntegrityError):
        sesion_servicios.execute(
            text("INSERT INTO existencias (producto_id, sucursal_id, cantidad) VALUES (:p, :s, -1)"),
            {"p": t.p1.id, "s": t.principal.id},
        )
    sesion_servicios.rollback()


# ---- compras y costo promedio ponderado --------------------------------------------


def test_compra_ingresa_stock_y_registra_el_kardex(sesion_servicios, administrador, t):
    s = sesion_servicios
    compra = registrar_compra(
        s, administrador, sucursal_id=t.principal.id, proveedor_id=t.proveedor.id, nota="F-001",
        lineas=[{"producto_id": t.p1.id, "cantidad": "10", "costo_unitario": "1,25"}],
    )
    assert compra.total == Decimal("12.50")
    assert stock_actual(s, t.p1.id, t.principal.id) == 10
    assert stock_actual(s, t.p1.id, t.norte.id) == 0
    movimiento = kardex(s, administrador, t.p1.id)[0]
    assert (movimiento["tipo"], movimiento["cantidad"], movimiento["saldo"]) == ("entrada", 10, 10)
    assert movimiento["costo"] == Decimal("1.25")
    assert movimiento["referencia"] == f"compra #{compra.id}"
    assert movimiento["usuario"] == administrador.nombre
    assert t.p1.costo_promedio == Decimal("1.25")  # sin stock previo, el costo es el de la compra


def test_costo_promedio_ponderado_en_compras_sucesivas(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1.00")
    assert t.p1.costo_promedio == Decimal("1.00")
    comprar(s, administrador, t, t.p1, 10, "2.00")
    assert t.p1.costo_promedio == Decimal("1.50")
    comprar(s, administrador, t, t.p1, 20, "3.00")
    assert t.p1.costo_promedio == Decimal("2.25")

    cambios = [h for h in historial_producto(s, administrador, t.p1.id) if h["campo"] == "costo"]
    assert (cambios[0]["anterior"], cambios[0]["nuevo"]) == ("1.50", "2.25")
    assert cambios[0]["usuario"] == administrador.nombre


def test_el_promedio_usa_el_stock_de_todas_las_sucursales(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1.00", sucursal=t.principal)
    comprar(s, administrador, t, t.p1, 10, "2.00", sucursal=t.norte)
    assert t.p1.costo_promedio == Decimal("1.50")


def test_formula_del_promedio_y_redondeo():
    assert costo_promedio_ponderado(0, Decimal("5"), 10, Decimal("2")) == Decimal("2")
    assert costo_promedio_ponderado(10, Decimal("1.00"), 10, Decimal("2.00")) == Decimal("1.50")
    assert costo_promedio_ponderado(3, Decimal("1.00"), 1, Decimal("1.50")) == Decimal("1.13")  # 1.125


def test_una_compra_con_varias_lineas_del_mismo_producto(sesion_servicios, administrador, t):
    registrar_compra(
        sesion_servicios, administrador, sucursal_id=t.principal.id, proveedor_id=t.proveedor.id,
        lineas=[
            {"producto_id": t.p1.id, "cantidad": 10, "costo_unitario": "1"},
            {"producto_id": t.p1.id, "cantidad": 10, "costo_unitario": "3"},
        ],
    )
    assert stock_actual(sesion_servicios, t.p1.id) == 20
    assert t.p1.costo_promedio == Decimal("2.00")


def test_compra_invalida_no_deja_nada_a_medias(sesion_servicios, administrador, t):
    s = sesion_servicios
    base = dict(sucursal_id=t.principal.id, proveedor_id=t.proveedor.id)
    buena = {"producto_id": t.p1.id, "cantidad": 5, "costo_unitario": "1"}
    invalidas = [
        [],
        [buena, {"producto_id": t.p2.id, "cantidad": 0, "costo_unitario": "1"}],
        [buena, {"producto_id": t.p2.id, "cantidad": "x", "costo_unitario": "1"}],
        [buena, {"producto_id": t.p2.id, "cantidad": 1, "costo_unitario": "-1"}],
        [buena, {"producto_id": 9999, "cantidad": 1, "costo_unitario": "1"}],
        [buena, {"cantidad": 1, "costo_unitario": "1"}],
    ]
    for lineas in invalidas:
        with pytest.raises(ErrorDeNegocio):
            registrar_compra(s, administrador, lineas=lineas, **base)
    assert contar(s, Compra) == 0
    assert contar(s, MovimientoInventario) == 0
    assert stock_actual(s, t.p1.id) == 0


def test_compra_rechaza_proveedor_sucursal_o_producto_inactivos(sesion_servicios, administrador, t):
    s = sesion_servicios
    linea = [{"producto_id": t.p1.id, "cantidad": 1, "costo_unitario": "1"}]

    establecer_proveedor_activo(s, administrador, t.proveedor.id, False)
    with pytest.raises(ErrorDeNegocio):
        registrar_compra(s, administrador, sucursal_id=t.principal.id, proveedor_id=t.proveedor.id, lineas=linea)
    establecer_proveedor_activo(s, administrador, t.proveedor.id, True)

    t.norte.activa = False
    s.flush()
    with pytest.raises(ErrorDeNegocio):
        registrar_compra(s, administrador, sucursal_id=t.norte.id, proveedor_id=t.proveedor.id, lineas=linea)

    establecer_activo(s, administrador, t.p1.id, False)
    with pytest.raises(ErrorDeNegocio):
        registrar_compra(s, administrador, sucursal_id=t.principal.id, proveedor_id=t.proveedor.id, lineas=linea)
    assert contar(s, Compra) == 0


# ---- núcleo: stock nunca negativo --------------------------------------------------


def test_no_se_puede_dejar_stock_negativo(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 5, "1")
    movimientos = contar(s, MovimientoInventario)
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        aplicar_movimiento(
            s, usuario_id=administrador.id, producto_id=t.p1.id, sucursal_id=t.principal.id,
            tipo="salida", cantidad=6,
        )
    assert stock_actual(s, t.p1.id, t.principal.id) == 5
    assert contar(s, MovimientoInventario) == movimientos  # tampoco quedó un movimiento huérfano


def test_sacar_de_una_sucursal_sin_existencia_falla(sesion_servicios, administrador, t):
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        aplicar_movimiento(
            sesion_servicios, usuario_id=administrador.id, producto_id=t.p1.id,
            sucursal_id=t.norte.id, tipo="salida", cantidad=1,
        )
    assert contar(sesion_servicios, Existencia) == 0


def test_la_ultima_unidad_solo_se_puede_sacar_una_vez(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 1, "1")
    salir = lambda: aplicar_movimiento(  # noqa: E731
        s, usuario_id=administrador.id, producto_id=t.p1.id, sucursal_id=t.principal.id, tipo="salida", cantidad=1
    )
    salir()
    with pytest.raises(ErrorDeNegocio):
        salir()
    assert stock_actual(s, t.p1.id) == 0


def test_validaciones_de_aplicar_movimiento(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 5, "1")
    base = dict(usuario_id=administrador.id, producto_id=t.p1.id, sucursal_id=t.principal.id)
    for cambio in (
        {"tipo": "inventado", "cantidad": 1},
        {"tipo": "entrada", "cantidad": 0},
        {"tipo": "entrada", "cantidad": 1.5},
        {"tipo": "entrada", "cantidad": "2"},
        {"tipo": "entrada", "cantidad": True},
        {"tipo": "salida", "cantidad": -1},
        {"tipo": "entrada", "cantidad": 1, "producto_id": 9999},
        {"tipo": "entrada", "cantidad": 1, "sucursal_id": 9999},
    ):
        with pytest.raises(ErrorDeNegocio):
            aplicar_movimiento(s, **{**base, **cambio})
    assert stock_actual(s, t.p1.id) == 5


def test_los_tipos_de_entrada_y_salida_respetan_su_sentido(sesion_servicios, administrador, t):
    s = sesion_servicios
    base = dict(usuario_id=administrador.id, producto_id=t.p1.id, sucursal_id=t.principal.id)
    aplicar_movimiento(s, tipo="entrada", cantidad=10, **base)
    aplicar_movimiento(s, tipo="devolucion", cantidad=2, **base)
    aplicar_movimiento(s, tipo="anulacion", cantidad=1, **base)
    aplicar_movimiento(s, tipo="salida", cantidad=3, **base)
    aplicar_movimiento(s, tipo="merma", cantidad=1, **base)
    aplicar_movimiento(s, tipo="ajuste", cantidad=-2, **base)
    aplicar_movimiento(s, tipo="ajuste", cantidad=4, **base)
    assert stock_actual(s, t.p1.id) == 10 + 2 + 1 - 3 - 1 - 2 + 4
    assert verificar_consistencia(s) == []


# ---- merma y ajuste ------------------------------------------------------------------


def test_merma_baja_el_stock_y_exige_motivo(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad="3", motivo="Se venció")
    assert stock_actual(s, t.p1.id) == 7
    ultimo = kardex(s, administrador, t.p1.id)[-1]
    assert (ultimo["tipo"], ultimo["cantidad"], ultimo["saldo"], ultimo["motivo"]) == ("merma", -3, 7, "Se venció")

    for motivo in ("", "   ", None):
        with pytest.raises(ErrorDeNegocio):
            registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=1, motivo=motivo)
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=8, motivo="x")
    with pytest.raises(ErrorDeNegocio):
        registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=0, motivo="x")
    assert stock_actual(s, t.p1.id) == 7


def test_ajuste_deja_el_stock_igual_al_conteo_fisico(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    datos = dict(producto_id=t.p1.id, sucursal_id=t.principal.id)

    bajada = ajustar_stock(s, administrador, conteo_fisico="8", motivo="Conteo de fin de mes", **datos)
    assert (bajada.tipo, bajada.cantidad, bajada.saldo_despues) == ("ajuste", -2, 8)
    subida = ajustar_stock(s, administrador, conteo_fisico=12, motivo="Apareció mercadería", **datos)
    assert (subida.cantidad, subida.saldo_despues) == (4, 12)
    assert ajustar_stock(s, administrador, conteo_fisico=12, motivo="Sin diferencia", **datos) is None
    assert ajustar_stock(s, administrador, conteo_fisico=0, motivo="Se perdió todo", **datos).saldo_despues == 0

    with pytest.raises(ErrorDeNegocio):
        ajustar_stock(s, administrador, conteo_fisico=5, motivo="", **datos)
    with pytest.raises(ErrorDeNegocio):
        ajustar_stock(s, administrador, conteo_fisico=-1, motivo="x", **datos)
    with pytest.raises(ErrorDeNegocio):
        ajustar_stock(s, administrador, conteo_fisico="abc", motivo="x", **datos)
    assert verificar_consistencia(s) == []


def test_ajuste_en_una_sucursal_sin_existencia_crea_la_fila(sesion_servicios, administrador, t):
    ajustar_stock(sesion_servicios, administrador, producto_id=t.p1.id, sucursal_id=t.norte.id, conteo_fisico=7, motivo="Alta inicial")
    assert stock_actual(sesion_servicios, t.p1.id, t.norte.id) == 7


# ---- traslados -----------------------------------------------------------------------


def test_traslado_mueve_stock_y_deja_dos_movimientos(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "2")
    costo = t.p1.costo_promedio
    traslado = trasladar(
        s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad="4", nota="Reposición"
    )
    assert stock_actual(s, t.p1.id, t.principal.id) == 6
    assert stock_actual(s, t.p1.id, t.norte.id) == 4
    assert stock_actual(s, t.p1.id) == 10
    assert t.p1.costo_promedio == costo  # un traslado no cambia el costo

    del_traslado = [m for m in kardex(s, administrador, t.p1.id) if m["referencia"] == f"traslado #{traslado.id}"]
    assert [(m["tipo"], m["cantidad"], m["sucursal"]) for m in del_traslado] == [
        ("traslado_salida", -4, "Principal"),
        ("traslado_entrada", 4, "Norte"),
    ]
    assert verificar_consistencia(s) == []


def test_traslado_sin_stock_suficiente_no_cambia_nada(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 3, "1")
    movimientos = contar(s, MovimientoInventario)
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=4)
    assert contar(s, Traslado) == 0  # ni siquiera el registro del traslado
    assert contar(s, MovimientoInventario) == movimientos
    assert stock_actual(s, t.p1.id, t.principal.id) == 3
    assert stock_actual(s, t.p1.id, t.norte.id) == 0


def test_traslado_invalido(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 5, "1")
    with pytest.raises(ErrorDeNegocio):
        trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.principal.id, cantidad=1)
    with pytest.raises(ErrorDeNegocio):
        trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=0)
    with pytest.raises(ErrorDeNegocio):
        trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=9999, cantidad=1)
    t.norte.activa = False
    s.flush()
    with pytest.raises(ErrorDeNegocio):
        trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=1)
    assert contar(s, Traslado) == 0


# ---- el stock siempre coincide con el kardex -----------------------------------------


def test_el_stock_coincide_siempre_con_la_suma_de_movimientos(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 50, "1.10")
    comprar(s, administrador, t, t.p2, 30, "3.00", sucursal=t.norte)
    trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=12)
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.norte.id, cantidad=2, motivo="Roto")
    ajustar_stock(s, administrador, producto_id=t.p2.id, sucursal_id=t.norte.id, conteo_fisico=28, motivo="Conteo")
    for _ in range(3):  # intentos rechazados no deben alterar nada
        with pytest.raises(ErrorDeNegocio):
            registrar_merma(s, administrador, producto_id=t.p2.id, sucursal_id=t.principal.id, cantidad=1, motivo="Nada")
    comprar(s, administrador, t, t.p1, 5, "1.50")
    s.commit()

    assert verificar_consistencia(s) == []
    for producto in (t.p1, t.p2):
        for sucursal in (t.principal, t.norte):
            suma = s.scalar(
                select(func.coalesce(func.sum(MovimientoInventario.cantidad), 0)).where(
                    MovimientoInventario.producto_id == producto.id,
                    MovimientoInventario.sucursal_id == sucursal.id,
                )
            )
            assert stock_actual(s, producto.id, sucursal.id) == suma


def test_la_verificacion_detecta_un_stock_editado_a_mano(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    assert verificar_consistencia(s) == []
    s.execute(update(Existencia.__table__).values(cantidad=99))  # alguien toca la tabla directamente
    diferencias = verificar_consistencia(s)
    assert len(diferencias) == 1
    assert (diferencias[0]["suma_movimientos"], diferencias[0]["existencia"]) == (10, 99)


# ---- existencias, alertas y kardex ---------------------------------------------------


def test_alerta_de_stock_bajo_incluye_el_minimo_exacto(sesion_servicios, administrador, t):
    s = sesion_servicios
    skus = lambda sucursal=None: [a["sku"] for a in alertas_stock_bajo(s, administrador, sucursal)]  # noqa: E731
    assert skus() == ["P1"]  # mínimo 10, stock 0: ya está bajo; P2 no tiene mínimo configurado
    comprar(s, administrador, t, t.p1, 10, "1")
    assert skus() == ["P1"]  # 10 <= 10
    comprar(s, administrador, t, t.p1, 1, "1")
    assert skus() == []  # 11 > 10
    assert skus(t.norte.id) == ["P1"]  # en Norte hay 0 y su mínimo es 10


def test_el_stock_bajo_se_evalua_por_sucursal_o_en_total(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1", sucursal=t.principal)
    comprar(s, administrador, t, t.p1, 5, "1", sucursal=t.norte)
    por_sucursal = {
        nombre: existencias(s, administrador, sid)[0]
        for nombre, sid in (("principal", t.principal.id), ("norte", t.norte.id), ("total", None))
    }
    assert [(k, v["stock"], v["bajo_minimo"]) for k, v in por_sucursal.items() if v["sku"] == "P1"] == [
        ("principal", 10, True),
        ("norte", 5, True),
        ("total", 15, False),
    ]


def test_existencias_busqueda_y_filtro_de_stock_bajo(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p2, 4, "3")
    assert [f["sku"] for f in existencias(s, administrador, t.principal.id, texto="producto 2")] == ["P2"]
    assert [f["sku"] for f in existencias(s, administrador, t.principal.id, texto="111")] == ["P1"]
    assert [f["sku"] for f in existencias(s, administrador, t.principal.id, solo_bajo_minimo=True)] == ["P1"]
    fila = existencias(s, administrador, t.principal.id, texto="P2")[0]
    assert fila["stock"] == 4 and fila["valor"] == Decimal("12.00") and fila["categoria"] == "General"


def test_los_productos_desactivados_no_salen_en_existencias(sesion_servicios, administrador, t):
    s = sesion_servicios
    establecer_activo(s, administrador, t.p2.id, False)
    assert [f["sku"] for f in existencias(s, administrador)] == ["P1"]
    assert {f["sku"] for f in existencias(s, administrador, incluir_inactivos=True)} == {"P1", "P2"}


def test_kardex_en_orden_con_filtros(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=2, motivo="Roto")
    comprar(s, administrador, t, t.p1, 5, "1", sucursal=t.norte)

    todos = kardex(s, administrador, t.p1.id)
    assert [m["id"] for m in todos] == sorted(m["id"] for m in todos)
    assert [(m["tipo"], m["cantidad"], m["saldo"]) for m in kardex(s, administrador, t.p1.id, t.principal.id)] == [
        ("entrada", 10, 10),
        ("merma", -2, 8),
    ]
    assert [m["sucursal"] for m in kardex(s, administrador, t.p1.id, t.norte.id)] == ["Norte"]
    assert kardex(s, administrador, t.p1.id, desde=datetime(2999, 1, 1)) == []
    assert len(kardex(s, administrador, t.p1.id, hasta=datetime(2999, 1, 1))) == 3
    assert kardex(s, administrador, t.p2.id) == []
    with pytest.raises(ErrorDeNegocio):
        kardex(s, administrador, 9999)


# ---- proveedores y sucursales --------------------------------------------------------


def test_proveedores_y_sucursales(sesion_servicios, administrador, t):
    s = sesion_servicios
    with pytest.raises(ErrorDeNegocio):
        crear_proveedor(s, administrador, "distribuidora")
    with pytest.raises(ErrorDeNegocio):
        crear_proveedor(s, administrador, "  ")
    with pytest.raises(ErrorDeNegocio):
        crear_sucursal(s, administrador, "PRINCIPAL")
    assert [p["nombre"] for p in listar_proveedores(s, administrador)] == ["Distribuidora"]
    establecer_proveedor_activo(s, administrador, t.proveedor.id, False)
    assert listar_proveedores(s, administrador) == []
    assert len(listar_proveedores(s, administrador, incluir_inactivos=True)) == 1
    assert [x["nombre"] for x in listar_sucursales(s, administrador)] == ["Principal", "Norte"]


# ---- permisos ------------------------------------------------------------------------


def test_vendedor_y_contador_solo_consultan(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    for rol in ("vendedor", "contador"):
        usuario = crear_con_rol(rol)
        assert existencias(s, usuario, t.principal.id)
        assert kardex(s, usuario, t.p1.id)
        assert listar_sucursales(s, usuario)
        operaciones = [
            lambda: comprar(s, usuario, t, t.p1, 1, "1"),
            lambda: registrar_merma(s, usuario, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=1, motivo="x"),
            lambda: trasladar(s, usuario, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=1),
            lambda: ajustar_stock(s, usuario, producto_id=t.p1.id, sucursal_id=t.principal.id, conteo_fisico=1, motivo="x"),
            lambda: crear_proveedor(s, usuario, "Otro"),
            lambda: crear_sucursal(s, usuario, "Sur"),
            lambda: establecer_proveedor_activo(s, usuario, t.proveedor.id, False),
            lambda: exportar_existencias_csv(s, usuario),
            lambda: exportar_kardex_csv(s, usuario, t.p1.id),
        ]
        for operacion in operaciones:
            with pytest.raises(PermisoDenegado):
                operacion()
    assert stock_actual(s, t.p1.id) == 10


def test_bodeguero_opera_el_inventario(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    bodeguero = crear_con_rol("bodeguero")
    comprar(s, bodeguero, t, t.p1, 20, "1")
    registrar_merma(s, bodeguero, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=1, motivo="Roto")
    trasladar(s, bodeguero, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=5)
    ajustar_stock(s, bodeguero, producto_id=t.p1.id, sucursal_id=t.principal.id, conteo_fisico=10, motivo="Conteo")
    assert exportar_existencias_csv(s, bodeguero)
    assert stock_actual(s, t.p1.id) == 15
    assert kardex(s, administrador, t.p1.id)[0]["usuario"] == bodeguero.nombre
    assert verificar_consistencia(s) == []


def test_un_usuario_sin_permiso_no_consulta_el_inventario(sesion_servicios, administrador, crear_con_rol, t):
    from app.servicios.usuarios import establecer_permiso_individual

    vendedor = crear_con_rol("vendedor")
    establecer_permiso_individual(sesion_servicios, administrador, vendedor.id, "inventario", "ver", False)
    with pytest.raises(PermisoDenegado):
        existencias(sesion_servicios, vendedor)
    with pytest.raises(PermisoDenegado):
        kardex(sesion_servicios, vendedor, t.p1.id)


# ---- exportación y auditoría ---------------------------------------------------------


def test_exportar_existencias_y_kardex_a_csv(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1.50")
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=2, motivo="Roto, con coma")

    filas = list(csv.reader(io.StringIO(exportar_existencias_csv(s, administrador, t.principal.id))))
    assert filas[0][:4] == ["SKU", "Producto", "Categoría", "Stock"]
    p1 = next(f for f in filas[1:] if f[0] == "P1")
    assert p1[3] == "8" and p1[7] == "sí"  # 8 <= 10: stock bajo

    movimientos = list(csv.reader(io.StringIO(exportar_kardex_csv(s, administrador, t.p1.id, t.principal.id))))
    assert movimientos[0][2:5] == ["Tipo", "Cantidad", "Saldo"]
    assert [m[2:5] for m in movimientos[1:]] == [["entrada", "10", "10"], ["merma", "-2", "8"]]
    assert movimientos[2][6] == "Roto, con coma"  # la coma no rompe el CSV
    with pytest.raises(ErrorDeNegocio):
        exportar_kardex_csv(s, administrador, 9999)


def test_las_operaciones_quedan_en_la_bitacora(sesion_servicios, administrador, t):
    s = sesion_servicios
    comprar(s, administrador, t, t.p1, 10, "1")
    registrar_merma(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, cantidad=1, motivo="Roto")
    ajustar_stock(s, administrador, producto_id=t.p1.id, sucursal_id=t.principal.id, conteo_fisico=5, motivo="Conteo")
    trasladar(s, administrador, producto_id=t.p1.id, origen_id=t.principal.id, destino_id=t.norte.id, cantidad=2)
    acciones = set(s.scalars(select(BitacoraAuditoria.accion)))
    assert {
        "sucursal_creada", "proveedor_creado", "compra_registrada", "merma_registrada",
        "ajuste_inventario", "traslado_registrado",
    } <= acciones
    ajuste = s.scalars(select(BitacoraAuditoria).where(BitacoraAuditoria.accion == "ajuste_inventario")).one()
    assert ajuste.detalle["antes"] == 9 and ajuste.detalle["despues"] == 5 and ajuste.usuario_id == administrador.id


# ---- seed ----------------------------------------------------------------------------


def test_seed_deja_stock_inicial_consistente_y_una_alerta(sesion_servicios):
    s = sesion_servicios
    sembrar(s, "Admin", "a@x.com", "claveSegura1")
    s.commit()
    admin = s.scalar(select(Usuario))
    principal = s.scalar(select(Sucursal).where(Sucursal.nombre == "Principal"))

    filas = existencias(s, admin, principal.id)
    assert {f["sku"]: f["stock"] for f in filas} == STOCK_INICIAL_EJEMPLO
    assert [a["sku"] for a in alertas_stock_bajo(s, admin, principal.id)] == ["SNK-002"]
    assert verificar_consistencia(s) == []

    sembrar(s, "Admin", "a@x.com", "claveSegura1")  # segunda vez: no duplica
    s.commit()
    assert contar(s, Compra) == 1
    assert {f["sku"]: f["stock"] for f in existencias(s, admin, principal.id)} == STOCK_INICIAL_EJEMPLO
