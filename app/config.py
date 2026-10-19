"""Configuración leída de variables de entorno (y de un archivo .env opcional)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ_PROYECTO / ".env")


def _como_bool(valor: str | None, por_defecto: bool = False) -> bool:
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass(frozen=True)
class Configuracion:
    database_url: str
    nombre_empresa: str
    sql_debug: bool


def cargar_configuracion() -> Configuracion:
    """Lee la configuración actual del entorno.

    Se calcula en cada llamada para que las pruebas puedan cambiar
    ``DATABASE_URL`` sin reiniciar el proceso.
    """
    return Configuracion(
        database_url=os.getenv("DATABASE_URL", "sqlite:///inventario.db"),
        nombre_empresa=os.getenv("NOMBRE_EMPRESA", "Mi Empresa"),
        sql_debug=_como_bool(os.getenv("SQL_DEBUG")),
    )
