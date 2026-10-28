"""Aplicación de migraciones de Alembic desde código."""

from __future__ import annotations

from alembic import command
from alembic.config import Config as AlembicConfig

from app.config import RAIZ_PROYECTO, RUTA_MIGRACIONES, cargar_configuracion


def _config_alembic(url: str | None = None) -> AlembicConfig:
    config = AlembicConfig(str(RAIZ_PROYECTO / "alembic.ini"))
    config.set_main_option("script_location", str(RUTA_MIGRACIONES))
    # Los % deben escaparse para el interpolador de configparser.
    url = (url or cargar_configuracion().database_url).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", url)
    return config


def migrar_a_ultima(url: str | None = None) -> None:
    """Lleva la base de datos a la última migración (no destruye datos)."""
    command.upgrade(_config_alembic(url), "head")
