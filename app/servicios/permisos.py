"""Catálogo de permisos, matriz base por rol y comprobación centralizada.

``exigir_permiso`` es la única puerta de autorización: toda función de servicio
que haga algo sensible la llama primero. La interfaz puede ocultar botones, pero
la seguridad real está aquí.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import Permiso, Rol, Usuario, UsuarioPermiso, roles_permisos
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado

# módulo -> acciones posibles
CATALOGO: dict[str, list[str]] = {
    "usuarios": ["ver", "crear", "editar"],
    # "precios": cambiar precio o costo (más sensible que editar nombre o stock mínimo)
    "productos": ["ver", "crear", "editar", "precios"],
    "inventario": ["ver", "crear", "editar", "anular", "exportar"],
    # "ver" = solo las ventas propias; "ver_todas" = las de todos los vendedores.
    "ventas": ["ver", "ver_todas", "crear", "anular"],
    "reportes": ["ver", "exportar"],
    "gastos": ["ver", "crear", "anular"],
    "bitacora": ["ver"],
}

NOMBRES_MODULOS = {
    "usuarios": "Usuarios",
    "productos": "Productos",
    "inventario": "Inventario y compras",
    "ventas": "Ventas",
    "reportes": "Reportes",
    "gastos": "Gastos",
    "bitacora": "Bitácora",
}

DESCRIPCION_ROLES = {
    "administrador": "Acceso total, usuarios y permisos",
    "bodeguero": "Inventario, compras y ajustes",
    "vendedor": "Ventas y consulta de productos",
    "contador": "Reportes, utilidad y exportaciones",
}

# rol -> módulo -> acciones. Es el punto de partida; cada usuario puede tener
# excepciones individuales (tabla usuarios_permisos).
# Nota: "vendedor ve solo sus propias ventas" se aplica en la Fase 4/5 al consultar datos.
MATRIZ_BASE: dict[str, dict[str, list[str]]] = {
    "administrador": {modulo: list(acciones) for modulo, acciones in CATALOGO.items()},
    "vendedor": {
        "productos": ["ver"],
        "inventario": ["ver"],
        "ventas": ["ver", "crear"],
        "reportes": ["ver"],
    },
    "bodeguero": {
        "productos": ["ver", "editar"],
        "inventario": ["ver", "crear", "editar", "anular", "exportar"],
        "reportes": ["ver"],
    },
    "contador": {
        "productos": ["ver"],
        "inventario": ["ver"],
        "ventas": ["ver", "ver_todas"],
        "reportes": ["ver", "exportar"],
        "gastos": ["ver", "crear", "anular"],
        "bitacora": ["ver"],
    },
}


def sembrar_permisos_y_roles(sesion: Session) -> None:
    """Crea los permisos y roles base. Se puede ejecutar varias veces sin duplicar.

    Los roles ya existentes conservan los cambios hechos por el administrador;
    solo reciben los permisos que aparecen por primera vez (según la matriz base) y
    el rol ``administrador`` se sincroniza con todo el catálogo.
    """
    existentes = {(p.modulo, p.accion): p for p in sesion.scalars(select(Permiso))}
    nuevos: set[tuple[str, str]] = set()
    for modulo, acciones in CATALOGO.items():
        for accion in acciones:
            if (modulo, accion) not in existentes:
                permiso = Permiso(modulo=modulo, accion=accion)
                sesion.add(permiso)
                existentes[(modulo, accion)] = permiso
                nuevos.add((modulo, accion))
    sesion.flush()

    roles = {r.nombre: r for r in sesion.scalars(select(Rol))}
    for nombre, matriz in MATRIZ_BASE.items():
        rol = roles.get(nombre)
        if rol is None:
            rol = Rol(nombre=nombre, descripcion=DESCRIPCION_ROLES[nombre])
            rol.permisos = [
                existentes[(modulo, accion)]
                for modulo, acciones in matriz.items()
                for accion in acciones
            ]
            sesion.add(rol)
        elif nombre == "administrador":
            rol.permisos = list(existentes.values())
        elif nuevos:
            # Actualización de una instalación existente: los permisos que aparecen por
            # primera vez se agregan a los roles según la matriz base, sin quitar nada
            # de lo que el administrador haya personalizado.
            actuales = {(p.modulo, p.accion) for p in rol.permisos}
            for modulo, acciones in matriz.items():
                for accion in acciones:
                    if (modulo, accion) in nuevos and (modulo, accion) not in actuales:
                        rol.permisos.append(existentes[(modulo, accion)])
    sesion.flush()


def permisos_del_rol(sesion: Session, rol_id: int) -> set[tuple[str, str]]:
    filas = sesion.execute(
        select(Permiso.modulo, Permiso.accion)
        .join(roles_permisos, roles_permisos.c.permiso_id == Permiso.id)
        .where(roles_permisos.c.rol_id == rol_id)
    )
    return {(modulo, accion) for modulo, accion in filas}


def permisos_individuales(sesion: Session, usuario_id: int) -> dict[tuple[str, str], bool]:
    filas = sesion.execute(
        select(Permiso.modulo, Permiso.accion, UsuarioPermiso.concedido)
        .join(UsuarioPermiso, UsuarioPermiso.permiso_id == Permiso.id)
        .where(UsuarioPermiso.usuario_id == usuario_id)
    )
    return {(modulo, accion): concedido for modulo, accion, concedido in filas}


def permisos_efectivos(sesion: Session, usuario: Usuario) -> set[tuple[str, str]]:
    """Permisos del rol, más los concedidos y menos los denegados a este usuario.

    Un usuario inactivo no tiene ningún permiso.
    """
    if not usuario.activo:
        return set()
    efectivos = permisos_del_rol(sesion, usuario.rol_id)
    for permiso, concedido in permisos_individuales(sesion, usuario.id).items():
        if concedido:
            efectivos.add(permiso)
        else:
            efectivos.discard(permiso)
    return efectivos


# Quien tenga alguno de estos permisos necesita conocer los costos para trabajar: el contador y el
# administrador (utilidad), quien cambia precios y costos, y quien registra compras (bodeguero).
# El vendedor/cajero no los ve: vender no requiere conocer el margen.
PERMISOS_QUE_VEN_COSTOS = (("ventas", "ver_todas"), ("productos", "precios"), ("inventario", "crear"))


def puede_ver_costos(sesion: Session, usuario: Usuario) -> bool:
    efectivos = permisos_efectivos(sesion, usuario)
    return any(permiso in efectivos for permiso in PERMISOS_QUE_VEN_COSTOS)


def tiene_permiso(sesion: Session, usuario: Usuario, modulo: str, accion: str) -> bool:
    return (modulo, accion) in permisos_efectivos(sesion, usuario)


def exigir_permiso(sesion: Session, usuario: Usuario, modulo: str, accion: str) -> None:
    """Lanza ``PermisoDenegado`` (403) si el usuario no puede hacer la acción."""
    if modulo not in CATALOGO or accion not in CATALOGO[modulo]:
        raise ErrorDeNegocio(f"Permiso desconocido: {modulo}.{accion}")
    if not tiene_permiso(sesion, usuario, modulo, accion):
        raise PermisoDenegado(modulo, accion)


def modulos_permitidos(sesion: Session, usuario: Usuario) -> list[str]:
    """Módulos que el usuario puede ver en el menú (los que tienen algún permiso)."""
    con_permiso = {modulo for modulo, _ in permisos_efectivos(sesion, usuario)}
    return [modulo for modulo in CATALOGO if modulo in con_permiso]
