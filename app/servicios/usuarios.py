"""Administración de usuarios, roles y permisos individuales.

Cada función recibe ``actor`` (quien la ejecuta), verifica su permiso y deja
constancia en la bitácora dentro de la misma transacción.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.modelos import Permiso, Rol, Usuario, UsuarioPermiso
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import (
    exigir_permiso,
    permisos_del_rol,
    permisos_individuales,
)
from app.servicios.seguridad import (
    hashear_contrasena,
    validar_contrasena,
    verificar_contrasena,
)


def obtener_usuario(sesion: Session, usuario_id: int) -> Usuario:
    usuario = sesion.get(Usuario, usuario_id)
    if usuario is None:
        raise ErrorDeNegocio("El usuario no existe.")
    return usuario


def _obtener_rol(sesion: Session, nombre: str) -> Rol:
    rol = sesion.scalar(select(Rol).where(Rol.nombre == nombre))
    if rol is None:
        raise ErrorDeNegocio(f"El rol '{nombre}' no existe.")
    return rol


def _validar_datos(nombre: str, correo: str) -> tuple[str, str]:
    nombre = nombre.strip()
    correo = correo.strip().lower()
    if not nombre:
        raise ErrorDeNegocio("El nombre es obligatorio.")
    if "@" not in correo or correo.startswith("@") or correo.endswith("@"):
        raise ErrorDeNegocio("El correo no es válido.")
    return nombre, correo


def _crear(sesion: Session, nombre: str, correo: str, clave: str, rol: Rol) -> Usuario:
    nombre, correo = _validar_datos(nombre, correo)
    if sesion.scalar(select(Usuario.id).where(Usuario.correo == correo)) is not None:
        raise ErrorDeNegocio("Ya existe un usuario con ese correo.")
    usuario = Usuario(
        nombre=nombre,
        correo=correo,
        hash_contrasena=hashear_contrasena(clave),
        rol_id=rol.id,
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario


def crear_administrador_inicial(sesion: Session, nombre: str, correo: str, clave: str) -> Usuario:
    """Primer administrador (lo usa ``seed.py``). No exige actor porque aún no hay usuarios."""
    rol = _obtener_rol(sesion, "administrador")
    usuario = _crear(sesion, nombre, correo, clave, rol)
    registrar(
        sesion,
        "usuario_creado",
        entidad="usuarios",
        entidad_id=usuario.id,
        detalle={"correo": usuario.correo, "rol": rol.nombre, "inicial": True},
    )
    return usuario


def crear_usuario(
    sesion: Session, actor: Usuario, nombre: str, correo: str, clave: str, rol_nombre: str
) -> Usuario:
    exigir_permiso(sesion, actor, "usuarios", "crear")
    rol = _obtener_rol(sesion, rol_nombre)
    usuario = _crear(sesion, nombre, correo, clave, rol)
    registrar(
        sesion,
        "usuario_creado",
        usuario_id=actor.id,
        entidad="usuarios",
        entidad_id=usuario.id,
        detalle={"correo": usuario.correo, "rol": rol.nombre},
    )
    return usuario


def cambiar_rol(sesion: Session, actor: Usuario, usuario_id: int, rol_nombre: str) -> None:
    exigir_permiso(sesion, actor, "usuarios", "editar")
    if usuario_id == actor.id:
        raise ErrorDeNegocio("No puedes cambiar tu propio rol.")
    usuario = obtener_usuario(sesion, usuario_id)
    rol = _obtener_rol(sesion, rol_nombre)
    anterior = usuario.rol.nombre
    if anterior == rol.nombre:
        return
    usuario.rol_id = rol.id
    sesion.flush()
    sesion.refresh(usuario)
    registrar(
        sesion,
        "rol_cambiado",
        usuario_id=actor.id,
        entidad="usuarios",
        entidad_id=usuario.id,
        detalle={"anterior": anterior, "nuevo": rol.nombre},
    )


def establecer_activo(sesion: Session, actor: Usuario, usuario_id: int, activo: bool) -> None:
    exigir_permiso(sesion, actor, "usuarios", "editar")
    if usuario_id == actor.id and not activo:
        raise ErrorDeNegocio("No puedes desactivar tu propio usuario.")
    usuario = obtener_usuario(sesion, usuario_id)
    if usuario.activo == activo:
        return
    usuario.activo = activo
    registrar(
        sesion,
        "usuario_activado" if activo else "usuario_desactivado",
        usuario_id=actor.id,
        entidad="usuarios",
        entidad_id=usuario.id,
    )


def establecer_permiso_individual(
    sesion: Session,
    actor: Usuario,
    usuario_id: int,
    modulo: str,
    accion: str,
    concedido: bool | None,
) -> None:
    """``True`` concede, ``False`` quita y ``None`` vuelve a lo que diga el rol."""
    exigir_permiso(sesion, actor, "usuarios", "editar")
    if usuario_id == actor.id:
        raise ErrorDeNegocio("No puedes modificar tus propios permisos.")
    obtener_usuario(sesion, usuario_id)
    permiso = sesion.scalar(
        select(Permiso).where(Permiso.modulo == modulo, Permiso.accion == accion)
    )
    if permiso is None:
        raise ErrorDeNegocio(f"Permiso desconocido: {modulo}.{accion}")

    fila = sesion.get(UsuarioPermiso, (usuario_id, permiso.id))
    anterior = None if fila is None else fila.concedido
    if anterior == concedido:
        return

    if concedido is None:
        sesion.delete(fila)
    elif fila is None:
        sesion.add(UsuarioPermiso(usuario_id=usuario_id, permiso_id=permiso.id, concedido=concedido))
    else:
        fila.concedido = concedido
    sesion.flush()
    registrar(
        sesion,
        "permiso_individual_cambiado",
        usuario_id=actor.id,
        entidad="usuarios",
        entidad_id=usuario_id,
        detalle={"permiso": f"{modulo}.{accion}", "anterior": anterior, "nuevo": concedido},
    )


def cambiar_contrasena(sesion: Session, usuario_id: int, clave_actual: str, clave_nueva: str) -> None:
    """Cada usuario cambia la suya; no requiere permiso especial."""
    usuario = obtener_usuario(sesion, usuario_id)
    if not verificar_contrasena(usuario.hash_contrasena, clave_actual):
        raise ErrorDeNegocio("La contraseña actual no es correcta.")
    validar_contrasena(clave_nueva)
    usuario.hash_contrasena = hashear_contrasena(clave_nueva)
    registrar(sesion, "contrasena_cambiada", usuario_id=usuario.id, entidad="usuarios", entidad_id=usuario.id)


def restablecer_contrasena(sesion: Session, actor: Usuario, usuario_id: int, clave_nueva: str) -> None:
    exigir_permiso(sesion, actor, "usuarios", "editar")
    usuario = obtener_usuario(sesion, usuario_id)
    usuario.hash_contrasena = hashear_contrasena(clave_nueva)
    registrar(
        sesion,
        "contrasena_restablecida",
        usuario_id=actor.id,
        entidad="usuarios",
        entidad_id=usuario.id,
    )


def listar_roles(sesion: Session) -> list[str]:
    return list(sesion.scalars(select(Rol.nombre).order_by(Rol.id)))


def listar_usuarios(sesion: Session, actor: Usuario) -> list[dict]:
    exigir_permiso(sesion, actor, "usuarios", "ver")
    usuarios = sesion.scalars(
        select(Usuario).options(joinedload(Usuario.rol)).order_by(Usuario.nombre)
    ).all()
    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "correo": u.correo,
            "rol": u.rol.nombre,
            "activo": u.activo,
            "ultimo_acceso": u.ultimo_acceso,
        }
        for u in usuarios
    ]


def detalle_permisos(sesion: Session, actor: Usuario, usuario_id: int) -> dict:
    """Permisos que da el rol y excepciones individuales de un usuario."""
    exigir_permiso(sesion, actor, "usuarios", "ver")
    usuario = obtener_usuario(sesion, usuario_id)
    return {
        "rol": permisos_del_rol(sesion, usuario.rol_id),
        "individuales": permisos_individuales(sesion, usuario.id),
    }
