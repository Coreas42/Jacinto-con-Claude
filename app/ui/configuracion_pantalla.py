"""Configuración del negocio: nombre, línea bajo el nombre y cierre por inactividad."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from app.servicios.configuracion import MAXIMO_INACTIVIDAD, guardar_configuracion, ver_configuracion
from app.ui import tema
from app.ui.comun import PantallaBase


class PantallaConfiguracion(PantallaBase):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app, "Configuración")
        self.puede_editar = app.usuario.puede("configuracion", "editar")
        ok, valores = self.ejecutar(lambda s, a: ver_configuracion(s, a))
        if not ok:
            return

        caja = tema.Tarjeta(self, "Datos del negocio")
        caja.pack(fill="x", pady=(6, 10))
        self.campos: dict[str, ctk.CTkEntry] = {}
        for clave, etiqueta, ayuda in [
            ("nombre_empresa", "Nombre del negocio", "Aparece en el encabezado, la ventana y los comprobantes."),
            ("eslogan", "Línea bajo el nombre (opcional)", "Ej.: ACCESORIOS • INSTALACIÓN • POLARIZADO"),
        ]:
            self._fila(caja, clave, etiqueta, ayuda, valores[clave])

        seguridad = tema.Tarjeta(self, "Seguridad")
        seguridad.pack(fill="x")
        self._fila(
            seguridad, "inactividad_minutos", "Cerrar sesión por inactividad (minutos)",
            f"De 0 a {MAXIMO_INACTIVIDAD}. Con 0 la sesión nunca se cierra sola. Una venta sin cobrar se pierde al cerrar.",
            valores["inactividad_minutos"],
        )
        if self.puede_editar:
            ctk.CTkButton(self, text="Guardar cambios", command=self.guardar).pack(anchor="w", pady=14)
        else:
            ctk.CTkLabel(self, text="Solo lectura: no tienes permiso para editar.", text_color=tema.TEXTO_SUAVE).pack(anchor="w", pady=10)

    def _fila(self, caja: Any, clave: str, etiqueta: str, ayuda: str, valor: Any) -> None:
        ctk.CTkLabel(caja, text=etiqueta, anchor="w", font=tema.fuente(13, True)).pack(fill="x", padx=12, pady=(4, 0))
        entrada = ctk.CTkEntry(caja, width=420)
        entrada.insert(0, str(valor))
        if not self.puede_editar:
            entrada.configure(state="disabled")
        entrada.pack(anchor="w", padx=12)
        ctk.CTkLabel(caja, text=ayuda, anchor="w", text_color=tema.TEXTO_SUAVE, font=tema.fuente(11)).pack(fill="x", padx=12, pady=(0, 8))
        self.campos[clave] = entrada

    def guardar(self) -> None:
        cambios = {clave: campo.get() for clave, campo in self.campos.items()}
        ok, _ = self.ejecutar(lambda s, a: guardar_configuracion(s, a, cambios))
        if ok:
            self.app.aplicar_configuracion()
