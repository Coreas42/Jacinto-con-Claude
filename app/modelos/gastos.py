"""Gastos del negocio (alquiler, servicios, salarios...). Un gasto no se borra: se anula con motivo."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Gasto(Base):
    __tablename__ = "gastos"
    __table_args__ = (CheckConstraint("monto > 0", name="monto_positivo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)  # día del calendario local en que ocurrió
    categoria: Mapped[str] = mapped_column(String(30))
    descripcion: Mapped[str] = mapped_column(String(200))
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"))  # vacío = gasto general
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    estado: Mapped[str] = mapped_column(String(20), default="activo", server_default="activo")
    anulado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_anulacion: Mapped[str | None] = mapped_column(String(200))
