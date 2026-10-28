"""Tema visual: oscuro con acento morado, y pequeñas piezas reutilizables.

``aplicar_tema`` debe llamarse antes de crear cualquier ventana. Si algo falla al ajustar
los colores, la aplicación sigue funcionando con el tema por defecto.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import customtkinter as ctk

FONDO = "#0f0a1e"
SUPERFICIE = "#1a1230"
SUPERFICIE_2 = "#241a42"
BORDE = "#3b2a66"
ACENTO = "#8b3dff"
ACENTO_HOVER = "#a35bff"
ACENTO_SUAVE = "#cfc8e8"
TEXTO = "#f2ecff"
TEXTO_SUAVE = "#a99fc4"
VERDE = "#2ecc71"
ROJO = "#e5484d"
NARANJA = "#f5a524"

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

# Colores azules del tema "blue" de CustomTkinter -> morados.
_ACENTOS = {
    "#3B8ED0": ACENTO, "#1F6AA5": ACENTO, "#36719F": ACENTO_HOVER, "#144870": ACENTO_HOVER,
    "#325882": "#6d2fd0", "#14375E": "#6d2fd0", "#27577D": "#5a28a8", "#203A4F": "#5a28a8",
}
# Grises del modo oscuro -> superficies moradas.
_OSCUROS = {
    "gray14": FONDO, "gray13": FONDO, "gray17": SUPERFICIE, "gray20": SUPERFICIE_2, "gray23": SUPERFICIE_2,
    "#343638": SUPERFICIE_2, "#565B5E": BORDE, "#DCE4EE": TEXTO,
}


def _recolorear(nodo: Any) -> None:
    for clave, valor in list(nodo.items()):
        if isinstance(valor, dict):
            _recolorear(valor)
        elif isinstance(valor, list) and len(valor) == 2 and all(isinstance(v, str) for v in valor):
            claro, oscuro = valor
            nodo[clave] = [_ACENTOS.get(claro, claro), _OSCUROS.get(_ACENTOS.get(oscuro, oscuro), _ACENTOS.get(oscuro, oscuro))]
        elif isinstance(valor, str):
            nodo[clave] = _ACENTOS.get(valor, valor)


def aplicar_tema() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    try:
        _recolorear(ctk.ThemeManager.theme)
    except Exception:  # noqa: BLE001  (lo estético nunca debe impedir abrir la aplicación)
        pass


def fuente(tamano: int = 13, negrita: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(size=tamano, weight="bold" if negrita else "normal")


def fecha_larga(dia: date) -> str:
    return f"{DIAS[dia.weekday()].capitalize()} {dia.day} de {MESES[dia.month - 1].capitalize()} {dia.year}"


def dinero(valor: Any) -> str:
    return "—" if valor is None else f"$ {valor:,.2f}"


def cargar_logo(altura: int = 56) -> ctk.CTkImage | None:
    """Usa ``assets/logo.png`` si existe (el negocio pone allí su propio logo)."""
    from app.config import DIRECTORIO_DATOS, RAIZ_PROYECTO

    # El logo propio del negocio va en la carpeta de datos; si no hay, el que trae el programa.
    ruta = next(
        (c for c in (DIRECTORIO_DATOS / "assets" / "logo.png", RAIZ_PROYECTO / "assets" / "logo.png") if c.is_file()),
        None,
    )
    if ruta is None:
        return None
    try:
        from PIL import Image

        imagen = Image.open(ruta)
        ancho = max(1, round(imagen.width * altura / imagen.height))
        return ctk.CTkImage(light_image=imagen, dark_image=imagen, size=(ancho, altura))
    except Exception:  # noqa: BLE001
        return None


class Tarjeta(ctk.CTkFrame):
    """Panel con borde y título, base de las secciones del inicio."""

    def __init__(self, master: Any, titulo: str = "", **kwargs: Any) -> None:
        super().__init__(master, fg_color=SUPERFICIE, border_width=1, border_color=BORDE, corner_radius=12, **kwargs)
        if titulo:
            ctk.CTkLabel(self, text=titulo, font=fuente(15, True), anchor="w").pack(fill="x", padx=14, pady=(10, 4))


class TarjetaKPI(ctk.CTkFrame):
    """Indicador: icono, título, valor grande y una línea de pie (por ejemplo ``↑ +12% vs ayer``)."""

    def __init__(self, master: Any, icono: str, titulo: str) -> None:
        super().__init__(master, fg_color=SUPERFICIE, border_width=1, border_color=BORDE, corner_radius=12)
        ctk.CTkLabel(
            self, text=icono, font=fuente(26), width=52, height=52, fg_color=SUPERFICIE_2, corner_radius=10
        ).pack(side="left", padx=(12, 8), pady=12)
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(cuerpo, text=titulo, font=fuente(12), text_color=TEXTO_SUAVE, anchor="w").pack(fill="x")
        self.valor = ctk.CTkLabel(cuerpo, text="—", font=fuente(22, True), anchor="w")
        self.valor.pack(fill="x")
        self.pie = ctk.CTkLabel(cuerpo, text="", font=fuente(11), text_color=TEXTO_SUAVE, anchor="w")
        self.pie.pack(fill="x")

    def poner(self, valor: str, pie: str = "", color_pie: str = TEXTO_SUAVE) -> None:
        self.valor.configure(text=valor)
        self.pie.configure(text=pie, text_color=color_pie)


def texto_cambio(cambio: Any) -> tuple[str, str]:
    """Texto y color para una variación porcentual frente a ayer."""
    if cambio is None:
        return "", TEXTO_SUAVE
    if cambio > 0:
        return f"↑ +{cambio}% vs ayer", VERDE
    if cambio < 0:
        return f"↓ {cambio}% vs ayer", ROJO
    return "= igual que ayer", TEXTO_SUAVE
