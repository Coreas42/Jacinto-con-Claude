"""Pruebas de la Fase 1: usuarios, roles, permisos por módulo, login y bitácora."""

import pytest
from sqlalchemy import func, inspect, select

from app.db import crear_fabrica_sesiones
from app.modelos import BitacoraAuditoria, Permiso, Rol, Usuario
from app.servicios.auditoria import listar_bitacora
from app.servicios.autenticacion import cerrar_sesion, datos_de_sesion, iniciar_sesion
from app.servicios.errores import CredencialesInvalidas, ErrorDeNegocio, PermisoDenegado
from app.servicios.permisos import (
    CATALOGO,
    MATRIZ_BASE,
    exigir_permiso,
    modulos_permitidos,
    permisos_efectivos,
    sembrar_permisos_y_roles,
)
from app.servicios.seguridad import hashear_contrasena, verificar_contrasena
from app.servicios.usuarios import (
    cambiar_contrasena,
    cambiar_rol,
    crear_administrador_inicial,
    crear_usuario,
    establecer_activo,
    establecer_permiso_individual,
    listar_usuarios,
)

CLAVE = "claveSegura1"


@pytest.fixture()
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


@pytest.fixture()
def sesion(fabrica):
    s = fabrica()
    sembrar_permisos_y_roles(s)
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def admin(sesion):
    usuario = crear_administrador_inicial(sesion, "Admin", "admin@x.com", CLAVE)
    sesion.commit()
    return usuario


def nuevo(sesion, admin, rol, correo=None):
    usuario = crear_usuario(sesion, admin, f"Usuario {rol}", correo or f"{rol}@x.com", CLAVE, rol)
    sesion.commit()
    return usuario


def acciones_en_bitacora(sesion, accion):
    return sesion.scalar(
        select(func.count()).select_from(BitacoraAuditoria).where(BitacoraAuditoria.accion == accion)
    )


# ---- migración y datos base -------------------------------------------------------


def test_migracion_crea_tablas_de_seguridad(motor):
    tablas = set(inspect(motor).get_table_names())
    assert {
        "usuarios",
        "roles",
        "permisos",
        "roles_permisos",
        "usuarios_permisos",
        "bitacora_auditoria",
    } <= tablas


def test_sembrar_es_idempotente(sesion):
    antes = (
        sesion.scalar(select(func.count()).select_from(Permiso)),
        sesion.scalar(select(func.count()).select_from(Rol)),
    )
    sembrar_permisos_y_roles(sesion)
    sembrar_permisos_y_roles(sesion)
    sesion.commit()
    despues = (
        sesion.scalar(select(func.count()).select_from(Permiso)),
        sesion.scalar(select(func.count()).select_from(Rol)),
    )
    assert antes == despues
    assert despues[0] == sum(len(a) for a in CATALOGO.values())
    assert despues[1] == len(MATRIZ_BASE)


# ---- contraseñas ------------------------------------------------------------------


def test_la_contrasena_se_guarda_con_hash(admin):
    assert admin.hash_contrasena != CLAVE
    assert CLAVE not in admin.hash_contrasena
    assert verificar_contrasena(admin.hash_contrasena, CLAVE)
    assert not verificar_contrasena(admin.hash_contrasena, "otra-clave")


def test_contrasena_corta_se_rechaza():
    with pytest.raises(ErrorDeNegocio):
        hashear_contrasena("corta")


# ---- login y bitácora -------------------------------------------------------------


def test_login_correcto_registra_acceso_en_bitacora(sesion, admin):
    usuario = iniciar_sesion(sesion, " ADMIN@x.com ", CLAVE)
    sesion.commit()
    assert usuario.id == admin.id
    assert usuario.ultimo_acceso is not None
    assert acciones_en_bitacora(sesion, "login") == 1


def test_login_fallido_queda_registrado_y_no_revela_el_motivo(sesion, admin, fabrica):
    with pytest.raises(CredencialesInvalidas) as clave_mala:
        iniciar_sesion(sesion, "admin@x.com", "incorrecta1")
    with pytest.raises(CredencialesInvalidas) as sin_usuario:
        iniciar_sesion(sesion, "nadie@x.com", CLAVE)
    assert str(clave_mala.value) == str(sin_usuario.value)

    otra = fabrica()  # sesión nueva: el registro debe estar confirmado en la base
    assert acciones_en_bitacora(otra, "login_fallido") == 2
    otra.close()


def test_usuario_inactivo_no_puede_entrar(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    establecer_activo(sesion, admin, vendedor.id, False)
    sesion.commit()
    with pytest.raises(CredencialesInvalidas):
        iniciar_sesion(sesion, "vendedor@x.com", CLAVE)


def test_logout_queda_en_bitacora(sesion, admin):
    cerrar_sesion(sesion, admin.id)
    sesion.commit()
    assert acciones_en_bitacora(sesion, "logout") == 1


# ---- permisos por módulo (403) ----------------------------------------------------


def test_usuario_sin_permiso_recibe_403(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    with pytest.raises(PermisoDenegado) as error:
        crear_usuario(sesion, vendedor, "Otro", "otro@x.com", CLAVE, "vendedor")
    assert error.value.codigo_http == 403
    with pytest.raises(PermisoDenegado):
        exigir_permiso(sesion, vendedor, "bitacora", "ver")
    with pytest.raises(PermisoDenegado):
        listar_usuarios(sesion, vendedor)


def test_administrador_si_puede_crear_usuarios(sesion, admin):
    creado = crear_usuario(sesion, admin, "Nuevo", "nuevo@x.com", CLAVE, "bodeguero")
    assert creado.id is not None
    assert creado.rol.nombre == "bodeguero"


def test_el_menu_solo_muestra_modulos_permitidos(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    bodeguero = nuevo(sesion, admin, "bodeguero")
    contador = nuevo(sesion, admin, "contador")

    assert modulos_permitidos(sesion, admin) == list(CATALOGO)
    assert "usuarios" not in modulos_permitidos(sesion, vendedor)
    assert "bitacora" not in modulos_permitidos(sesion, vendedor)
    assert "ventas" in modulos_permitidos(sesion, vendedor)
    assert "ventas" not in modulos_permitidos(sesion, bodeguero)
    assert "inventario" in modulos_permitidos(sesion, bodeguero)
    assert "bitacora" in modulos_permitidos(sesion, contador)
    assert "usuarios" not in modulos_permitidos(sesion, contador)


def test_datos_de_sesion_reflejan_los_permisos(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    datos = datos_de_sesion(sesion, vendedor)
    assert datos.rol == "vendedor"
    assert datos.puede("ventas", "crear")
    assert not datos.puede("ventas", "anular")
    assert "usuarios" not in datos.modulos


def test_permiso_individual_concede_quita_y_restaura(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    assert ("usuarios", "ver") not in permisos_efectivos(sesion, vendedor)
    assert ("ventas", "crear") in permisos_efectivos(sesion, vendedor)

    establecer_permiso_individual(sesion, admin, vendedor.id, "usuarios", "ver", True)
    establecer_permiso_individual(sesion, admin, vendedor.id, "ventas", "crear", False)
    sesion.commit()
    efectivos = permisos_efectivos(sesion, vendedor)
    assert ("usuarios", "ver") in efectivos
    assert ("ventas", "crear") not in efectivos

    establecer_permiso_individual(sesion, admin, vendedor.id, "usuarios", "ver", None)
    establecer_permiso_individual(sesion, admin, vendedor.id, "ventas", "crear", None)
    sesion.commit()
    assert permisos_efectivos(sesion, vendedor) == permisos_efectivos(sesion, nuevo(sesion, admin, "vendedor", "v2@x.com"))
    assert acciones_en_bitacora(sesion, "permiso_individual_cambiado") == 4


def test_usuario_desactivado_pierde_todos_los_permisos(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    establecer_activo(sesion, admin, vendedor.id, False)
    assert permisos_efectivos(sesion, vendedor) == set()
    with pytest.raises(PermisoDenegado):
        exigir_permiso(sesion, vendedor, "ventas", "crear")


def test_no_se_puede_exigir_un_permiso_inexistente(sesion, admin):
    with pytest.raises(ErrorDeNegocio):
        exigir_permiso(sesion, admin, "ventas", "volar")


# ---- reglas de administración -----------------------------------------------------


def test_cambio_de_rol_queda_en_bitacora_con_antes_y_despues(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    cambiar_rol(sesion, admin, vendedor.id, "contador")
    sesion.commit()
    evento = sesion.scalars(
        select(BitacoraAuditoria).where(BitacoraAuditoria.accion == "rol_cambiado")
    ).one()
    assert evento.usuario_id == admin.id
    assert evento.detalle == {"anterior": "vendedor", "nuevo": "contador"}
    assert "bitacora" in modulos_permitidos(sesion, vendedor)


def test_el_administrador_no_puede_degradarse_ni_desactivarse(sesion, admin):
    with pytest.raises(ErrorDeNegocio):
        cambiar_rol(sesion, admin, admin.id, "vendedor")
    with pytest.raises(ErrorDeNegocio):
        establecer_activo(sesion, admin, admin.id, False)
    with pytest.raises(ErrorDeNegocio):
        establecer_permiso_individual(sesion, admin, admin.id, "ventas", "crear", False)


def test_correo_duplicado_se_rechaza(sesion, admin):
    nuevo(sesion, admin, "vendedor", "repetido@x.com")
    with pytest.raises(ErrorDeNegocio):
        crear_usuario(sesion, admin, "Otro", "REPETIDO@x.com", CLAVE, "vendedor")


def test_datos_invalidos_se_rechazan(sesion, admin):
    with pytest.raises(ErrorDeNegocio):
        crear_usuario(sesion, admin, "  ", "a@x.com", CLAVE, "vendedor")
    with pytest.raises(ErrorDeNegocio):
        crear_usuario(sesion, admin, "Ana", "sin-arroba", CLAVE, "vendedor")
    with pytest.raises(ErrorDeNegocio):
        crear_usuario(sesion, admin, "Ana", "ana@x.com", "corta", "vendedor")
    with pytest.raises(ErrorDeNegocio):
        crear_usuario(sesion, admin, "Ana", "ana@x.com", CLAVE, "rol-inexistente")


def test_cambiar_contrasena_exige_la_actual(sesion, admin):
    with pytest.raises(ErrorDeNegocio):
        cambiar_contrasena(sesion, admin.id, "equivocada1", "nuevaClave99")
    cambiar_contrasena(sesion, admin.id, CLAVE, "nuevaClave99")
    sesion.commit()
    assert verificar_contrasena(admin.hash_contrasena, "nuevaClave99")
    assert acciones_en_bitacora(sesion, "contrasena_cambiada") == 1


# ---- bitácora ---------------------------------------------------------------------


def test_solo_quien_tiene_permiso_ve_la_bitacora(sesion, admin):
    vendedor = nuevo(sesion, admin, "vendedor")
    contador = nuevo(sesion, admin, "contador")
    with pytest.raises(PermisoDenegado):
        listar_bitacora(sesion, vendedor)
    eventos = listar_bitacora(sesion, contador)
    assert eventos
    assert eventos[0]["id"] > eventos[-1]["id"]  # más recientes primero
    assert {e["accion"] for e in eventos} >= {"usuario_creado"}


def test_la_creacion_de_usuarios_queda_en_bitacora(sesion, admin):
    nuevo(sesion, admin, "vendedor")
    creaciones = sesion.scalars(
        select(BitacoraAuditoria)
        .where(BitacoraAuditoria.accion == "usuario_creado")
        .order_by(BitacoraAuditoria.id)
    ).all()
    assert len(creaciones) == 2  # el administrador inicial y el vendedor
    assert creaciones[-1].usuario_id == admin.id
    assert creaciones[-1].detalle["rol"] == "vendedor"


def test_listar_usuarios_devuelve_rol_y_estado(sesion, admin):
    nuevo(sesion, admin, "bodeguero")
    filas = listar_usuarios(sesion, admin)
    por_correo = {f["correo"]: f for f in filas}
    assert por_correo["bodeguero@x.com"]["rol"] == "bodeguero"
    assert por_correo["admin@x.com"]["activo"] is True
    assert isinstance(sesion.get(Usuario, admin.id), Usuario)
