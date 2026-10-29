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


class CapaCosto(Base):
    """Lote de costo (capa PEPS): unidades que entraron a un mismo costo y aún no se han consumido.

    Se mantiene SIEMPRE, sin importar el método de costeo elegido, así cambiar de método es inmediato.
    Las salidas consumen primero la capa más antigua. La suma de ``cantidad_restante`` de un producto en
    una sucursal debe ser igual a su existencia (``verificar_consistencia`` lo comprueba).
    """

    __tablename__ = "capas_costo"
    __table_args__ = (
        CheckConstraint("cantidad_restante >= 0", name="restante_no_negativo"),
        CheckConstraint("cantidad_restante <= cantidad_inicial", name="restante_no_mayor_que_inicial"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    cantidad_inicial: Mapped[int]
    cantidad_restante: Mapped[int]
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    creada_en: Mapped[datetime] = mapped_column(DateTime)  # define el orden de consumo
    origen_tipo: Mapped[str | None] = mapped_column(String(30))
    origen_id: Mapped[int | None] = mapped_column()


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


class CapaCosto(Base):
    """Lote de unidades con su costo de entrada (para costear por PEPS).

    Cada entrada de stock (compra, ajuste positivo, devolución, traslado recibido) crea una capa;
    cada salida consume las capas más antiguas primero. Se mantienen siempre, sea cual sea el
    método de costeo elegido, para poder cambiar de método sin perder información.
    """

    __tablename__ = "capas_costo"
    __table_args__ = (
        CheckConstraint("cantidad_inicial > 0", name="cantidad_inicial_positiva"),
        CheckConstraint("cantidad_restante >= 0", name="cantidad_restante_no_negativa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    cantidad_inicial: Mapped[int]
    cantidad_restante: Mapped[int]
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    origen: Mapped[str] = mapped_column(String(20))  # inicial, entrada, ajuste, devolucion, anulacion, traslado_entrada
    referencia_tipo: Mapped[str | None] = mapped_column(String(20))
    referencia_id: Mapped[int | None]
    creada_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
