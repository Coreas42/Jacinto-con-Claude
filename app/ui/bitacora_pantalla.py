"""Pantalla de consulta de la bitácora de auditoría (solo lectura)."""

from __future__ import annotations

import json
from typing import Any

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.auditoria import listar_bitacora
from app.servicios.errores import ErrorDeNegocio
from app.servicios.usuarios import obtener_usuario


class PantallaBitacora(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            cabecera, text="Bitácora de auditoría", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(cabecera, text="Actualizar", width=100, command=self.recargar).pack(side="right")

        self.texto = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none")
        self.texto.pack(fill="both", expand=True)
        self.recargar()

    def recargar(self) -> None:
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        try:
            with sesion_transaccional(self.app.fabrica) as sesion:
                actor = obtener_usuario(sesion, self.app.usuario.id)
                eventos = listar_bitacora(sesion, actor)
        except ErrorDeNegocio as error:
            self.texto.insert("end", str(error))
        else:
            if not eventos:
                self.texto.insert("end", "Sin eventos registrados.")
            for evento in eventos:
                detalle = json.dumps(evento["detalle"], ensure_ascii=False) if evento["detalle"] else ""
                destino = f"{evento['entidad']}#{evento['entidad_id']}" if evento["entidad"] else ""
                self.texto.insert(
                    "end",
                    f"{evento['fecha']:%Y-%m-%d %H:%M:%S} UTC | {evento['usuario']:<18} | "
                    f"{evento['accion']:<28} | {destino:<14} | {detalle}\n",
                )
        self.texto.configure(state="disabled")
