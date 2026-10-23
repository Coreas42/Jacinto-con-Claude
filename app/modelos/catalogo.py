"""Modelos del catálogo: categorías, productos e historial de cambios.

El producto NO tiene columna de existencias: el stock vive en ``existencias`` y
solo cambia mediante movimientos de inventario (Fase 3).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True)
    codigo_barras: Mapped[str | None] = mapped_column(String(50), unique=True)
    nombre: Mapped[str] = mapped_column(String(150))
    descripcion: Mapped[str | None] = mapped_column(String(500))
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    marca: Mapped[str | None] = mapped_column(String(80))
    costo_promedio: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), server_default="0"
    )
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    stock_minimo: Mapped[int] = mapped_column(default=0, server_default="0")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Servicio (polarizado, instalación...): se vende sin controlar existencias.
    es_servicio: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    categoria: Mapped[Categoria] = relationship()


class HistorialProducto(Base):
    """Cambios de precio, costo y otros datos clave. Solo se agregan filas."""

    __tablename__ = "historial_productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    campo: Mapped[str] = mapped_column(String(30))
    valor_anterior: Mapped[str | None] = mapped_column(String(100))
    valor_nuevo: Mapped[str | None] = mapped_column(String(100))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
