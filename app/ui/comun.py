"""Piezas comunes de las pantallas: ejecución en transacción con mensajes, tablas y diálogos."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.errores import ErrorDeNegocio
from app.servicios.usuarios import obtener_usuario
from app.ui import tema


class PantallaBase(ctk.CTkFrame):
    """Marco con título y línea de mensajes; ``ejecutar`` corre un servicio como el usuario con sesión."""

    def __init__(self, master: Any, app: Any, titulo: str) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        ctk.CTkLabel(self, text=titulo, font=tema.fuente(22, True)).pack(anchor="w")
        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        self.mensaje.pack(fill="x", pady=2)

    def ejecutar(self, funcion: Callable[[Any, Any], Any], exito: str | None = None) -> tuple[bool, Any]:
        try:
            with sesion_transaccional(self.app.fabrica) as sesion:
                actor = obtener_usuario(sesion, self.app.usuario.id)
                resultado = funcion(sesion, actor)
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=tema.ROJO)
            return False, None
        if exito:
            self.mensaje.configure(text=exito, text_color=tema.VERDE)
        return True, resultado


def pintar_tabla(marco: Any, encabezados: list[str], filas: list[list[Any]], derecha: set[int] | None = None,
                 vacio: str = "No hay datos para mostrar.") -> None:
    """Dibuja una tabla simple. Una celda puede ser texto o un widget ya creado en ``marco`` (vía ``lambda master``)."""
    derecha = derecha or set()
    for widget in marco.winfo_children():
        widget.destroy()
    for columna, titulo in enumerate(encabezados):
        ctk.CTkLabel(marco, text=titulo, font=tema.fuente(12, True), text_color=tema.TEXTO_SUAVE).grid(
            row=0, column=columna, padx=8, pady=4, sticky="e" if columna in derecha else "w"
        )
    if not filas:
        ctk.CTkLabel(marco, text=vacio, text_color=tema.TEXTO_SUAVE).grid(
            row=1, column=0, columnspan=len(encabezados), pady=20
        )
    for fila, celdas in enumerate(filas, start=1):
        for columna, celda in enumerate(celdas):
            if callable(celda):
                celda(marco).grid(row=fila, column=columna, padx=8, pady=2)
            else:
                ctk.CTkLabel(marco, text=str(celda)).grid(
                    row=fila, column=columna, padx=8, pady=2, sticky="e" if columna in derecha else "w"
                )


class Dialogo(ctk.CTkToplevel):
    def __init__(self, pantalla: Any, titulo: str, tamano: str) -> None:
        super().__init__(pantalla)
        self.pantalla = pantalla
        self.title(titulo)
        self.geometry(tamano)
        self.after(150, self._tomar_foco)

    def _tomar_foco(self) -> None:
        try:
            self.grab_set()
            self.focus_set()
        except Exception:  # noqa: BLE001  (la ventana pudo cerrarse antes)
            pass


class DialogoFormulario(Dialogo):
    """Formulario de campos de texto; ``guardar(sesion, actor, valores)`` recibe un dict por campo."""

    def __init__(self, pantalla: Any, titulo: str, campos: list[tuple[str, str]], guardar: Callable,
                 valores: dict[str, str] | None = None, exito: str = "Guardado.") -> None:
        super().__init__(pantalla, titulo, f"400x{120 + 56 * len(campos)}")
        self._guardar, self._exito = guardar, exito
        self.entradas: dict[str, ctk.CTkEntry] = {}
        for clave, etiqueta in campos:
            entrada = ctk.CTkEntry(self, width=320, placeholder_text=etiqueta)
            entrada.pack(pady=8, padx=24)
            if valores and valores.get(clave):
                entrada.insert(0, valores[clave])
            self.entradas[clave] = entrada
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=14)

    def guardar(self) -> None:
        datos = {clave: entrada.get() for clave, entrada in self.entradas.items()}
        ok, _ = self.pantalla.ejecutar(lambda s, a: self._guardar(s, a, datos), exito=self._exito)
        if ok:
            self.pantalla.recargar()
            self.destroy()


class DialogoMotivo(Dialogo):
    """Pide un motivo antes de una acción delicada (anular)."""

    def __init__(self, pantalla: Any, titulo: str, pregunta: str, accion: Callable[[Any, Any, str], Any], exito: str) -> None:
        super().__init__(pantalla, titulo, "420x230")
        self._accion, self._exito = accion, exito
        ctk.CTkLabel(self, text=pregunta, wraplength=360).pack(pady=(22, 8))
        self.motivo = ctk.CTkEntry(self, width=340, placeholder_text="Motivo (obligatorio)")
        self.motivo.pack(pady=8)
        ctk.CTkButton(self, text="Confirmar", fg_color=tema.ROJO, hover_color="#c23b40", command=self.confirmar).pack(pady=14)

    def confirmar(self) -> None:
        motivo = self.motivo.get()
        ok, _ = self.pantalla.ejecutar(lambda s, a: self._accion(s, a, motivo), exito=self._exito)
        if ok:
            self.pantalla.recargar()
            self.destroy()
