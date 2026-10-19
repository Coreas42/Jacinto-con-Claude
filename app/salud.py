"""Verificación de salud del sistema (equivale a la ruta /salud de una app web)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app import __version__
from app.config import RAIZ_PROYECTO


def _cabeza_de_migraciones() -> str | None:
    config = AlembicConfig(str(RAIZ_PROYECTO / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ_PROYECTO / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def verificar_salud(motor: Engine) -> dict:
    """Comprueba la base de datos y que las migraciones estén al día.

    Devuelve un diccionario con ``estado`` igual a ``"ok"`` o ``"error"``.
    """
    resultado: dict = {
        "version": __version__,
        "base_de_datos": "desconocida",
        "migracion_actual": None,
        "migracion_esperada": None,
        "estado": "error",
        "detalle": "",
    }
    try:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
            resultado["base_de_datos"] = "conectada"
            actual = MigrationContext.configure(conexion).get_current_revision()
    except Exception as error:  # noqa: BLE001
        resultado["base_de_datos"] = "sin conexión"
        resultado["detalle"] = f"No se pudo conectar a la base de datos: {error}"
        return resultado

    esperada = _cabeza_de_migraciones()
    resultado["migracion_actual"] = actual
    resultado["migracion_esperada"] = esperada

    if actual != esperada:
        resultado["detalle"] = (
            "La base de datos no está al día. Ejecuta: python main.py --migrar"
        )
        return resultado

    resultado["estado"] = "ok"
    resultado["detalle"] = "Todo en orden."
    return resultado
