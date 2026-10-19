"""Modelos de cimientos: sucursales y configuración del sistema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Sucursal(Base):
    """Sucursal o bodega.

    Existe desde la Fase 0 porque el sistema es multi-sucursal: existencias,
    movimientos y ventas llevarán ``sucursal_id`` desde su primera migración.
    """

    __tablename__ = "sucursales"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    direccion: Mapped[str | None] = mapped_column(String(200))
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    creada_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Configuracion(Base):
    """Parámetros del sistema en formato clave-valor.

    Ejemplos previstos: ``permitir_stock_negativo``, ``metodo_costeo``.
    """

    __tablename__ = "configuracion"

    clave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[str | None] = mapped_column(String(200))
