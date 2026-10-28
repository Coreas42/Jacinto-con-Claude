"""Fotos de producto.

La base de datos guarda solo el nombre del archivo; la imagen se copia (reducida a 800 px y
convertida a JPEG) a la carpeta de fotos (``CARPETA_FOTOS``, por defecto ``fotos/``).
Hace falta Pillow.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import RAIZ_PROYECTO
from app.modelos import Producto, Usuario
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import exigir_permiso

TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024
LADO_MAXIMO = 800
EXTENSIONES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def carpeta_fotos() -> Path:
    destino = Path(os.getenv("CARPETA_FOTOS", "fotos"))
    return destino if destino.is_absolute() else RAIZ_PROYECTO / destino


def _producto(sesion: Session, producto_id: int) -> Producto:
    producto = sesion.get(Producto, producto_id)
    if producto is None:
        raise ErrorDeNegocio("El producto no existe.")
    return producto


def _borrar_archivo(nombre: str | None) -> None:
    if not nombre:
        return
    try:
        (carpeta_fotos() / nombre).unlink(missing_ok=True)
    except OSError:
        pass  # un archivo que no se puede borrar no debe frenar la operación


def _preparar_imagen(origen: Path, destino: Path) -> None:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise ErrorDeNegocio("Falta instalar Pillow para usar fotos: pip install -r requirements.txt") from None
    try:
        with Image.open(origen) as bruta:
            bruta.load()
            imagen = ImageOps.exif_transpose(bruta)
            if imagen.mode in ("RGBA", "LA", "P"):
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, "white")
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
            destino.parent.mkdir(parents=True, exist_ok=True)
            imagen.save(destino, "JPEG", quality=85)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ErrorDeNegocio("El archivo no es una imagen válida.") from None


def asignar_foto(sesion: Session, actor: Usuario, producto_id: int, ruta_origen: str | Path) -> str:
    """Copia la imagen a la carpeta de fotos y la asocia al producto. Devuelve el nombre del archivo."""
    exigir_permiso(sesion, actor, "productos", "editar")
    producto = _producto(sesion, producto_id)
    origen = Path(ruta_origen)
    if origen.suffix.lower() not in EXTENSIONES:
        raise ErrorDeNegocio("Formato no admitido. Usa PNG, JPG, GIF, BMP o WEBP.")
    if not origen.is_file():
        raise ErrorDeNegocio("No se encontró el archivo de la imagen.")
    if origen.stat().st_size > TAMANO_MAXIMO_BYTES:
        raise ErrorDeNegocio("La imagen pesa más de 10 MB.")

    nombre = f"p{producto.id}_{uuid.uuid4().hex[:8]}.jpg"
    _preparar_imagen(origen, carpeta_fotos() / nombre)
    anterior = producto.foto
    producto.foto = nombre
    sesion.flush()
    registrar(
        sesion, "foto_asignada", usuario_id=actor.id, entidad="productos", entidad_id=producto.id,
        detalle={"archivo": nombre},
    )
    _borrar_archivo(anterior)
    return nombre


def quitar_foto(sesion: Session, actor: Usuario, producto_id: int) -> None:
    exigir_permiso(sesion, actor, "productos", "editar")
    producto = _producto(sesion, producto_id)
    if producto.foto is None:
        return
    anterior = producto.foto
    producto.foto = None
    sesion.flush()
    registrar(sesion, "foto_quitada", usuario_id=actor.id, entidad="productos", entidad_id=producto.id, detalle={"archivo": anterior})
    _borrar_archivo(anterior)


def rutas_de_fotos(sesion: Session, actor: Usuario, producto_ids: list[int]) -> dict[int, Path]:
    """Ruta de la foto de cada producto que la tenga y cuyo archivo exista."""
    exigir_permiso(sesion, actor, "productos", "ver")
    if not producto_ids:
        return {}
    carpeta = carpeta_fotos()
    filas = sesion.execute(select(Producto.id, Producto.foto).where(Producto.id.in_(producto_ids), Producto.foto.is_not(None)))
    return {i: carpeta / f for i, f in filas if (carpeta / f).is_file()}
