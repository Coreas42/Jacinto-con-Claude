"""Inicio y cierre de sesión."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ahora_utc
from app.modelos import BitacoraAuditoria, Usuario
from app.servicios.auditoria import registrar
from app.servicios.errores import CredencialesInvalidas, ErrorDeNegocio
from app.servicios.permisos import CATALOGO, permisos_efectivos
from app.servicios.seguridad import verificar_contra_hash_falso, verificar_contrasena


@dataclass(frozen=True)
class SesionUsuario:
    """Datos del usuario autenticado que la interfaz guarda mientras dura la sesión."""

    id: int
    nombre: str
    correo: str
    rol: str
    permisos: frozenset[tuple[str, str]]

    @property
    def modulos(self) -> list[str]:
        con_permiso = {modulo for modulo, _ in self.permisos}
        return [modulo for modulo in CATALOGO if modulo in con_permiso]

    def puede(self, modulo: str, accion: str) -> bool:
        return (modulo, accion) in self.permisos


INTENTOS_MAXIMOS = 5
VENTANA_DE_BLOQUEO = timedelta(minutes=15)


def _intentos_recientes(sesion: Session, correo: str) -> int:
    """Intentos fallidos con este correo en la ventana de bloqueo, sin contar los previos a un acceso correcto.

    Se aplica igual a correos que no existen, para no revelar cuáles están registrados.
    """
    desde = ahora_utc() - VENTANA_DE_BLOQUEO
    filas = sesion.execute(
        select(BitacoraAuditoria.accion, BitacoraAuditoria.detalle, BitacoraAuditoria.usuario_id)
        .where(BitacoraAuditoria.accion.in_(("login_fallido", "login")), BitacoraAuditoria.creado_en >= desde)
        .order_by(BitacoraAuditoria.id.desc())
    )
    usuario_id = sesion.scalar(select(Usuario.id).where(Usuario.correo == correo))
    intentos = 0
    for accion, detalle, uid in filas:
        if accion == "login" and usuario_id is not None and uid == usuario_id:
            break  # un acceso correcto reinicia la cuenta
        if accion == "login_fallido" and (detalle or {}).get("correo") == correo:
            intentos += 1
    return intentos


def iniciar_sesion(sesion: Session, correo: str, clave: str, ip: str | None = None) -> Usuario:
    """Valida credenciales y registra el intento en la bitácora.

    Un intento fallido se confirma (commit) antes de lanzar el error, para que
    quede en la bitácora aunque la operación que lo llamó haga rollback.
    """
    correo = correo.strip().lower()
    if _intentos_recientes(sesion, correo) >= INTENTOS_MAXIMOS:
        registrar(sesion, "login_bloqueado", detalle={"correo": correo}, ip=ip)
        sesion.commit()
        raise ErrorDeNegocio(
            f"Demasiados intentos fallidos. Espera {int(VENTANA_DE_BLOQUEO.total_seconds() // 60)} minutos "
            "y vuelve a intentar."
        )
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo))

    if usuario is None:
        verificar_contra_hash_falso(clave)
        valido = False
    else:
        valido = verificar_contrasena(usuario.hash_contrasena, clave) and usuario.activo

    if not valido:
        registrar(
            sesion,
            "login_fallido",
            usuario_id=usuario.id if usuario else None,
            detalle={"correo": correo},
            ip=ip,
        )
        sesion.commit()
        raise CredencialesInvalidas()

    usuario.ultimo_acceso = ahora_utc()
    registrar(sesion, "login", usuario_id=usuario.id, entidad="usuarios", entidad_id=usuario.id, ip=ip)
    sesion.flush()
    return usuario


def cerrar_sesion(sesion: Session, usuario_id: int, ip: str | None = None) -> None:
    registrar(sesion, "logout", usuario_id=usuario_id, entidad="usuarios", entidad_id=usuario_id, ip=ip)


def datos_de_sesion(sesion: Session, usuario: Usuario) -> SesionUsuario:
    return SesionUsuario(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.correo,
        rol=usuario.rol.nombre,
        permisos=frozenset(permisos_efectivos(sesion, usuario)),
    )
