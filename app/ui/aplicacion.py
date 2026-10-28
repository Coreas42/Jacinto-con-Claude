"""Ventana principal: login, encabezado, menú lateral según permisos y cambio de módulo."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

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
from app.servicios.configuracion import registrar_expiracion, sesion_expirada, valores_actuales
from app.servicios.errores import ErrorDeNegocio
from app.ui import tema

ROJO = "#d64545"
VERDE = "#2e9e5b"


class Aplicacion(ctk.CTk):
    def __init__(self, motor: Engine) -> None:
        tema.aplicar_tema()
        super().__init__()
        self.motor = motor
        self.fabrica = crear_fabrica_sesiones(motor)
        self.configuracion = cargar_configuracion()
        self.usuario: SesionUsuario | None = None
        self.principal: PantallaPrincipal | None = None
        self.inactividad_minutos = 0
        self.aviso_login = ""
        self._ultima_actividad = time.monotonic()
        self._cargar_valores_guardados()
        for evento in ("<Key>", "<Motion>", "<ButtonPress>", "<MouseWheel>"):
            self.bind_all(evento, self._registrar_actividad, add="+")
        self.after(10_000, self._vigilar_inactividad)

        self.title(f"{self.configuracion.nombre_empresa} · Inventario y ventas")
        self.geometry("1280x780")
        self.minsize(1000, 620)
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
        self.principal = PantallaPrincipal(self)
        self.principal.pack(fill="both", expand=True)

    # ---- configuración guardada e inactividad ---------------------------------------

    def _cargar_valores_guardados(self) -> None:
        try:
            with sesion_transaccional(self.fabrica) as sesion:
                valores = valores_actuales(sesion)
        except Exception:  # noqa: BLE001 - sin base lista, la pantalla de login lo informa
            return
        self.configuracion = replace(
            self.configuracion, nombre_empresa=valores["nombre_empresa"], eslogan=valores["eslogan"]
        )
        self.inactividad_minutos = valores["inactividad_minutos"]
        self.title(f"{self.configuracion.nombre_empresa} · Inventario y ventas")

    def aplicar_configuracion(self) -> None:
        """Relee la configuración guardada y reconstruye la pantalla principal (nombre en el encabezado)."""
        self._cargar_valores_guardados()
        self.mostrar_principal()
        if self.principal is not None and "configuracion" in self.principal.botones:
            self.principal.mostrar_modulo("configuracion")

    def _registrar_actividad(self, _evento: object = None) -> None:
        self._ultima_actividad = time.monotonic()

    def _vigilar_inactividad(self) -> None:
        self.after(10_000, self._vigilar_inactividad)
        if self.usuario is None:
            return
        if sesion_expirada(time.monotonic() - self._ultima_actividad, self.inactividad_minutos):
            self.salir(por_inactividad=True)

    # ---- acciones -------------------------------------------------------------------

    def entrar(self, correo: str, clave: str) -> None:
        """Lanza ``ErrorDeNegocio`` si las credenciales no son válidas."""
        with sesion_transaccional(self.fabrica) as sesion:
            usuario = iniciar_sesion(sesion, correo, clave)
            self.usuario = datos_de_sesion(sesion, usuario)
        self._cargar_valores_guardados()
        self._ultima_actividad = time.monotonic()
        self.aviso_login = ""
        self.mostrar_principal()

    def salir(self, por_inactividad: bool = False) -> None:
        if self.usuario is not None:
            with sesion_transaccional(self.fabrica) as sesion:
                cerrar_sesion(sesion, self.usuario.id)
                if por_inactividad:
                    registrar_expiracion(sesion, self.usuario.id, self.inactividad_minutos)
        self.usuario = None
        self.principal = None
        self.aviso_login = "Sesión cerrada por inactividad." if por_inactividad else ""
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
        if app.aviso_login:
            self.mensaje.configure(text=app.aviso_login, text_color=tema.NARANJA)
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


# (clave, icono, texto, módulo cuyo permiso lo habilita; None = siempre)
MENU = [
    ("inicio", "🏠", "Inicio", None),
    ("productos", "📦", "Productos", "productos"),
    ("ventas", "🛒", "Ventas", "ventas"),
    ("inventario", "🏬", "Inventario", "inventario"),
    ("clientes", "👥", "Clientes", "ventas"),
    ("proveedores", "🚚", "Proveedores", "inventario"),
    ("gastos", "💸", "Gastos", "gastos"),
    ("reportes", "📊", "Reportes", "reportes"),
    ("usuarios", "🔐", "Usuarios", "usuarios"),
    ("bitacora", "📜", "Bitácora", "bitacora"),
    ("configuracion", "⚙️", "Configuración", "configuracion"),
]


class PantallaPrincipal(ctk.CTkFrame):
    def __init__(self, app: Aplicacion) -> None:
        super().__init__(app, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        assert usuario is not None
        self._reloj_id: str | None = None

        self._armar_encabezado(app, usuario)

        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True)
        menu = ctk.CTkFrame(cuerpo, width=200, corner_radius=0, fg_color=tema.SUPERFICIE)
        menu.pack(side="left", fill="y")
        menu.pack_propagate(False)

        # El menú solo ofrece los módulos para los que el usuario tiene algún permiso.
        self.botones: dict[str, ctk.CTkButton] = {}
        habilitados = [m for m in MENU if m[3] is None or m[3] in usuario.modulos]
        for clave, icono, texto, _ in habilitados if usuario.modulos else []:
            boton = ctk.CTkButton(
                menu, text=f"  {icono}   {texto}", anchor="w", height=40, corner_radius=8,
                fg_color="transparent", hover_color=tema.SUPERFICIE_2, text_color=tema.TEXTO,
                font=tema.fuente(14), command=lambda c=clave: self.mostrar_modulo(c),
            )
            boton.pack(fill="x", padx=10, pady=2)
            self.botones[clave] = boton

        ctk.CTkButton(
            menu, text="Cerrar sesión", fg_color="transparent", border_width=1, border_color=tema.BORDE,
            text_color=tema.TEXTO_SUAVE, hover_color=tema.SUPERFICIE_2, command=app.salir,
        ).pack(side="bottom", fill="x", padx=12, pady=16)

        self.contenido = ctk.CTkFrame(cuerpo, fg_color="transparent")
        self.contenido.pack(side="left", fill="both", expand=True, padx=18, pady=14)

        if usuario.modulos:
            self.mostrar_modulo("inicio")
        else:
            ctk.CTkLabel(
                self.contenido,
                text="Tu usuario no tiene módulos asignados.\nPide a un administrador que te dé acceso.",
            ).pack(expand=True)

    # ---- encabezado -----------------------------------------------------------------

    def _armar_encabezado(self, app: Aplicacion, usuario: SesionUsuario) -> None:
        barra = ctk.CTkFrame(self, fg_color=tema.SUPERFICIE, corner_radius=0, height=76)
        barra.pack(fill="x")
        barra.pack_propagate(False)

        logo = tema.cargar_logo(56)
        if logo is not None:
            ctk.CTkLabel(barra, text="", image=logo).pack(side="left", padx=(16, 4), pady=8)
        titulo = ctk.CTkFrame(barra, fg_color="transparent")
        titulo.pack(side="left", padx=12)
        ctk.CTkLabel(
            titulo, text=app.configuracion.nombre_empresa.upper(), font=tema.fuente(24, True), text_color=tema.ACENTO_HOVER
        ).pack(anchor="w", pady=(10, 0))
        if app.configuracion.eslogan:
            ctk.CTkLabel(
                titulo, text=app.configuracion.eslogan, font=tema.fuente(11), text_color=tema.TEXTO_SUAVE
            ).pack(anchor="w")

        persona = ctk.CTkFrame(barra, fg_color=tema.SUPERFICIE_2, border_width=1, border_color=tema.BORDE, corner_radius=10)
        persona.pack(side="right", padx=(8, 16), pady=10)
        ctk.CTkLabel(persona, text="👤", font=tema.fuente(22)).pack(side="left", padx=(10, 6))
        datos = ctk.CTkFrame(persona, fg_color="transparent")
        datos.pack(side="left", padx=(0, 12), pady=4)
        ctk.CTkLabel(datos, text=usuario.nombre, font=tema.fuente(13, True), anchor="w").pack(fill="x")
        ctk.CTkLabel(datos, text=usuario.rol.capitalize(), font=tema.fuente(11), text_color=tema.TEXTO_SUAVE, anchor="w").pack(fill="x")

        reloj = ctk.CTkFrame(barra, fg_color=tema.SUPERFICIE_2, border_width=1, border_color=tema.BORDE, corner_radius=10)
        reloj.pack(side="right", pady=10)
        self.fecha = ctk.CTkLabel(reloj, text="", font=tema.fuente(11), text_color=tema.TEXTO_SUAVE)
        self.fecha.pack(padx=14, pady=(4, 0))
        self.hora = ctk.CTkLabel(reloj, text="", font=tema.fuente(20, True))
        self.hora.pack(padx=14, pady=(0, 4))
        self._tic()

    def _tic(self) -> None:
        ahora = datetime.now()
        self.fecha.configure(text=tema.fecha_larga(ahora.date()))
        self.hora.configure(text=ahora.strftime("%I:%M:%S %p").lstrip("0"))
        self._reloj_id = self.after(1000, self._tic)

    def destroy(self) -> None:
        if self._reloj_id is not None:
            try:
                self.after_cancel(self._reloj_id)
            except Exception:  # noqa: BLE001
                pass
        super().destroy()

    # ---- navegación -----------------------------------------------------------------

    def mostrar_modulo(self, modulo: str) -> None:
        for widget in self.contenido.winfo_children():
            widget.destroy()
        for nombre, boton in self.botones.items():
            boton.configure(fg_color=tema.ACENTO if nombre == modulo else "transparent")

        if modulo == "inicio":
            from app.ui.inicio_pantalla import PantallaInicio

            pantalla: ctk.CTkFrame = PantallaInicio(self.contenido, self.app, self.mostrar_modulo)
        elif modulo == "productos":
            from app.ui.productos_pantalla import PantallaProductos

            pantalla = PantallaProductos(self.contenido, self.app)
        elif modulo == "ventas":
            from app.ui.ventas_pantalla import PantallaVentas

            pantalla = PantallaVentas(self.contenido, self.app)
        elif modulo == "inventario":
            from app.ui.inventario_pantalla import PantallaInventario

            pantalla = PantallaInventario(self.contenido, self.app)
        elif modulo == "clientes":
            from app.ui.clientes_pantalla import PantallaClientes

            pantalla = PantallaClientes(self.contenido, self.app)
        elif modulo == "proveedores":
            from app.ui.proveedores_pantalla import PantallaProveedores

            pantalla = PantallaProveedores(self.contenido, self.app)
        elif modulo == "gastos":
            from app.ui.gastos_pantalla import PantallaGastos

            pantalla = PantallaGastos(self.contenido, self.app)
        elif modulo == "reportes":
            from app.ui.reportes_pantalla import PantallaReportes

            pantalla = PantallaReportes(self.contenido, self.app)
        elif modulo == "usuarios":
            from app.ui.usuarios_pantalla import PantallaUsuarios

            pantalla = PantallaUsuarios(self.contenido, self.app)
        elif modulo == "bitacora":
            from app.ui.bitacora_pantalla import PantallaBitacora

            pantalla = PantallaBitacora(self.contenido, self.app)
        elif modulo == "configuracion":
            from app.ui.configuracion_pantalla import PantallaConfiguracion

            pantalla = PantallaConfiguracion(self.contenido, self.app)
        else:
            return
        pantalla.pack(fill="both", expand=True)


def abrir_aplicacion(motor: Engine) -> None:
    Aplicacion(motor).mainloop()
