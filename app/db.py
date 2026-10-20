"""Conexión a la base de datos (SQLAlchemy 2)."""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import cargar_configuracion

# SQLite guarda Numeric como número decimal; con 2 decimales es exacto para dinero,
# así que se silencia el aviso informativo de SQLAlchemy.
warnings.filterwarnings("ignore", message=r".*does \*not\* support Decimal objects natively.*", category=SAWarning)

# Convención de nombres para que Alembic genere restricciones estables.
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base de todos los modelos."""

    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


def ahora_utc() -> datetime:
    """Fecha y hora UTC sin zona (como las guarda la base de datos)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def crear_motor(url: str | None = None) -> Engine:
    """Crea el motor de base de datos.

    En SQLite se activan las llaves foráneas, que vienen desactivadas por defecto.
    """
    configuracion = cargar_configuracion()
    url = url or configuracion.database_url
    motor = create_engine(url, echo=configuracion.sql_debug, future=True)

    if motor.dialect.name == "sqlite":

        @event.listens_for(motor, "connect")
        def _preparar_conexion(conexion, _registro):  # pragma: no cover
            # pysqlite no emite BEGIN por su cuenta de forma fiable: se desactiva y se
            # emite a mano (receta oficial de SQLAlchemy). Así los SAVEPOINT y los
            # rollback parciales de los servicios funcionan correctamente.
            conexion.isolation_level = None
            cursor = conexion.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(motor, "begin")
        def _comenzar_transaccion(conexion):  # pragma: no cover
            conexion.exec_driver_sql("BEGIN")

    return motor


def crear_fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=motor, expire_on_commit=False, future=True)


@contextmanager
def sesion_transaccional(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    """Abre una sesión y la confirma al salir; si hay error, revierte todo.

    Toda operación de negocio (por ejemplo una venta con su descuento de stock)
    debe ejecutarse dentro de un único bloque como este para ser atómica.
    """
    sesion = fabrica()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()
