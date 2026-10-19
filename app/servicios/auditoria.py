"""Bitácora de auditoría: quién hizo qué y cuándo. Solo se agregan registros."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos import BitacoraAuditoria, Usuario
from app.servicios.permisos import exigir_permiso


def registrar(
    sesion: Session,
    accion: str,
    *,
    usuario_id: int | None = None,
    entidad: str | None = None,
    entidad_id: int | None = None,
    detalle: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Agrega un evento en la misma transacción que la operación auditada."""
    sesion.add(
        BitacoraAuditoria(
            usuario_id=usuario_id,
            accion=accion,
            entidad=entidad,
            entidad_id=entidad_id,
            detalle=detalle,
            ip=ip,
        )
    )


def listar_bitacora(sesion: Session, actor: Usuario, limite: int = 200) -> list[dict]:
    """Eventos más recientes primero. Exige permiso ``bitacora.ver``."""
    exigir_permiso(sesion, actor, "bitacora", "ver")
    filas = sesion.execute(
        select(BitacoraAuditoria, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == BitacoraAuditoria.usuario_id)
        .order_by(BitacoraAuditoria.id.desc())
        .limit(limite)
    ).all()
    return [
        {
            "id": evento.id,
            "fecha": evento.creado_en,
            "usuario": nombre or "—",
            "accion": evento.accion,
            "entidad": evento.entidad,
            "entidad_id": evento.entidad_id,
            "detalle": evento.detalle,
        }
        for evento, nombre in filas
    ]
