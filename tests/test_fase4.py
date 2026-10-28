"""Pruebas de la Fase 4: ventas (POS), anulación, alcance por vendedor y comprobante."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select

from app.modelos import (
    BitacoraAuditoria,
    Existencia,
    MovimientoInventario,
    Permiso,
    Rol,
    Venta,
    VentaDetalle,
)
from app.servicios.catalogo import crear_categoria, crear_producto, establecer_activo
from app.servicios.comprobante import comprobante_html, comprobante_texto
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.inventario import (
    crear_proveedor,
    crear_sucursal,
    registrar_compra,
    stock_actual,
    verificar_consistencia,
)
from app.servicios.permisos import (
    MATRIZ_BASE,
    permisos_efectivos,
    sembrar_permisos_y_roles,
)
from app.servicios.ventas import (
    anular_venta,
    buscar_para_venta,
    crear_cliente,
    formatear_numero,
    listar_clientes,
    listar_ventas,
    obtener_venta,
    producto_para_venta,
    registrar_venta,
)


@pytest.fixture()
def t(sesion_servicios, administrador):
    """Tienda: sucursal Principal con P1 (precio 10, costo 4, 20 u.) y P2 (precio 5, costo 2, 5 u.)."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(
        s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id,
        precio="10", costo="4", codigo_barras="111",
    )
    p2 = crear_producto(
        s, administrador, sku="P2", nombre="Producto 2", categoria_id=categoria.id, precio="5", costo="2",
    )
    for producto, cantidad, costo in ((p1, 20, "4"), (p2, 5, "2")):
        registrar_compra(
            s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
            lineas=[{"producto_id": producto.id, "cantidad": cantidad, "costo_unitario": costo}],
        )
    s.commit()
    return SimpleNamespace(principal=principal, p1=p1, p2=p2)


def vender(s, actor, t, lineas, **extra):
    extra.setdefault("metodo_pago", "efectivo")
    return registrar_venta(s, actor, sucursal_id=t.principal.id, lineas=lineas, **extra)


def contar(s, modelo):
    return s.scalar(select(func.count()).select_from(modelo))


# ---- esquema y permisos --------------------------------------------------------------


def test_migracion_crea_tablas_de_ventas(motor):
    assert {"clientes", "ventas", "ventas_detalle"} <= set(inspect(motor).get_table_names())


def test_vendedor_ve_lo_suyo_y_contador_y_admin_ven_todo(sesion_servicios, administrador, crear_con_rol):
    s = sesion_servicios
    vendedor, contador = crear_con_rol("vendedor"), crear_con_rol("contador")
    assert ("ventas", "ver_todas") not in permisos_efectivos(s, vendedor)
    assert ("ventas", "ver_todas") in permisos_efectivos(s, contador)
    assert ("ventas", "ver_todas") in permisos_efectivos(s, administrador)
    assert ("ventas", "anular") not in permisos_efectivos(s, vendedor)


def test_actualizar_instalacion_existente_agrega_solo_permisos_nuevos(sesion_servicios, administrador):
    s = sesion_servicios
    # Simula una instalación anterior: el permiso ver_todas no existía y el vendedor fue personalizado.
    nuevo = s.scalar(select(Permiso).where(Permiso.modulo == "ventas", Permiso.accion == "ver_todas"))
    for rol in s.scalars(select(Rol)):
        rol.permisos = [p for p in rol.permisos if p.id != nuevo.id]
    vendedor = s.scalar(select(Rol).where(Rol.nombre == "vendedor"))
    vendedor.permisos = [p for p in vendedor.permisos if (p.modulo, p.accion) != ("reportes", "ver")]
    s.delete(nuevo)
    s.commit()

    sembrar_permisos_y_roles(s)
    s.commit()

    por_rol = {r.nombre: {(p.modulo, p.accion) for p in r.permisos} for r in s.scalars(select(Rol))}
    assert ("ventas", "ver_todas") in por_rol["contador"]
    assert ("ventas", "ver_todas") in por_rol["administrador"]
    assert ("ventas", "ver_todas") not in por_rol["vendedor"]
    # lo que el administrador había quitado al vendedor no se restituye
    assert ("reportes", "ver") not in por_rol["vendedor"]


# ---- registrar venta -----------------------------------------------------------------


def test_venta_calcula_totales_congela_precio_y_costo_y_descuenta_stock(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    venta = vender(
        s, vendedor, t,
        [{"producto_id": t.p1.id, "cantidad": 3}, {"producto_id": t.p2.id, "cantidad": 2, "descuento": "1"}],
        descuento="4", metodo_pago="tarjeta",
    )
    s.commit()
    # 3*10 + (2*5 - 1) = 39 de subtotal, menos 4 de descuento general
    assert (venta.subtotal, venta.descuento, venta.total) == (Decimal("39.00"), Decimal("4.00"), Decimal("35.00"))
    assert venta.vendedor_id == vendedor.id
    assert venta.numero == 1 and formatear_numero(venta.numero) == "V-000001"
    assert stock_actual(s, t.p1.id, t.principal.id) == 17
    assert stock_actual(s, t.p2.id, t.principal.id) == 3

    detalle = s.scalars(select(VentaDetalle).where(VentaDetalle.producto_id == t.p1.id)).one()
    assert (detalle.precio_unitario, detalle.costo_unitario) == (Decimal("10.00"), Decimal("4.00"))

    kardex_venta = s.scalars(
        select(MovimientoInventario).where(
            MovimientoInventario.referencia_tipo == "venta", MovimientoInventario.referencia_id == venta.id
        )
    ).all()
    assert sorted(m.cantidad for m in kardex_venta) == [-3, -2]
    assert all(m.tipo == "salida" and m.usuario_id == vendedor.id for m in kardex_venta)

    # un cambio de precio posterior no altera la venta ya hecha
    from app.servicios.catalogo import editar_producto

    editar_producto(s, administrador, t.p1.id, {"precio": "99"})
    s.commit()
    assert s.scalars(select(VentaDetalle).where(VentaDetalle.producto_id == t.p1.id)).one().precio_unitario == Decimal("10.00")
    assert verificar_consistencia(s) == []


def test_numeros_de_venta_son_consecutivos(sesion_servicios, administrador, t):
    a = vender(sesion_servicios, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    b = vender(sesion_servicios, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    assert (a.numero, b.numero) == (1, 2)


def test_cliente_no_puede_fijar_el_precio_ni_el_vendedor(sesion_servicios, administrador, t):
    venta = vender(
        sesion_servicios, administrador, t,
        [{"producto_id": t.p1.id, "cantidad": 1, "precio": "0.01", "precio_unitario": "0.01"}],
    )
    assert venta.total == Decimal("10.00")
    with pytest.raises(TypeError):
        registrar_venta(  # no existe el parámetro vendedor_id
            sesion_servicios, administrador, sucursal_id=t.principal.id, vendedor_id=999,
            lineas=[{"producto_id": t.p1.id, "cantidad": 1}], metodo_pago="efectivo",
        )


@pytest.mark.parametrize(
    "cambios",
    [
        {"metodo_pago": "cripto"},
        {"descuento": "-1"},
        {"descuento": "11"},  # mayor que el subtotal
        {"lineas": []},
        {"lineas": [{"producto_id": 1, "cantidad": 0}]},
        {"lineas": [{"producto_id": 1, "cantidad": -2}]},
        {"lineas": [{"producto_id": 1, "cantidad": 1.5}]},
        {"lineas": [{"producto_id": 1, "cantidad": 1, "descuento": "11"}]},
        {"lineas": [{"producto_id": 99999, "cantidad": 1}]},
        {"cliente_id": 99999},
    ],
)
def test_validaciones_rechazan_y_no_dejan_rastro(sesion_servicios, administrador, t, cambios):
    s = sesion_servicios
    datos = {"lineas": [{"producto_id": t.p1.id, "cantidad": 1}], "metodo_pago": "efectivo"}
    datos.update(cambios)
    if datos["lineas"] and datos["lineas"][0].get("producto_id") == 1:
        datos["lineas"][0]["producto_id"] = t.p1.id
    with pytest.raises(ErrorDeNegocio):
        registrar_venta(s, administrador, sucursal_id=t.principal.id, **datos)
    s.rollback()
    assert contar(s, Venta) == 0
    assert stock_actual(s, t.p1.id, t.principal.id) == 20


def test_sucursal_inexistente_se_rechaza(sesion_servicios, administrador, t):
    with pytest.raises(ErrorDeNegocio):
        registrar_venta(
            sesion_servicios, administrador, sucursal_id=9999,
            lineas=[{"producto_id": t.p1.id, "cantidad": 1}], metodo_pago="efectivo",
        )


def test_stock_insuficiente_rechaza_toda_la_venta_aunque_falle_una_linea_posterior(sesion_servicios, administrador, t):
    s = sesion_servicios
    with pytest.raises(ErrorDeNegocio, match="P2"):
        vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 5}, {"producto_id": t.p2.id, "cantidad": 6}])
    s.rollback()
    assert contar(s, Venta) == 0 and contar(s, VentaDetalle) == 0
    assert stock_actual(s, t.p1.id, t.principal.id) == 20  # la primera línea tampoco se descontó
    assert stock_actual(s, t.p2.id, t.principal.id) == 5
    assert verificar_consistencia(s) == []


def test_la_ultima_unidad_solo_se_vende_una_vez(sesion_servicios, administrador, t):
    s = sesion_servicios
    vender(s, administrador, t, [{"producto_id": t.p2.id, "cantidad": 4}])
    s.commit()
    vender(s, administrador, t, [{"producto_id": t.p2.id, "cantidad": 1}])
    s.commit()
    with pytest.raises(ErrorDeNegocio, match="Stock insuficiente"):
        vender(s, administrador, t, [{"producto_id": t.p2.id, "cantidad": 1}])
    s.rollback()
    assert stock_actual(s, t.p2.id, t.principal.id) == 0
    assert contar(s, Venta) == 2
    assert s.scalar(select(Existencia.cantidad).where(Existencia.producto_id == t.p2.id)) == 0


def test_producto_inactivo_no_se_vende_ni_aparece_en_busqueda(sesion_servicios, administrador, t):
    s = sesion_servicios
    establecer_activo(s, administrador, t.p1.id, False)
    s.commit()
    with pytest.raises(ErrorDeNegocio, match="desactivado"):
        vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    assert producto_para_venta(s, administrador, "111", t.principal.id) is None
    assert buscar_para_venta(s, administrador, "Producto", t.principal.id) == [
        {"id": t.p2.id, "sku": "P2", "nombre": "Producto 2", "precio": Decimal("5.00"), "es_servicio": False, "stock": 5}
    ]


def test_busqueda_por_codigo_de_barras_y_sku(sesion_servicios, administrador, t):
    s = sesion_servicios
    por_codigo = producto_para_venta(s, administrador, "111", t.principal.id)
    assert por_codigo["sku"] == "P1" and por_codigo["precio"] == Decimal("10.00") and por_codigo["stock"] == 20
    assert producto_para_venta(s, administrador, "p2", t.principal.id)["sku"] == "P2"
    assert producto_para_venta(s, administrador, "no-existe", t.principal.id) is None
    assert producto_para_venta(s, administrador, "  ", t.principal.id) is None


def test_clientes(sesion_servicios, administrador, t):
    s = sesion_servicios
    cliente = crear_cliente(s, administrador, "  Ana Pérez ", "555")
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}], cliente_id=cliente.id)
    assert [c["nombre"] for c in listar_clientes(s, administrador)] == ["Ana Pérez"]
    assert obtener_venta(s, administrador, venta.id)["cliente"] == "Ana Pérez"
    with pytest.raises(ErrorDeNegocio):
        crear_cliente(s, administrador, "   ")


def test_bodeguero_y_contador_no_pueden_vender(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    for rol in ("bodeguero", "contador"):
        with pytest.raises(PermisoDenegado):
            vender(s, crear_con_rol(rol), t, [{"producto_id": t.p1.id, "cantidad": 1}])
        s.rollback()
    assert contar(s, Venta) == 0


# ---- anulación -----------------------------------------------------------------------


def test_anular_devuelve_stock_y_registra_quien_cuando_y_por_que(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    venta = vender(s, vendedor, t, [{"producto_id": t.p1.id, "cantidad": 3}])
    s.commit()
    anular_venta(s, administrador, venta.id, "Error de captura")
    s.commit()

    assert venta.estado == "anulada"
    assert venta.anulada_por == administrador.id and venta.anulada_en is not None
    assert venta.motivo_anulacion == "Error de captura"
    assert stock_actual(s, t.p1.id, t.principal.id) == 20
    reversa = s.scalars(select(MovimientoInventario).where(MovimientoInventario.tipo == "anulacion")).one()
    assert reversa.cantidad == 3 and reversa.costo_unitario == Decimal("4.00") and reversa.usuario_id == administrador.id
    eventos = s.scalars(select(BitacoraAuditoria.accion).where(BitacoraAuditoria.accion.like("venta_%"))).all()
    assert sorted(eventos) == ["venta_anulada", "venta_registrada"]
    assert verificar_consistencia(s) == []


def test_no_se_anula_dos_veces_ni_sin_motivo(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}])
    s.commit()
    with pytest.raises(ErrorDeNegocio, match="motivo"):
        anular_venta(s, administrador, venta.id, "   ")
    anular_venta(s, administrador, venta.id, "Devolución")
    s.commit()
    with pytest.raises(ErrorDeNegocio, match="ya está anulada"):
        anular_venta(s, administrador, venta.id, "Otra vez")
    s.rollback()
    assert stock_actual(s, t.p1.id, t.principal.id) == 20  # no se devolvió dos veces
    with pytest.raises(ErrorDeNegocio, match="no existe"):
        anular_venta(s, administrador, 9999, "x")


def test_anular_exige_permiso(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    venta = vender(s, vendedor, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    s.commit()
    with pytest.raises(PermisoDenegado):
        anular_venta(s, vendedor, venta.id, "Me arrepentí")
    s.rollback()
    assert s.get(Venta, venta.id).estado == "completada"


# ---- consultas y alcance -------------------------------------------------------------


def test_vendedor_solo_ve_sus_ventas_y_el_contador_ve_todas(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    ana = crear_con_rol("vendedor")
    from app.servicios.usuarios import crear_usuario

    luis = crear_usuario(s, administrador, "Luis", "luis@x.com", "claveSegura1", "vendedor")
    contador = crear_con_rol("contador")
    mia = vender(s, ana, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    ajena = vender(s, luis, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    s.commit()

    assert [v["id"] for v in listar_ventas(s, ana)] == [mia.id]
    assert obtener_venta(s, ana, mia.id)["id"] == mia.id
    with pytest.raises(PermisoDenegado):
        obtener_venta(s, ana, ajena.id)
    # intentar filtrar por otro vendedor no amplía el alcance
    assert [v["id"] for v in listar_ventas(s, ana, vendedor_id=luis.id)] == [mia.id]

    assert {v["id"] for v in listar_ventas(s, contador)} == {mia.id, ajena.id}
    assert {v["id"] for v in listar_ventas(s, administrador)} == {mia.id, ajena.id}
    assert [v["id"] for v in listar_ventas(s, contador, vendedor_id=luis.id)] == [ajena.id]


def test_listar_filtra_por_estado_y_no_expone_costos(sesion_servicios, administrador, t):
    s = sesion_servicios
    a = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    b = vender(s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 1}])
    anular_venta(s, administrador, b.id, "Prueba")
    s.commit()
    assert [v["id"] for v in listar_ventas(s, administrador, estado="completada")] == [a.id]
    assert [v["id"] for v in listar_ventas(s, administrador, estado="anulada")] == [b.id]
    assert all("costo" not in k for k in obtener_venta(s, administrador, a.id)["lineas"][0])


def test_sin_permiso_de_ver_no_hay_historial(sesion_servicios, crear_con_rol):
    with pytest.raises(PermisoDenegado):
        listar_ventas(sesion_servicios, crear_con_rol("bodeguero"))


# ---- comprobante ---------------------------------------------------------------------


def test_comprobante_texto_y_html(sesion_servicios, administrador, t):
    s = sesion_servicios
    venta = vender(
        s, administrador, t, [{"producto_id": t.p1.id, "cantidad": 2}], descuento="2", nota="x",
    )
    s.commit()
    datos = obtener_venta(s, administrador, venta.id)
    texto = comprobante_texto(datos, "Mi Tienda")
    assert "V-000001" in texto and "Producto 1" in texto and "18.00" in texto and "Mi Tienda" in texto
    assert "ANULADA" not in texto

    datos["lineas"][0]["nombre"] = "<script>alert(1)</script>"
    html = comprobante_html(datos, "Tienda & Co")
    assert "<script>" not in html and "&lt;script&gt;" in html and "Tienda &amp; Co" in html

    anular_venta(s, administrador, venta.id, "Error")
    s.commit()
    anulada = obtener_venta(s, administrador, venta.id)
    assert "VENTA ANULADA" in comprobante_texto(anulada, "Mi Tienda")
    assert "VENTA ANULADA" in comprobante_html(anulada, "Mi Tienda")


def test_las_matrices_incluyen_los_permisos_de_ventas():
    assert MATRIZ_BASE["vendedor"]["ventas"] == ["ver", "crear"]
    assert "anular" not in MATRIZ_BASE["vendedor"]["ventas"]
    assert "ver_todas" in MATRIZ_BASE["contador"]["ventas"]


def test_catalogo_para_venta_lista_por_categoria_y_respeta_permiso(sesion_servicios, administrador, crear_con_rol):
    from app.servicios.catalogo import crear_categoria, crear_producto
    from app.servicios.errores import PermisoDenegado
    from app.servicios.inventario import crear_sucursal
    from app.servicios.ventas import catalogo_para_venta, categorias_para_venta

    s = sesion_servicios
    sucursal = crear_sucursal(s, administrador, "Cat Sucursal")
    c1 = crear_categoria(s, administrador, "CatUno")
    c2 = crear_categoria(s, administrador, "CatDos")
    crear_categoria(s, administrador, "CatVacia")
    crear_producto(s, administrador, sku="CAT-A", nombre="Alfombra", categoria_id=c1.id, precio="10", costo="4")
    crear_producto(s, administrador, sku="CAT-B", nombre="Brillo", categoria_id=c2.id, precio="5", costo="2")
    s.commit()

    todos = catalogo_para_venta(s, administrador, sucursal.id)
    assert [p["sku"] for p in todos] == ["CAT-A", "CAT-B"]
    assert [p["sku"] for p in catalogo_para_venta(s, administrador, sucursal.id, c2.id)] == ["CAT-B"]
    assert [c["nombre"] for c in categorias_para_venta(s, administrador)] == ["CatDos", "CatUno"]

    bodeguero = crear_con_rol("bodeguero")  # no tiene ventas.crear
    with pytest.raises(PermisoDenegado):
        catalogo_para_venta(s, bodeguero, sucursal.id)
