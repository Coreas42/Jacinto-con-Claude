"""Configuración leída de variables de entorno (y de un archivo .env opcional)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Programa empaquetado con PyInstaller (el .exe de Windows)?
EMPAQUETADO = bool(getattr(sys, "frozen", False))

if EMPAQUETADO:
    # RAIZ_PROYECTO: recursos de solo lectura que van dentro del programa (migraciones, logo de ejemplo).
    RAIZ_PROYECTO = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # DIRECTORIO_DATOS: lo que es del negocio y se escribe (base de datos, respaldos, fotos, .env).
    # Está fuera de la carpeta del programa para que actualizar o reinstalar no toque los datos.
    DIRECTORIO_DATOS = Path(os.getenv("INVENTARIO_DATOS") or Path(os.getenv("LOCALAPPDATA") or Path.home()) / "Inventario")
    DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)
    RUTA_MIGRACIONES = RAIZ_PROYECTO / "migraciones"
else:
    RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
    DIRECTORIO_DATOS = RAIZ_PROYECTO
    RUTA_MIGRACIONES = RAIZ_PROYECTO / "alembic"

load_dotenv(DIRECTORIO_DATOS / ".env")
if EMPAQUETADO:
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(DIRECTORIO_DATOS / 'inventario.db').as_posix()}")


def _como_bool(valor: str | None, por_defecto: bool = False) -> bool:
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass(frozen=True)
class Configuracion:
    database_url: str
    nombre_empresa: str
    eslogan: str
    sql_debug: bool


def cargar_configuracion() -> Configuracion:
    """Lee la configuración actual del entorno.

    Se calcula en cada llamada para que las pruebas puedan cambiar
    ``DATABASE_URL`` sin reiniciar el proceso.
    """
    return Configuracion(
        database_url=os.getenv("DATABASE_URL", "sqlite:///inventario.db"),
        nombre_empresa=os.getenv("NOMBRE_EMPRESA", "Mi Empresa"),
        eslogan=os.getenv("ESLOGAN_EMPRESA", "").strip(),
        sql_debug=_como_bool(os.getenv("SQL_DEBUG")),
    )
