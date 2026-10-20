"""Ventana principal: login, menú lateral según permisos y cambio de módulo."""

from __future__ import annotations

import customtkinter as ctk
from sqlalchemy import Engine, func, select

from app import __version__
from app.config import cargar_configuracion
from app.db import crear_fabrica_sesiones, sesion_transaccional
from app.modelos import Usuario
from app.salud import verificar_salud
from app.servicios.autenticacion import (
    SesionUsuario,
    cerrar_sesion,
    datos_de_sesion,
    iniciar_sesion,
)
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import NOMBRES_MODULOS

ROJO = "#d64545"
VERDE = "#2e9e5b"

# Módulos cuya pantalla llega en una fase posterior.
FASE_DE_MODULO = {"ventas": 4, "reportes": 5}


class Aplicacion(ctk.CTk):
    def __init__(self, motor: Engine) -> None:
        super().__init__()
        self.motor = motor
        self.fabrica = crear_fabrica_sesiones(motor)
        self.configuracion = cargar_configuracion()
        self.usuario: SesionUsuario | None = None

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        self.title(f"{self.configuracion.nombre_empresa} · Inventario y ventas")
        self.geometry("1100x680")
        self.minsize(900, 560)
        self.mostrar_login()

    # ---- navegación entre pantallas -------------------------------------------------

    def _limpiar(self) -> None:
        for widget in self.winfo_children():
            widget.destroy()

    def mostrar_login(self) -> None:
        self._limpiar()
        PantallaLogin(self).pack(expand=True)

    def mostrar_principal(self) -> None:
        self._limpiar()
        PantallaPrincipal(self).pack(fill="both", expand=True)

    # ---- acciones -------------------------------------------------------------------

    def entrar(self, correo: str, clave: str) -> None:
        """Lanza ``ErrorDeNegocio`` si las credenciales no son válidas."""
        with sesion_transaccional(self.fabrica) as sesion:
            usuario = iniciar_sesion(sesion, correo, clave)
            self.usuario = datos_de_sesion(sesion, usuario)
        self.mostrar_principal()

    def salir(self) -> None:
        if self.usuario is not None:
            with sesion_transaccional(self.fabrica) as sesion:
                cerrar_sesion(sesion, self.usuario.id)
        self.usuario = None
        self.mostrar_login()

    def hay_usuarios(self) -> bool:
        with sesion_transaccional(self.fabrica) as sesion:
            return (sesion.scalar(select(func.count()).select_from(Usuario)) or 0) > 0


class PantallaLogin(ctk.CTkFrame):
    def __init__(self, app: Aplicacion) -> None:
        super().__init__(app, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(
            self,
            text=app.configuracion.nombre_empresa,
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(pady=(0, 4))
        ctk.CTkLabel(self, text="Inicia sesión para continuar").pack(pady=(0, 20))

        self.correo = ctk.CTkEntry(self, width=300, placeholder_text="Correo")
        self.correo.pack(pady=6)
        self.clave = ctk.CTkEntry(self, width=300, placeholder_text="Contraseña", show="•")
        self.clave.pack(pady=6)
        self.clave.bind("<Return>", lambda _evento: self.entrar())
        self.correo.bind("<Return>", lambda _evento: self.clave.focus())

        self.mensaje = ctk.CTkLabel(self, text="", text_color=ROJO, wraplength=300)
        self.mensaje.pack(pady=(8, 0))
        ctk.CTkButton(self, text="Entrar", width=300, command=self.entrar).pack(pady=12)

        self._mostrar_estado_del_sistema()
        self.correo.focus()

    def _mostrar_estado_del_sistema(self) -> None:
        salud = verificar_salud(self.app.motor)
        if salud["estado"] != "ok":
            self.mensaje.configure(text=salud["detalle"])
            return
        if not self.app.hay_usuarios():
            self.mensaje.configure(
                text="Aún no hay usuarios. Ejecuta: python seed.py", text_color=ROJO
            )
        ctk.CTkLabel(self, text=f"versión {__version__}", text_color="gray").pack(pady=(16, 0))

    def entrar(self) -> None:
        try:
            self.app.entrar(self.correo.get(), self.clave.get())
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            self.clave.delete(0, "end")


class PantallaPrincipal(ctk.CTkFrame):
    def __init__(self, app: Aplicacion) -> None:
        super().__init__(app, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        assert usuario is not None

        menu = ctk.CTkFrame(self, width=220, corner_radius=0)
        menu.pack(side="left", fill="y")
        menu.pack_propagate(False)

        ctk.CTkLabel(
            menu,
            text=app.configuracion.nombre_empresa,
            font=ctk.CTkFont(size=18, weight="bold"),
            wraplength=190,
        ).pack(padx=16, pady=(20, 2))
        ctk.CTkLabel(menu, text=f"{usuario.nombre}\n({usuario.rol})", text_color="gray").pack(
            padx=16, pady=(0, 16)
        )

        # El menú solo ofrece los módulos para los que el usuario tiene algún permiso.
        self.botones: dict[str, ctk.CTkButton] = {}
        for modulo in usuario.modulos:
            boton = ctk.CTkButton(
                menu,
                text=NOMBRES_MODULOS[modulo],
                anchor="w",
                command=lambda m=modulo: self.mostrar_modulo(m),
            )
            boton.pack(fill="x", padx=12, pady=3)
            self.botones[modulo] = boton

        ctk.CTkButton(
            menu,
            text="Cerrar sesión",
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
            command=app.salir,
        ).pack(side="bottom", fill="x", padx=12, pady=16)

        self.contenido = ctk.CTkFrame(self, fg_color="transparent")
        self.contenido.pack(side="left", fill="both", expand=True, padx=20, pady=20)

        if usuario.modulos:
            self.mostrar_modulo(usuario.modulos[0])
        else:
            ctk.CTkLabel(
                self.contenido,
                text="Tu usuario no tiene módulos asignados.\nPide a un administrador que te dé acceso.",
            ).pack(expand=True)

    def mostrar_modulo(self, modulo: str) -> None:
        for widget in self.contenido.winfo_children():
            widget.destroy()
        for nombre, boton in self.botones.items():
            boton.configure(fg_color=("#1f6aa5" if nombre == modulo else "gray40"))

        if modulo == "productos":
            from app.ui.productos_pantalla import PantallaProductos

            PantallaProductos(self.contenido, self.app).pack(fill="both", expand=True)
        elif modulo == "inventario":
            from app.ui.inventario_pantalla import PantallaInventario

            PantallaInventario(self.contenido, self.app).pack(fill="both", expand=True)
        elif modulo == "usuarios":
            from app.ui.usuarios_pantalla import PantallaUsuarios

            PantallaUsuarios(self.contenido, self.app).pack(fill="both", expand=True)
        elif modulo == "bitacora":
            from app.ui.bitacora_pantalla import PantallaBitacora

            PantallaBitacora(self.contenido, self.app).pack(fill="both", expand=True)
        else:
            fase = FASE_DE_MODULO.get(modulo, "?")
            ctk.CTkLabel(
                self.contenido,
                text=f"{NOMBRES_MODULOS[modulo]}\n\nEste módulo se activa en la Fase {fase}.",
                font=ctk.CTkFont(size=16),
            ).pack(expand=True)


def abrir_aplicacion(motor: Engine) -> None:
    Aplicacion(motor).mainloop()
