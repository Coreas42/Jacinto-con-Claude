"""Respaldos de la base de datos SQLite: crear, rotar, listar y restaurar.

Se usa la API de respaldo de SQLite, que genera una copia consistente aunque la aplicación
esté abierta. Con PostgreSQL usa ``pg_dump`` (este módulo no aplica).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import RAIZ_PROYECTO, cargar_configuracion
from app.servicios.errores import ErrorDeNegocio

PREFIJO = "respaldo_"
PREFIJO_SEGURIDAD = "antes_de_restaurar_"
CONSERVAR_POR_DEFECTO = 14


def carpeta_de_respaldos(carpeta: str | Path | None = None) -> Path:
    if carpeta is not None:
        return Path(carpeta)
    return Path(os.getenv("CARPETA_RESPALDOS") or RAIZ_PROYECTO / "respaldos")


def archivo_de_la_base(url: str | None = None) -> Path:
    """Ruta del archivo SQLite al que apunta la URL; error claro si no es SQLite."""
    url = url or cargar_configuracion().database_url
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise ErrorDeNegocio(
            "Los respaldos integrados solo funcionan con una base SQLite en archivo. "
            "Con PostgreSQL usa pg_dump."
        )
    return Path(parsed.database)


def _copiar(origen: Path, destino: Path) -> None:
    """Copia consistente de una base SQLite a otra (puede estar en uso)."""
    entrada = sqlite3.connect(str(origen))
    salida = sqlite3.connect(str(destino))
    try:
        with salida:
            entrada.backup(salida)
    finally:
        salida.close()
        entrada.close()


def _integra(archivo: Path) -> bool:
    try:
        conexion = sqlite3.connect(f"file:{archivo}?mode=ro", uri=True)
        try:
            return conexion.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conexion.close()
    except sqlite3.Error:
        return False


def listar_respaldos(carpeta: str | Path | None = None) -> list[Path]:
    """Respaldos regulares, del más reciente al más antiguo."""
    destino = carpeta_de_respaldos(carpeta)
    if not destino.is_dir():
        return []
    return sorted(destino.glob(f"{PREFIJO}*.db"), reverse=True)


def crear_respaldo(
    url: str | None = None, carpeta: str | Path | None = None, conservar: int = CONSERVAR_POR_DEFECTO,
    prefijo: str = PREFIJO,
) -> Path:
    """Crea ``respaldo_AAAAMMDD_HHMMSS.db`` y conserva solo los ``conservar`` más recientes."""
    origen = archivo_de_la_base(url)
    if not origen.is_file():
        raise ErrorDeNegocio(f"No existe la base de datos en {origen}.")
    destino = carpeta_de_respaldos(carpeta)
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"{prefijo}{datetime.now():%Y%m%d_%H%M%S}.db"
    contador = 1
    while archivo.exists():  # dos respaldos en el mismo segundo
        archivo = destino / f"{prefijo}{datetime.now():%Y%m%d_%H%M%S}_{contador}.db"
        contador += 1
    _copiar(origen, archivo)
    if not _integra(archivo):
        archivo.unlink(missing_ok=True)
        raise ErrorDeNegocio("El respaldo se generó dañado y fue descartado. Revisa el disco y la base de datos.")
    if prefijo == PREFIJO:
        for viejo in listar_respaldos(destino)[max(conservar, 1):]:
            viejo.unlink(missing_ok=True)
    return archivo


def respaldo_automatico(
    url: str | None = None, carpeta: str | Path | None = None, conservar: int = CONSERVAR_POR_DEFECTO
) -> Path | None:
    """Un respaldo por día: no hace nada si ya hay uno de hoy. Devuelve el archivo creado, o ``None``."""
    hoy = f"{PREFIJO}{datetime.now():%Y%m%d}_"
    if any(r.name.startswith(hoy) for r in listar_respaldos(carpeta)):
        return None
    return crear_respaldo(url, carpeta, conservar)


def restaurar_respaldo(
    archivo: str | Path, url: str | None = None, carpeta: str | Path | None = None
) -> Path:
    """Reemplaza la base actual por el respaldo. Cierra la aplicación antes de restaurar.

    Antes de sobrescribir guarda una copia de seguridad de la base actual
    (``antes_de_restaurar_*.db``) y devuelve su ruta.
    """
    origen = Path(archivo)
    if not origen.is_file():
        raise ErrorDeNegocio(f"No existe el archivo de respaldo {origen}.")
    if not _integra(origen):
        raise ErrorDeNegocio("El archivo de respaldo está dañado o no es una base SQLite válida.")
    destino = archivo_de_la_base(url)
    seguridad = crear_respaldo(url, carpeta, prefijo=PREFIJO_SEGURIDAD) if destino.is_file() else None
    destino.parent.mkdir(parents=True, exist_ok=True)
    _copiar(origen, destino)
    return seguridad if seguridad is not None else destino
