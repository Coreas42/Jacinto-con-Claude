"""Configuración del sistema guardada en la base de datos (tabla ``configuracion``).

Los valores propios de cada instalación (nombre del negocio, inactividad...) se editan desde la
pantalla de Configuración. Para el nombre y el eslogan, si aún no hay valor guardado se usa el
del archivo ``.env``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import cargar_configuracion
from app.modelos import Configuracion, Usuario
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import exigir_permiso

MAXIMO_INACTIVIDAD = 480  # minutos (8 horas)

# clave -> descripción. Los valores se validan en ``_normalizar``.
CLAVES = {
    "nombre_empresa": "Nombre del negocio",
    "eslogan": "Línea bajo el nombre",
    "inactividad_minutos": "Cerrar la sesión tras estos minutos sin usar el sistema (0 = nunca)",
    "metodo_costeo": "Cómo se calcula el costo de lo que se vende (promedio ponderado o PEPS)",
}

METODOS_COSTEO = ("promedio", "peps")
METODO_COSTEO_POR_DEFECTO = "promedio"


def metodo_costeo(sesion: Session) -> str:
    """Método de costeo vigente (``promedio`` o ``peps``). No exige permiso: lo consulta el inventario."""
    valor = sesion.scalar(select(Configuracion.valor).where(Configuracion.clave == "metodo_costeo"))
    return valor if valor in METODOS_COSTEO else METODO_COSTEO_POR_DEFECTO

INACTIVIDAD_POR_DEFECTO = 15


def valores_actuales(sesion: Session) -> dict[str, Any]:
    """Valores vigentes con sus tipos. No exige permiso: lo usa la ventana para arrancar."""
    entorno = cargar_configuracion()
    guardados = {c.clave: c.valor for c in sesion.scalars(select(Configuracion))}
    try:
        minutos = int(guardados.get("inactividad_minutos", INACTIVIDAD_POR_DEFECTO))
    except ValueError:
        minutos = INACTIVIDAD_POR_DEFECTO
    return {
        "nombre_empresa": guardados.get("nombre_empresa") or entorno.nombre_empresa,
        "eslogan": guardados["eslogan"] if "eslogan" in guardados else entorno.eslogan,
        "inactividad_minutos": max(0, min(minutos, MAXIMO_INACTIVIDAD)),
        "metodo_costeo": guardados["metodo_costeo"] if guardados.get("metodo_costeo") in METODOS_COSTEO else METODO_COSTEO_POR_DEFECTO,
    }


def ver_configuracion(sesion: Session, actor: Usuario) -> dict[str, Any]:
    exigir_permiso(sesion, actor, "configuracion", "ver")
    return valores_actuales(sesion)


def _normalizar(clave: str, valor: Any) -> Any:
    if clave == "nombre_empresa":
        texto = str(valor or "").strip()
        if not texto:
            raise ErrorDeNegocio("El nombre del negocio es obligatorio.")
        if len(texto) > 80:
            raise ErrorDeNegocio("El nombre del negocio admite hasta 80 caracteres.")
        return texto
    if clave == "eslogan":
        texto = str(valor or "").strip()
        if len(texto) > 120:
            raise ErrorDeNegocio("La línea bajo el nombre admite hasta 120 caracteres.")
        return texto
    if clave == "inactividad_minutos":
        try:
            minutos = int(str(valor).strip())
        except ValueError:
            raise ErrorDeNegocio("Los minutos de inactividad deben ser un número entero.") from None
        if not 0 <= minutos <= MAXIMO_INACTIVIDAD:
            raise ErrorDeNegocio(f"Los minutos de inactividad van de 0 a {MAXIMO_INACTIVIDAD}.")
        return minutos
    if clave == "metodo_costeo":
        metodo = str(valor or "").strip().lower()
        if metodo not in METODOS_COSTEO:
            raise ErrorDeNegocio("El método de costeo debe ser «promedio» o «peps».")
        return metodo
    raise ErrorDeNegocio(f"Parámetro desconocido: {clave}")


def guardar_configuracion(sesion: Session, actor: Usuario, cambios: dict[str, Any]) -> dict[str, Any]:
    """Valida y guarda los parámetros indicados. Exige ``configuracion.editar``. Devuelve los valores vigentes."""
    exigir_permiso(sesion, actor, "configuracion", "editar")
    nuevos = {clave: _normalizar(clave, valor) for clave, valor in cambios.items()}
    antes = valores_actuales(sesion)
    existentes = {c.clave: c for c in sesion.scalars(select(Configuracion))}
    detalle: dict[str, list[Any]] = {}
    for clave, valor in nuevos.items():
        if antes[clave] == valor:
            continue
        detalle[clave] = [antes[clave], valor]
        fila = existentes.get(clave)
        if fila is None:
            sesion.add(Configuracion(clave=clave, valor=str(valor), descripcion=CLAVES[clave]))
        else:
            fila.valor = str(valor)
    if detalle:
        registrar(sesion, "configuracion_cambiada", usuario_id=actor.id, entidad="configuracion", detalle=detalle)
    sesion.flush()
    return valores_actuales(sesion)


def sesion_expirada(segundos_inactivo: float, minutos: int) -> bool:
    """``True`` si ya pasó el tiempo permitido sin actividad. ``minutos == 0`` desactiva el cierre."""
    return minutos > 0 and segundos_inactivo >= minutos * 60


def registrar_expiracion(sesion: Session, usuario_id: int, minutos: int) -> None:
    registrar(
        sesion, "sesion_expirada", usuario_id=usuario_id, entidad="usuarios", entidad_id=usuario_id,
        detalle={"minutos": minutos},
    )
