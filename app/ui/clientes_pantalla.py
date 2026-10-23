"""Clientes: búsqueda, alta, edición y desactivación."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from app.servicios.ventas import crear_cliente, editar_cliente, establecer_cliente_activo, listar_clientes
from app.ui import tema
from app.ui.comun import DialogoFormulario, PantallaBase, pintar_tabla

CAMPOS = [("nombre", "Nombre"), ("telefono", "Teléfono (opcional)"), ("correo", "Correo (opcional)")]


class PantallaClientes(PantallaBase):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app, "Clientes")
        u = app.usuario
        self.puede_crear = u.puede("ventas", "crear")
        self.puede_desactivar = u.puede("ventas", "anular")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        self.busqueda = ctk.CTkEntry(barra, width=280, placeholder_text="Buscar por nombre, teléfono o correo")
        self.busqueda.pack(side="left")
        self.busqueda.bind("<KeyRelease>", lambda _e: self.recargar())
        self.inactivos = ctk.CTkSwitch(barra, text="Ver desactivados", command=self.recargar)
        self.inactivos.pack(side="left", padx=14)
        if self.puede_crear:
            ctk.CTkButton(barra, text="+ Nuevo cliente", command=self.nuevo).pack(side="right")

        self.tabla = ctk.CTkScrollableFrame(self)
        self.tabla.pack(fill="both", expand=True)
        self.recargar()

    def nuevo(self) -> None:
        DialogoFormulario(
            self, "Nuevo cliente", CAMPOS,
            lambda s, a, d: crear_cliente(s, a, d["nombre"], d["telefono"], d["correo"]), exito="Cliente guardado.",
        )

    def editar(self, cliente: dict) -> None:
        DialogoFormulario(
            self, "Editar cliente", CAMPOS,
            lambda s, a, d: editar_cliente(s, a, cliente["id"], d["nombre"], d["telefono"], d["correo"]),
            valores=cliente, exito="Cliente actualizado.",
        )

    def alternar(self, cliente: dict) -> None:
        ok, _ = self.ejecutar(
            lambda s, a: establecer_cliente_activo(s, a, cliente["id"], not cliente["activo"]),
            exito="Cliente reactivado." if not cliente["activo"] else "Cliente desactivado.",
        )
        if ok:
            self.recargar()

    def recargar(self) -> None:
        texto, con_inactivos = self.busqueda.get(), bool(self.inactivos.get())
        ok, clientes = self.ejecutar(lambda s, a: listar_clientes(s, a, texto, con_inactivos))
        if not ok:
            return

        def acciones(c: dict):
            def crear(master: Any) -> ctk.CTkFrame:
                caja = ctk.CTkFrame(master, fg_color="transparent")
                if self.puede_crear:
                    ctk.CTkButton(caja, text="Editar", width=70, command=lambda: self.editar(c)).pack(side="left", padx=2)
                if self.puede_desactivar:
                    ctk.CTkButton(
                        caja, text="Reactivar" if not c["activo"] else "Desactivar", width=90,
                        fg_color=tema.SUPERFICIE_2, command=lambda: self.alternar(c),
                    ).pack(side="left", padx=2)
                return caja
            return crear

        pintar_tabla(
            self.tabla, ["Nombre", "Teléfono", "Correo", "Estado", ""],
            [[c["nombre"], c["telefono"] or "", c["correo"] or "", "Activo" if c["activo"] else "Desactivado", acciones(c)]
             for c in clientes],
            vacio="No hay clientes.",
        )
