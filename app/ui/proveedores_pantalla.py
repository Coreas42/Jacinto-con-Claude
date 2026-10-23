"""Proveedores: alta, edición y desactivación (usa los permisos de inventario)."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from app.servicios.inventario import (
    crear_proveedor,
    editar_proveedor,
    establecer_proveedor_activo,
    listar_proveedores,
)
from app.ui import tema
from app.ui.comun import DialogoFormulario, PantallaBase, pintar_tabla

CAMPOS = [("nombre", "Nombre"), ("contacto", "Contacto: teléfono o correo (opcional)")]


class PantallaProveedores(PantallaBase):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app, "Proveedores")
        u = app.usuario
        self.puede_crear = u.puede("inventario", "crear")
        self.puede_editar = u.puede("inventario", "editar")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        self.inactivos = ctk.CTkSwitch(barra, text="Ver desactivados", command=self.recargar)
        self.inactivos.pack(side="left")
        if self.puede_crear:
            ctk.CTkButton(barra, text="+ Nuevo proveedor", command=self.nuevo).pack(side="right")
        self.tabla = ctk.CTkScrollableFrame(self)
        self.tabla.pack(fill="both", expand=True)
        self.recargar()

    def nuevo(self) -> None:
        DialogoFormulario(
            self, "Nuevo proveedor", CAMPOS, lambda s, a, d: crear_proveedor(s, a, d["nombre"], d["contacto"]),
            exito="Proveedor guardado.",
        )

    def editar(self, proveedor: dict) -> None:
        DialogoFormulario(
            self, "Editar proveedor", CAMPOS,
            lambda s, a, d: editar_proveedor(s, a, proveedor["id"], d["nombre"], d["contacto"]),
            valores=proveedor, exito="Proveedor actualizado.",
        )

    def alternar(self, proveedor: dict) -> None:
        ok, _ = self.ejecutar(
            lambda s, a: establecer_proveedor_activo(s, a, proveedor["id"], not proveedor["activo"]),
            exito="Proveedor actualizado.",
        )
        if ok:
            self.recargar()

    def recargar(self) -> None:
        con_inactivos = bool(self.inactivos.get())
        ok, proveedores = self.ejecutar(lambda s, a: listar_proveedores(s, a, con_inactivos))
        if not ok:
            return

        def acciones(p: dict):
            def crear(master: Any) -> ctk.CTkFrame:
                caja = ctk.CTkFrame(master, fg_color="transparent")
                if self.puede_editar:
                    ctk.CTkButton(caja, text="Editar", width=70, command=lambda: self.editar(p)).pack(side="left", padx=2)
                    ctk.CTkButton(
                        caja, text="Reactivar" if not p["activo"] else "Desactivar", width=90,
                        fg_color=tema.SUPERFICIE_2, command=lambda: self.alternar(p),
                    ).pack(side="left", padx=2)
                return caja
            return crear

        pintar_tabla(
            self.tabla, ["Nombre", "Contacto", "Estado", ""],
            [[p["nombre"], p["contacto"] or "", "Activo" if p["activo"] else "Desactivado", acciones(p)] for p in proveedores],
            vacio="No hay proveedores.",
        )
