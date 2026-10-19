"""Modelos de seguridad: usuarios, roles, permisos y bitácora de auditoría."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

roles_permisos = Table(
    "roles_permisos",
    Base.metadata,
    Column("rol_id", ForeignKey("roles.id"), primary_key=True),
    Column("permiso_id", ForeignKey("permisos.id"), primary_key=True),
)


class Rol(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(200))

    permisos: Mapped[list["Permiso"]] = relationship(secondary=roles_permisos)


class Permiso(Base):
    """Una acción posible sobre un módulo (por ejemplo ``ventas`` + ``anular``)."""

    __tablename__ = "permisos"
    __table_args__ = (UniqueConstraint("modulo", "accion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(50))
    accion: Mapped[str] = mapped_column(String(30))


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    correo: Mapped[str] = mapped_column(String(150), unique=True)
    hash_contrasena: Mapped[str] = mapped_column(String(255))
    rol_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)

    rol: Mapped[Rol] = relationship()


class UsuarioPermiso(Base):
    """Excepción individual sobre el rol: concede (True) o quita (False) un permiso."""

    __tablename__ = "usuarios_permisos"

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    permiso_id: Mapped[int] = mapped_column(ForeignKey("permisos.id"), primary_key=True)
    concedido: Mapped[bool] = mapped_column(Boolean)


class BitacoraAuditoria(Base):
    """Registro de eventos sensibles. Nunca se actualiza ni se borra."""

    __tablename__ = "bitacora_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str] = mapped_column(String(60))
    entidad: Mapped[str | None] = mapped_column(String(60))
    entidad_id: Mapped[int | None] = mapped_column()
    detalle: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(45))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
