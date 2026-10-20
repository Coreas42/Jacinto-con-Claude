"""Modelos de inventario: proveedores, existencias, kardex, compras y traslados.

Regla central: ``existencias`` solo se modifica desde
``app.servicios.inventario.aplicar_movimiento``, que escribe en la misma
transacción el movimiento correspondiente en ``movimientos_inventario``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    contacto: Mapped[str | None] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Existencia(Base):
    """Cantidad actual de un producto en una sucursal. Nunca negativa."""

    __tablename__ = "existencias"
    __table_args__ = (CheckConstraint("cantidad >= 0", name="cantidad_no_negativa"),)

    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"), primary_key=True)
    cantidad: Mapped[int] = mapped_column(default=0, server_default="0")


class MovimientoInventario(Base):
    """Kardex. ``cantidad`` lleva signo (+ entra, - sale) y nunca se actualiza ni se borra."""

    __tablename__ = "movimientos_inventario"
    __table_args__ = (CheckConstraint("cantidad <> 0", name="cantidad_distinta_de_cero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    tipo: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[int]
    saldo_despues: Mapped[int]
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    motivo: Mapped[str | None] = mapped_column(String(200))
    referencia_tipo: Mapped[str | None] = mapped_column(String(30))
    referencia_id: Mapped[int | None] = mapped_column()
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Compra(Base):
    __tablename__ = "compras"

    id: Mapped[int] = mapped_column(primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    nota: Mapped[str | None] = mapped_column(String(200))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    estado: Mapped[str] = mapped_column(String(20), default="completada", server_default="completada")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompraDetalle(Base):
    __tablename__ = "compras_detalle"

    id: Mapped[int] = mapped_column(primary_key=True)
    compra_id: Mapped[int] = mapped_column(ForeignKey("compras.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int]
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Traslado(Base):
    """Movimiento de un producto entre dos sucursales (genera dos movimientos de kardex)."""

    __tablename__ = "traslados"
    __table_args__ = (CheckConstraint("origen_id <> destino_id", name="origen_distinto_de_destino"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int]
    origen_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    destino_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    nota: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
