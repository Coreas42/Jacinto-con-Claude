"""Pruebas de la fase de interfaz: gastos, clientes, proveedores, panel de inicio y tema."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, select

from app.config import cargar_configuracion
from app.modelos import BitacoraAuditoria, Gasto, Permiso, Rol
from app.servicios.catalogo import crear_categoria, crear_producto, editar_producto
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.gastos import (
    anular_gasto,
    crear_gasto,
    gastos_por_categoria,
    listar_gastos,
    total_gastos,
)
from app.servicios.inicio import _cambio_porcentual, panel_inicio
from app.servicios.inventario import (
    crear_proveedor,
    crear_sucursal,
    editar_proveedor,
    listar_proveedores,
    registrar_compra,
)
from app.servicios.permisos import MATRIZ_BASE, sembrar_permisos_y_roles
from app.servicios.reportes import resultado_del_periodo
from app.servicios.ventas import (
    crear_cliente,
    editar_cliente,
    establecer_cliente_activo,
    listar_clientes,
    registrar_venta,
)
from app.ui import tema


@pytest.fixture()
def t(sesion_servicios, administrador, crear_con_rol):
    """P1 (precio 10, costo 4, 20 u.). Venta del vendedor: 2×P1 (20). Venta del administrador: 1×P1 (10)."""
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    principal = crear_sucursal(s, administrador, "Principal")
    norte = crear_sucursal(s, administrador, "Norte")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id, precio="10", costo="4")
    registrar_compra(
        s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
        lineas=[{"producto_id": p1.id, "cantidad": 20, "costo_unitario": "4"}],
    )
    for actor, cantidad in ((vendedor, 2), (administrador, 1)):
        registrar_venta(
            s, actor, sucursal_id=principal.id, metodo_pago="efectivo",
            lineas=[{"producto_id": p1.id, "cantidad": cantidad}],
        )
    s.commit()
    return SimpleNamespace(principal=principal, norte=norte, p1=p1, vendedor=vendedor, proveedor=proveedor)


# ---- gastos ----------------------------------------------------------------------------


def test_migracion_crea_tabla_de_gastos(motor):
    assert "gastos" in inspect(motor).get_table_names()


def test_crear_gasto_guarda_y_audita(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    contador = crear_con_rol("contador")
    g = crear_gasto(s, contador, categoria="Alquiler", descripcion="  Local de octubre ", monto="350,50")
    s.commit()
    assert (g.categoria, g.descripcion, g.monto) == ("alquiler", "Local de octubre", Decimal("350.50"))
    assert g.fecha == date.today() and g.usuario_id == contador.id and g.estado == "activo"
    assert s.scalars(select(BitacoraAuditoria.accion).where(BitacoraAuditoria.accion == "gasto_registrado")).all()


def test_solo_quien_tiene_permiso_registra_o_ve_gastos(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    for actor in (t.vendedor, crear_con_rol("bodeguero")):
        with pytest.raises(PermisoDenegado):
            crear_gasto(s, actor, categoria="otros", descripcion="x", monto="1")
        s.rollback()
        with pytest.raises(PermisoDenegado):
            listar_gastos(s, actor)
        s.rollback()


@pytest.mark.parametrize(
    "cambios",
    [
        {"monto": "0"},
        {"monto": "-5"},
        {"monto": "abc"},
        {"categoria": "viajes"},
        {"descripcion": "   "},
        {"fecha": date.today() + timedelta(days=1)},
        {"fecha": "31/10/2026"},
        {"sucursal_id": 9999},
    ],
)
def test_validaciones_de_gasto(sesion_servicios, administrador, t, cambios):
    datos = {"categoria": "otros", "descripcion": "Compra", "monto": "10"}
    datos.update(cambios)
    with pytest.raises(ErrorDeNegocio):
        crear_gasto(sesion_servicios, administrador, **datos)
    sesion_servicios.rollback()
    assert not sesion_servicios.scalars(select(Gasto)).all()


def test_fecha_como_texto_y_sucursal(sesion_servicios, administrador, t):
    g = crear_gasto(
        sesion_servicios, administrador, categoria="servicios", descripcion="Agua", monto="12",
        fecha="2026-01-15", sucursal_id=t.norte.id,
    )
    assert g.fecha == date(2026, 1, 15) and g.sucursal_id == t.norte.id


def test_anular_gasto(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    g = crear_gasto(s, administrador, categoria="otros", descripcion="Error de digitación", monto="99")
    crear_gasto(s, administrador, categoria="otros", descripcion="Bueno", monto="1")
    s.commit()
    with pytest.raises(ErrorDeNegocio, match="motivo"):
        anular_gasto(s, administrador, g.id, " ")
    with pytest.raises(PermisoDenegado):
        anular_gasto(s, t.vendedor, g.id, "x")
    s.rollback()
    anular_gasto(s, administrador, g.id, "Se capturó dos veces")
    s.commit()
    assert (g.estado, g.anulado_por, g.motivo_anulacion) == ("anulado", administrador.id, "Se capturó dos veces")
    with pytest.raises(ErrorDeNegocio, match="ya está anulado"):
        anular_gasto(s, administrador, g.id, "otra vez")
    s.rollback()
    assert total_gastos(s, administrador) == Decimal("1.00")  # el anulado no cuenta
    assert len(listar_gastos(s, administrador)) == 1
    assert len(listar_gastos(s, administrador, incluir_anulados=True)) == 2


def test_filtros_y_totales_de_gastos(sesion_servicios, administrador, t):
    s = sesion_servicios
    crear_gasto(s, administrador, categoria="alquiler", descripcion="a", monto="100", fecha="2026-03-01")
    crear_gasto(s, administrador, categoria="servicios", descripcion="b", monto="40", fecha="2026-03-10", sucursal_id=t.norte.id)
    crear_gasto(s, administrador, categoria="servicios", descripcion="c", monto="10", fecha="2026-04-02")
    s.commit()
    assert total_gastos(s, administrador) == Decimal("150.00")
    assert total_gastos(s, administrador, desde=date(2026, 3, 1), hasta=date(2026, 3, 31)) == Decimal("140.00")
    assert total_gastos(s, administrador, categoria="servicios") == Decimal("50.00")
    assert total_gastos(s, administrador, sucursal_id=t.norte.id) == Decimal("40.00")
    por_cat = gastos_por_categoria(s, administrador)
    assert [(f["categoria"], f["total"], f["cantidad"]) for f in por_cat] == [
        ("alquiler", Decimal("100.00"), 1), ("servicios", Decimal("50.00"), 2),
    ]
    assert [g["fecha"] for g in listar_gastos(s, administrador)] == [date(2026, 4, 2), date(2026, 3, 10), date(2026, 3, 1)]
    assert listar_gastos(s, administrador)[1]["sucursal"] == "Norte" and listar_gastos(s, administrador)[0]["sucursal"] == "General"


# ---- resultado neto --------------------------------------------------------------------


def test_utilidad_neta_es_utilidad_bruta_menos_gastos(sesion_servicios, administrador, t):
    s = sesion_servicios
    crear_gasto(s, administrador, categoria="alquiler", descripcion="Local", monto="5")
    anulado = crear_gasto(s, administrador, categoria="otros", descripcion="Error", monto="100")
    anular_gasto(s, administrador, anulado.id, "Error")
    s.commit()
    r = resultado_del_periodo(s, administrador, date.today(), date.today())
    # 3 unidades: ingreso 30, costo 12, utilidad bruta 18; gastos 5 -> neta 13
    assert (r["ingreso"], r["costo"], r["utilidad_bruta"]) == (Decimal("30.00"), Decimal("12.00"), Decimal("18.00"))
    assert (r["gastos"], r["utilidad_neta"], r["margen_neto"]) == (Decimal("5.00"), Decimal("13.00"), Decimal("43.3"))


def test_resultado_por_sucursal_excluye_gastos_generales(sesion_servicios, administrador, t):
    s = sesion_servicios
    crear_gasto(s, administrador, categoria="otros", descripcion="General", monto="7")
    crear_gasto(s, administrador, categoria="otros", descripcion="Principal", monto="3", sucursal_id=t.principal.id)
    s.commit()
    assert resultado_del_periodo(s, administrador)["gastos"] == Decimal("10.00")
    assert resultado_del_periodo(s, administrador, sucursal_id=t.principal.id)["gastos"] == Decimal("3.00")


def test_resultado_exige_ver_costos(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    assert resultado_del_periodo(s, crear_con_rol("contador"))["utilidad_bruta"] == Decimal("18.00")
    with pytest.raises(PermisoDenegado):
        resultado_del_periodo(s, t.vendedor)


# ---- clientes y proveedores --------------------------------------------------------------


def test_editar_y_desactivar_cliente(sesion_servicios, administrador, t):
    s = sesion_servicios
    cliente = crear_cliente(s, administrador, "Ana", "555")
    s.commit()
    editar_cliente(s, t.vendedor, cliente.id, "Ana Pérez", None, "ana@x.com")  # el vendedor puede editar
    s.commit()
    assert [(c["nombre"], c["telefono"], c["correo"]) for c in listar_clientes(s, administrador)] == [("Ana Pérez", None, "ana@x.com")]
    with pytest.raises(ErrorDeNegocio):
        editar_cliente(s, administrador, cliente.id, "  ")
    with pytest.raises(ErrorDeNegocio, match="no existe"):
        editar_cliente(s, administrador, 9999, "X")
    s.rollback()

    with pytest.raises(PermisoDenegado):  # desactivar exige ventas.anular
        establecer_cliente_activo(s, t.vendedor, cliente.id, False)
    s.rollback()
    establecer_cliente_activo(s, administrador, cliente.id, False)
    s.commit()
    assert listar_clientes(s, administrador) == []
    assert len(listar_clientes(s, administrador, incluir_inactivos=True)) == 1
    with pytest.raises(ErrorDeNegocio, match="desactivado"):
        registrar_venta(
            s, administrador, sucursal_id=t.principal.id, metodo_pago="efectivo", cliente_id=cliente.id,
            lineas=[{"producto_id": t.p1.id, "cantidad": 1}],
        )
    s.rollback()
    establecer_cliente_activo(s, administrador, cliente.id, True)
    assert len(listar_clientes(s, administrador)) == 1


def test_buscar_clientes(sesion_servicios, administrador):
    s = sesion_servicios
    crear_cliente(s, administrador, "Ana Pérez", "7000-1111")
    crear_cliente(s, administrador, "Luis Gómez", None, "luis@x.com")
    assert [c["nombre"] for c in listar_clientes(s, administrador, "pérez")] == ["Ana Pérez"]
    assert [c["nombre"] for c in listar_clientes(s, administrador, "7000")] == ["Ana Pérez"]
    assert [c["nombre"] for c in listar_clientes(s, administrador, "luis@")] == ["Luis Gómez"]


def test_editar_proveedor(sesion_servicios, administrador, t):
    s = sesion_servicios
    otro = crear_proveedor(s, administrador, "Otro")
    s.commit()
    editar_proveedor(s, administrador, t.proveedor.id, "Distribuidora Norte", "2222-3333")
    s.commit()
    assert {p["nombre"]: p["contacto"] for p in listar_proveedores(s, administrador)}["Distribuidora Norte"] == "2222-3333"
    with pytest.raises(ErrorDeNegocio, match="Ya existe"):
        editar_proveedor(s, administrador, otro.id, "distribuidora norte")
    s.rollback()
    editar_proveedor(s, administrador, t.proveedor.id, "Distribuidora Norte", None)  # no choca consigo mismo
    with pytest.raises(PermisoDenegado):
        editar_proveedor(s, t.vendedor, t.proveedor.id, "X")


# ---- panel de inicio -------------------------------------------------------------------


def test_panel_del_administrador(sesion_servicios, administrador, t):
    s = sesion_servicios
    crear_cliente(s, administrador, "Ana")
    p = panel_inicio(s, administrador)
    assert (p["ventas_hoy"]["ventas"], p["ventas_hoy"]["unidades"]) == (2, 3)
    assert (p["ventas_hoy"]["ingreso"], p["ventas_hoy"]["utilidad"]) == (Decimal("30.00"), Decimal("18.00"))
    assert p["cambio_ventas"] is None and p["cambio_ganancia"] is None  # ayer no hubo ventas
    assert len(p["serie"]) == 7 and p["serie"][-1]["dia"] == date.today()
    assert (p["serie"][-1]["ingreso"], p["serie"][-1]["utilidad"]) == (Decimal("30.00"), Decimal("18.00"))
    assert all(f["ingreso"] == 0 and f["utilidad"] == 0 for f in p["serie"][:-1])
    assert [f["clave"] for f in p["mas_vendidos"]] == ["P1 · Producto 1"]
    assert len(p["ultimas_ventas"]) == 2
    assert p["inventario"] == {"productos": 1, "unidades": 17, "valor": Decimal("68.00"), "stock_bajo": 0}
    assert p["clientes"] == 1


def test_panel_marca_stock_bajo(sesion_servicios, administrador, t):
    s = sesion_servicios
    editar_producto(s, administrador, t.p1.id, {"stock_minimo": 20})
    assert panel_inicio(s, administrador)["inventario"]["stock_bajo"] == 1


def test_panel_del_vendedor_solo_ve_lo_suyo_y_sin_ganancia(sesion_servicios, t):
    p = panel_inicio(sesion_servicios, t.vendedor)
    assert p["ventas_hoy"]["ingreso"] == Decimal("20.00") and p["ventas_hoy"]["utilidad"] is None
    assert p["cambio_ganancia"] is None
    assert all(f["utilidad"] is None for f in p["serie"]) and p["serie"][-1]["ingreso"] == Decimal("20.00")
    assert len(p["ultimas_ventas"]) == 1
    assert p["mas_vendidos"][0]["costo"] is None


def test_panel_del_bodeguero_solo_muestra_inventario(sesion_servicios, crear_con_rol, t):
    p = panel_inicio(sesion_servicios, crear_con_rol("bodeguero"))
    assert p["ventas_hoy"] is None and p["serie"] is None and p["mas_vendidos"] is None
    assert p["ultimas_ventas"] is None and p["clientes"] is None
    assert p["inventario"]["unidades"] == 17


def test_cambio_porcentual():
    assert _cambio_porcentual(Decimal("150"), Decimal("100")) == Decimal("50.0")
    assert _cambio_porcentual(Decimal("50"), Decimal("200")) == Decimal("-75.0")
    assert _cambio_porcentual(Decimal("10"), Decimal("0")) is None


# ---- permisos y módulos nuevos -----------------------------------------------------------


def test_matriz_de_gastos():
    assert MATRIZ_BASE["contador"]["gastos"] == ["ver", "crear", "anular"]
    assert "gastos" not in MATRIZ_BASE["vendedor"] and "gastos" not in MATRIZ_BASE["bodeguero"]


def test_actualizar_instalacion_agrega_los_permisos_de_gastos(sesion_servicios, administrador):
    s = sesion_servicios
    nuevos = s.scalars(select(Permiso).where(Permiso.modulo == "gastos")).all()
    for rol in s.scalars(select(Rol)):
        rol.permisos = [p for p in rol.permisos if p.modulo != "gastos"]
    for p in nuevos:
        s.delete(p)
    s.commit()
    sembrar_permisos_y_roles(s)
    s.commit()
    por_rol = {r.nombre: {(p.modulo, p.accion) for p in r.permisos if p.modulo == "gastos"} for r in s.scalars(select(Rol))}
    assert por_rol["administrador"] == {("gastos", "ver"), ("gastos", "crear"), ("gastos", "anular")}
    assert por_rol["contador"] == por_rol["administrador"]
    assert por_rol["vendedor"] == set() and por_rol["bodeguero"] == set()


# ---- tema y configuración ----------------------------------------------------------------


def test_tema_formatos():
    assert tema.fecha_larga(date(2026, 10, 23)) == "Viernes 23 de Octubre 2026"
    assert tema.dinero(Decimal("1234.5")) == "$ 1,234.50" and tema.dinero(None) == "—"
    assert tema.texto_cambio(Decimal("12.0")) == ("↑ +12.0% vs ayer", tema.VERDE)
    assert tema.texto_cambio(Decimal("-3.5")) == ("↓ -3.5% vs ayer", tema.ROJO)
    assert tema.texto_cambio(None)[0] == "" and tema.texto_cambio(Decimal("0"))[0] == "= igual que ayer"


def test_tema_reemplaza_azules_por_morado_sin_tocar_el_resto():
    theme = {
        "CTkButton": {"fg_color": ["#3B8ED0", "#1F6AA5"], "text_color": ["gray10", "#DCE4EE"], "corner_radius": 6},
        "CTkFrame": {"fg_color": ["gray86", "gray17"]},
        "CTk": {"fg_color": ["gray92", "gray14"]},
    }
    tema._recolorear(theme)
    assert theme["CTkButton"]["fg_color"] == [tema.ACENTO, tema.ACENTO]
    assert theme["CTkButton"]["text_color"] == ["gray10", tema.TEXTO] and theme["CTkButton"]["corner_radius"] == 6
    assert theme["CTkFrame"]["fg_color"] == ["gray86", tema.SUPERFICIE]
    assert theme["CTk"]["fg_color"] == ["gray92", tema.FONDO]


def test_configuracion_lee_el_eslogan(monkeypatch):
    monkeypatch.setenv("ESLOGAN_EMPRESA", "  ACCESORIOS • POLARIZADO ")
    assert cargar_configuracion().eslogan == "ACCESORIOS • POLARIZADO"
    monkeypatch.delenv("ESLOGAN_EMPRESA")
    assert cargar_configuracion().eslogan == ""
