"""Modelos de ventas: clientes, ventas y su detalle.

Una venta nunca se borra: se anula (con motivo, usuario y fecha) y su stock se
revierte con movimientos de kardex. El detalle congela el precio cobrado y el
costo vigente al vender, para que los reportes de utilidad no cambien después.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    telefono: Mapped[str | None] = mapped_column(String(30))
    correo: Mapped[str | None] = mapped_column(String(150))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Venta(Base):
    __tablename__ = "ventas"
    __table_args__ = (
        CheckConstraint("total >= 0", name="total_no_negativo"),
        CheckConstraint("descuento >= 0", name="descuento_no_negativo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(unique=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    # Se toma siempre de la sesión autenticada; no existe forma de elegirlo.
    vendedor_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    metodo_pago: Mapped[str] = mapped_column(String(20))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    estado: Mapped[str] = mapped_column(String(20), default="completada", server_default="completada")
    nota: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    anulada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_anulacion: Mapped[str | None] = mapped_column(String(200))


class VentaDetalle(Base):
    __tablename__ = "ventas_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="cantidad_positiva"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[int]
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # congelado al vender
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # congelado al vender
    descuento_linea: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")


class PagoVenta(Base):
    """Cómo se pagó una venta. Una venta puede tener varias formas de pago (pago mixto).

    ``monto`` es lo que se aplica a la venta; ``recibido`` (solo efectivo) es lo que entregó el
    cliente, y el cambio es ``recibido - monto``.
    """

    __tablename__ = "ventas_pagos"
    __table_args__ = (CheckConstraint("monto >= 0", name="monto_no_negativo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    metodo: Mapped[str] = mapped_column(String(20))
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    recibido: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class Devolucion(Base):
    """Devolución parcial o total de una venta completada. Nunca se borra."""

    __tablename__ = "devoluciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    motivo: Mapped[str] = mapped_column(String(200))
    metodo_reembolso: Mapped[str] = mapped_column(String(20))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DevolucionDetalle(Base):
    __tablename__ = "devoluciones_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="cantidad_devuelta_positiva"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    devolucion_id: Mapped[int] = mapped_column(ForeignKey("devoluciones.id"), index=True)
    detalle_id: Mapped[int] = mapped_column(ForeignKey("ventas_detalle.id"), index=True)
    cantidad: Mapped[int]
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # lo reembolsado por estas unidades
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # el costo congelado de la venta
