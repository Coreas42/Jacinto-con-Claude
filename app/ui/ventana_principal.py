"""Ventana principal. En la Fase 0 solo muestra el estado del sistema."""

from __future__ import annotations

from sqlalchemy import Engine

from app import __version__
from app.config import cargar_configuracion
from app.salud import verificar_salud


def abrir_ventana_principal(motor: Engine) -> None:
    # Se importa aquí para que las pruebas y la línea de comandos
    # funcionen en equipos sin entorno gráfico.
    import customtkinter as ctk

    configuracion = cargar_configuracion()
    salud = verificar_salud(motor)

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")

    ventana = ctk.CTk()
    ventana.title(f"{configuracion.nombre_empresa} · Inventario y ventas")
    ventana.geometry("640x360")

    ctk.CTkLabel(
        ventana,
        text=configuracion.nombre_empresa,
        font=ctk.CTkFont(size=26, weight="bold"),
    ).pack(pady=(32, 4))
    ctk.CTkLabel(ventana, text=f"Inventario y ventas · versión {__version__}").pack()

    color = "#2e9e5b" if salud["estado"] == "ok" else "#d64545"
    ctk.CTkLabel(
        ventana,
        text=f"Estado del sistema: {salud['estado'].upper()}",
        text_color=color,
        font=ctk.CTkFont(size=16, weight="bold"),
    ).pack(pady=(28, 4))
    ctk.CTkLabel(ventana, text=salud["detalle"], wraplength=540).pack()

    ctk.CTkLabel(
        ventana,
        text="Los módulos (usuarios, productos, inventario, ventas y reportes)\n"
        "se activan en las siguientes fases.",
        text_color="gray",
    ).pack(pady=(28, 0))

    ventana.mainloop()
