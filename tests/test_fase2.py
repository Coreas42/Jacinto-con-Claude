"""Pruebas de la Fase 2: catálogo de productos, historial de precios y permisos."""

from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select

from app.modelos import BitacoraAuditoria, HistorialProducto, Producto
from app.servicios.catalogo import (
    buscar_productos,
    crear_categoria,
    crear_producto,
    editar_producto,
    establecer_activo,
    historial_producto,
    listar_categorias,
    obtener_por_codigo,
)
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.usuarios import establecer_permiso_individual
from seed import PRODUCTOS_EJEMPLO, sembrar


@pytest.fixture()
def categoria(sesion_servicios, administrador):
    cat = crear_categoria(sesion_servicios, administrador, "Bebidas")
    sesion_servicios.commit()
    return cat


@pytest.fixture()
def producto(sesion_servicios, administrador, categoria):
    p = crear_producto(
        sesion_servicios,
        administrador,
        sku="bev-001",
        nombre="Agua 600 ml",
        categoria_id=categoria.id,
        precio="0.60",
        costo="0.35",
        stock_minimo=10,
        codigo_barras="7501",
        marca="Pura",
    )
    sesion_servicios.commit()
    return p


def contar(sesion, modelo, *condiciones):
    return sesion.scalar(select(func.count()).select_from(modelo).where(*condiciones))


# ---- esquema y alta ----------------------------------------------------------------


def test_migracion_crea_tablas_del_catalogo(motor):
    assert {"categorias", "productos", "historial_productos"} <= set(inspect(motor).get_table_names())


def test_el_producto_no_tiene_columna_de_stock(motor):
    columnas = {c["name"] for c in inspect(motor).get_columns("productos")}
    assert not {"stock", "existencias", "cantidad"} & columnas


def test_alta_normaliza_sku_y_codigo_vacio(sesion_servicios, administrador, categoria):
    p = crear_producto(
        sesion_servicios, administrador, sku="  ab-1 ", nombre=" Lápiz ", categoria_id=categoria.id,
        precio="1,50", codigo_barras="   ",
    )
    assert p.sku == "AB-1"
    assert p.nombre == "Lápiz"
    assert p.codigo_barras is None
    assert p.precio == Decimal("1.50")
    assert p.costo_promedio == Decimal("0.00")


@pytest.mark.parametrize(
    "texto, esperado",
    [("12.5", "12.50"), ("12,50", "12.50"), ("1,234.50", "1234.50"), (3, "3.00"), (0.1, "0.10"), ("2.005", "2.01")],
)
def test_formatos_de_dinero(sesion_servicios, administrador, categoria, texto, esperado):
    p = crear_producto(
        sesion_servicios, administrador, sku="X", nombre="X", categoria_id=categoria.id, precio=texto
    )
    assert p.precio == Decimal(esperado)


@pytest.mark.parametrize("precio", ["-1", "abc", "", "nan", "inf", "99999999999999"])
def test_precios_invalidos_se_rechazan(sesion_servicios, administrador, categoria, precio):
    with pytest.raises(ErrorDeNegocio):
        crear_producto(sesion_servicios, administrador, sku="X", nombre="X", categoria_id=categoria.id, precio=precio)


def test_otros_datos_invalidos(sesion_servicios, administrador, categoria):
    base = dict(sku="X", nombre="X", categoria_id=categoria.id, precio="1")
    for cambio in ({"sku": " "}, {"nombre": ""}, {"stock_minimo": "-3"}, {"stock_minimo": "dos"}, {"categoria_id": 999}):
        with pytest.raises(ErrorDeNegocio):
            crear_producto(sesion_servicios, administrador, **{**base, **cambio})


def test_sku_y_codigo_de_barras_son_unicos(sesion_servicios, administrador, categoria, producto):
    base = dict(nombre="Otro", categoria_id=categoria.id, precio="1")
    with pytest.raises(ErrorDeNegocio):
        crear_producto(sesion_servicios, administrador, sku="BEV-001", **base)  # SKU repetido
    with pytest.raises(ErrorDeNegocio):
        crear_producto(sesion_servicios, administrador, sku="NUEVO", codigo_barras="7501", **base)
    with pytest.raises(ErrorDeNegocio):  # el código de otro producto no puede ser mi SKU
        crear_producto(sesion_servicios, administrador, sku="7501", **base)
    with pytest.raises(ErrorDeNegocio):  # ni mi código de barras el SKU de otro
        crear_producto(sesion_servicios, administrador, sku="NUEVO", codigo_barras="BEV-001", **base)


def test_categoria_duplicada_se_rechaza(sesion_servicios, administrador, categoria):
    with pytest.raises(ErrorDeNegocio):
        crear_categoria(sesion_servicios, administrador, "bebidas")


# ---- historial de precios y costos ---------------------------------------------------


def test_el_alta_deja_el_historial_inicial(sesion_servicios, administrador, producto):
    filas = historial_producto(sesion_servicios, administrador, producto.id)
    por_campo = {f["campo"]: f for f in filas}
    assert por_campo["precio"]["anterior"] is None and por_campo["precio"]["nuevo"] == "0.60"
    assert por_campo["costo"]["nuevo"] == "0.35"


def test_cambiar_el_precio_crea_fila_con_anterior_nuevo_usuario_y_fecha(
    sesion_servicios, administrador, producto
):
    cambiados = editar_producto(sesion_servicios, administrador, producto.id, {"precio": "0.75"})
    sesion_servicios.commit()
    assert cambiados == ["precio"]
    ultima = historial_producto(sesion_servicios, administrador, producto.id)[0]
    assert ultima["campo"] == "precio"
    assert ultima["anterior"] == "0.60"
    assert ultima["nuevo"] == "0.75"
    assert ultima["usuario"] == administrador.nombre
    assert ultima["fecha"] is not None
    assert producto.precio == Decimal("0.75")


def test_cambiar_el_costo_tambien_queda_en_historial(sesion_servicios, administrador, producto):
    editar_producto(sesion_servicios, administrador, producto.id, {"costo": "0.40"})
    ultima = historial_producto(sesion_servicios, administrador, producto.id)[0]
    assert (ultima["campo"], ultima["anterior"], ultima["nuevo"]) == ("costo", "0.35", "0.40")


def test_sin_cambios_reales_no_se_crean_filas(sesion_servicios, administrador, producto):
    antes = contar(sesion_servicios, HistorialProducto)
    assert editar_producto(sesion_servicios, administrador, producto.id, {"precio": "0.6", "nombre": "Agua 600 ml"}) == []
    assert contar(sesion_servicios, HistorialProducto) == antes


def test_editar_deja_constancia_en_la_bitacora(sesion_servicios, administrador, producto):
    editar_producto(sesion_servicios, administrador, producto.id, {"precio": "0.80", "marca": "Otra"})
    evento = sesion_servicios.scalars(
        select(BitacoraAuditoria).where(BitacoraAuditoria.accion == "producto_editado")
    ).one()
    assert evento.usuario_id == administrador.id
    assert evento.detalle["precio"] == ["0.60", "0.80"]
    assert evento.detalle["marca"] == ["Pura", "Otra"]


def test_el_sku_no_se_puede_editar(sesion_servicios, administrador, producto):
    with pytest.raises(ErrorDeNegocio):
        editar_producto(sesion_servicios, administrador, producto.id, {"sku": "NUEVO"})
    with pytest.raises(ErrorDeNegocio):
        editar_producto(sesion_servicios, administrador, producto.id, {"activo": False})


def test_editar_codigo_de_barras_respeta_la_unicidad(sesion_servicios, administrador, categoria, producto):
    otro = crear_producto(
        sesion_servicios, administrador, sku="OTRO", nombre="Otro", categoria_id=categoria.id, precio="1"
    )
    with pytest.raises(ErrorDeNegocio):
        editar_producto(sesion_servicios, administrador, otro.id, {"codigo_barras": "7501"})
    editar_producto(sesion_servicios, administrador, producto.id, {"codigo_barras": "7501"})  # el suyo, sin error
    editar_producto(sesion_servicios, administrador, producto.id, {"codigo_barras": ""})
    assert producto.codigo_barras is None


# ---- desactivar en lugar de borrar ----------------------------------------------------


def test_producto_desactivado_no_aparece_al_vender_pero_conserva_su_historia(
    sesion_servicios, administrador, producto
):
    historial_antes = len(historial_producto(sesion_servicios, administrador, producto.id))
    establecer_activo(sesion_servicios, administrador, producto.id, False)
    sesion_servicios.commit()

    assert buscar_productos(sesion_servicios, administrador, "agua") == []
    assert obtener_por_codigo(sesion_servicios, administrador, "7501") is None
    assert obtener_por_codigo(sesion_servicios, administrador, "bev-001") is None

    assert len(buscar_productos(sesion_servicios, administrador, "agua", incluir_inactivos=True)) == 1
    assert obtener_por_codigo(sesion_servicios, administrador, "7501", solo_activos=False)["sku"] == "BEV-001"
    historial = historial_producto(sesion_servicios, administrador, producto.id)
    assert len(historial) == historial_antes + 1
    assert (historial[0]["campo"], historial[0]["nuevo"]) == ("activo", "inactivo")
    assert contar(sesion_servicios, Producto, Producto.id == producto.id) == 1  # no se borró

    establecer_activo(sesion_servicios, administrador, producto.id, True)
    assert obtener_por_codigo(sesion_servicios, administrador, "7501")["id"] == producto.id


# ---- búsqueda ------------------------------------------------------------------------


def test_busqueda_por_texto_codigo_marca_y_categoria(sesion_servicios, administrador, categoria, producto):
    snacks = crear_categoria(sesion_servicios, administrador, "Snacks")
    crear_producto(
        sesion_servicios, administrador, sku="SNK-1", nombre="Papas", categoria_id=snacks.id,
        precio="0.75", marca="Crunch", codigo_barras="9999",
    )
    buscar = lambda *a, **k: [p["sku"] for p in buscar_productos(sesion_servicios, administrador, *a, **k)]  # noqa: E731
    assert buscar() == ["BEV-001", "SNK-1"] or sorted(buscar()) == ["BEV-001", "SNK-1"]
    assert buscar("AGUA") == ["BEV-001"]
    assert buscar("snk") == ["SNK-1"]
    assert buscar("9999") == ["SNK-1"]
    assert buscar("crunch") == ["SNK-1"]
    assert buscar(categoria_id=snacks.id) == ["SNK-1"]
    assert buscar("agua", categoria_id=snacks.id) == []
    assert buscar("no existe") == []


def test_escaneo_por_codigo_o_sku(sesion_servicios, administrador, producto):
    por_codigo = obtener_por_codigo(sesion_servicios, administrador, " 7501 ")
    por_sku = obtener_por_codigo(sesion_servicios, administrador, "bev-001")
    assert por_codigo["id"] == por_sku["id"] == producto.id
    assert obtener_por_codigo(sesion_servicios, administrador, "") is None
    assert obtener_por_codigo(sesion_servicios, administrador, "nada") is None


def test_categoria_desactivada_no_admite_productos_nuevos(sesion_servicios, administrador, categoria):
    from app.servicios.catalogo import establecer_categoria_activa

    establecer_categoria_activa(sesion_servicios, administrador, categoria.id, False)
    assert listar_categorias(sesion_servicios, administrador) == []
    assert len(listar_categorias(sesion_servicios, administrador, incluir_inactivas=True)) == 1
    with pytest.raises(ErrorDeNegocio):
        crear_producto(sesion_servicios, administrador, sku="Z", nombre="Z", categoria_id=categoria.id, precio="1")


# ---- permisos ------------------------------------------------------------------------


def test_vendedor_solo_consulta(sesion_servicios, crear_con_rol, producto):
    vendedor = crear_con_rol("vendedor")
    assert len(buscar_productos(sesion_servicios, vendedor)) == 1
    with pytest.raises(PermisoDenegado):
        crear_producto(sesion_servicios, vendedor, sku="N", nombre="N", categoria_id=producto.categoria_id, precio="1")
    with pytest.raises(PermisoDenegado):
        editar_producto(sesion_servicios, vendedor, producto.id, {"nombre": "Hackeado"})
    with pytest.raises(PermisoDenegado):
        establecer_activo(sesion_servicios, vendedor, producto.id, False)
    with pytest.raises(PermisoDenegado):
        crear_categoria(sesion_servicios, vendedor, "Nueva")


def test_bodeguero_edita_datos_pero_no_precios_salvo_que_se_le_conceda(
    sesion_servicios, administrador, crear_con_rol, producto
):
    bodeguero = crear_con_rol("bodeguero")
    editar_producto(sesion_servicios, bodeguero, producto.id, {"stock_minimo": "25", "marca": "Nueva"})
    assert producto.stock_minimo == 25

    with pytest.raises(PermisoDenegado) as error:
        editar_producto(sesion_servicios, bodeguero, producto.id, {"precio": "9.99"})
    assert error.value.codigo_http == 403
    with pytest.raises(PermisoDenegado):
        editar_producto(sesion_servicios, bodeguero, producto.id, {"costo": "9.99"})
    assert producto.precio == Decimal("0.60")

    establecer_permiso_individual(sesion_servicios, administrador, bodeguero.id, "productos", "precios", True)
    editar_producto(sesion_servicios, bodeguero, producto.id, {"precio": "0.90"})
    ultima = historial_producto(sesion_servicios, administrador, producto.id)[0]
    assert ultima["usuario"] == bodeguero.nombre and ultima["nuevo"] == "0.90"


def test_la_matriz_base_reserva_los_precios_al_administrador(sesion_servicios, administrador, crear_con_rol):
    from app.servicios.permisos import tiene_permiso

    assert tiene_permiso(sesion_servicios, administrador, "productos", "precios")
    for rol in ("vendedor", "bodeguero", "contador"):
        assert not tiene_permiso(sesion_servicios, crear_con_rol(rol), "productos", "precios")


# ---- seed ------------------------------------------------------------------------------


def test_seed_carga_el_catalogo_de_ejemplo_una_sola_vez(sesion_servicios):
    sembrar(sesion_servicios, "Admin", "a@x.com", "claveSegura1")
    sesion_servicios.commit()
    assert contar(sesion_servicios, Producto) == len(PRODUCTOS_EJEMPLO) == 9
    sembrar(sesion_servicios, "Admin", "a@x.com", "claveSegura1")
    sesion_servicios.commit()
    assert contar(sesion_servicios, Producto) == 9
