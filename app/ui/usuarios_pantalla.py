"""Pantalla de administración de usuarios, roles y permisos individuales."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import CATALOGO, NOMBRES_MODULOS
from app.servicios.usuarios import (
    cambiar_rol,
    crear_usuario,
    detalle_permisos,
    establecer_activo,
    establecer_permiso_individual,
    listar_roles,
    listar_usuarios,
    obtener_usuario,
    restablecer_contrasena,
)

ROJO = "#d64545"
VERDE = "#2e9e5b"

SEGUN_ROL, CONCEDER, DENEGAR = "Según el rol", "Conceder", "Denegar"
OPCION_A_VALOR = {SEGUN_ROL: None, CONCEDER: True, DENEGAR: False}
VALOR_A_OPCION = {valor: opcion for opcion, valor in OPCION_A_VALOR.items()}


class PantallaUsuarios(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.puede_crear = app.usuario.puede("usuarios", "crear")
        self.puede_editar = app.usuario.puede("usuarios", "editar")

        ctk.CTkLabel(
            self, text="Usuarios y permisos", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 10))

        _, roles = self.ejecutar(lambda sesion, actor: listar_roles(sesion))
        self.roles: list[str] = roles or []

        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        if self.puede_crear:
            self._construir_formulario()
        self.mensaje.pack(fill="x", pady=6)

        self.lista = ctk.CTkScrollableFrame(self)
        self.lista.pack(fill="both", expand=True)
        self.recargar()

    # ---- utilidades -----------------------------------------------------------------

    def ejecutar(self, funcion: Callable[[Any, Any], Any], exito: str | None = None) -> tuple[bool, Any]:
        """Corre ``funcion(sesion, actor)`` en una transacción y muestra el resultado.

        El ``actor`` se toma siempre de la sesión de la aplicación, nunca de un campo.
        """
        try:
            with sesion_transaccional(self.app.fabrica) as sesion:
                actor = obtener_usuario(sesion, self.app.usuario.id)
                resultado = funcion(sesion, actor)
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            return False, None
        if exito:
            self.mensaje.configure(text=exito, text_color=VERDE)
        return True, resultado

    # ---- formulario de alta ---------------------------------------------------------

    def _construir_formulario(self) -> None:
        marco = ctk.CTkFrame(self)
        marco.pack(fill="x")
        self.nombre = ctk.CTkEntry(marco, width=170, placeholder_text="Nombre")
        self.correo = ctk.CTkEntry(marco, width=200, placeholder_text="Correo")
        self.clave = ctk.CTkEntry(marco, width=150, placeholder_text="Contraseña", show="•")
        self.rol = ctk.CTkOptionMenu(marco, values=self.roles or ["—"], width=130)
        if "vendedor" in self.roles:
            self.rol.set("vendedor")
        for widget in (self.nombre, self.correo, self.clave, self.rol):
            widget.pack(side="left", padx=6, pady=10)
        ctk.CTkButton(marco, text="Crear usuario", width=110, command=self.crear).pack(
            side="left", padx=6
        )

    def crear(self) -> None:
        ok, _ = self.ejecutar(
            lambda sesion, actor: crear_usuario(
                sesion,
                actor,
                self.nombre.get(),
                self.correo.get(),
                self.clave.get(),
                self.rol.get(),
            ),
            exito="Usuario creado.",
        )
        if ok:
            for campo in (self.nombre, self.correo, self.clave):
                campo.delete(0, "end")
            self.recargar()

    # ---- lista ----------------------------------------------------------------------

    def recargar(self) -> None:
        ok, filas = self.ejecutar(lambda sesion, actor: listar_usuarios(sesion, actor))
        for widget in self.lista.winfo_children():
            widget.destroy()
        if not ok:
            return

        negrita = ctk.CTkFont(weight="bold")
        for columna, titulo in enumerate(["Nombre", "Correo", "Rol", "Estado", ""]):
            ctk.CTkLabel(self.lista, text=titulo, font=negrita).grid(
                row=0, column=columna, padx=8, pady=4, sticky="w"
            )

        for fila, usuario in enumerate(filas, start=1):
            es_yo = usuario["id"] == self.app.usuario.id
            ctk.CTkLabel(self.lista, text=usuario["nombre"]).grid(row=fila, column=0, padx=8, sticky="w")
            ctk.CTkLabel(self.lista, text=usuario["correo"]).grid(row=fila, column=1, padx=8, sticky="w")

            menu_rol = ctk.CTkOptionMenu(
                self.lista,
                values=self.roles or [usuario["rol"]],
                width=130,
                command=lambda valor, uid=usuario["id"]: self.cambiar_rol(uid, valor),
            )
            menu_rol.set(usuario["rol"])
            if not self.puede_editar or es_yo:
                menu_rol.configure(state="disabled")
            menu_rol.grid(row=fila, column=2, padx=8, pady=3, sticky="w")

            ctk.CTkLabel(
                self.lista,
                text="Activo" if usuario["activo"] else "Inactivo",
                text_color=VERDE if usuario["activo"] else ROJO,
            ).grid(row=fila, column=3, padx=8, sticky="w")

            acciones = ctk.CTkFrame(self.lista, fg_color="transparent")
            acciones.grid(row=fila, column=4, padx=8, sticky="w")
            boton_estado = ctk.CTkButton(
                acciones,
                text="Desactivar" if usuario["activo"] else "Activar",
                width=90,
                command=lambda u=usuario: self.alternar_activo(u),
            )
            boton_permisos = ctk.CTkButton(
                acciones,
                text="Permisos",
                width=80,
                command=lambda u=usuario: DialogoPermisos(self, self.app, u["id"], u["nombre"]),
            )
            boton_clave = ctk.CTkButton(
                acciones,
                text="Nueva clave",
                width=90,
                command=lambda u=usuario: DialogoClave(self, u["id"], u["nombre"]),
            )
            if not self.puede_editar or es_yo:
                for boton in (boton_estado, boton_permisos, boton_clave):
                    boton.configure(state="disabled")
            for boton in (boton_estado, boton_permisos, boton_clave):
                boton.pack(side="left", padx=2)

    def cambiar_rol(self, usuario_id: int, rol: str) -> None:
        self.ejecutar(
            lambda sesion, actor: cambiar_rol(sesion, actor, usuario_id, rol),
            exito="Rol actualizado.",
        )
        self.recargar()

    def alternar_activo(self, usuario: dict) -> None:
        nuevo = not usuario["activo"]
        self.ejecutar(
            lambda sesion, actor: establecer_activo(sesion, actor, usuario["id"], nuevo),
            exito="Usuario activado." if nuevo else "Usuario desactivado.",
        )
        self.recargar()


class DialogoPermisos(ctk.CTkToplevel):
    """Permite conceder o quitar permisos puntuales sobre lo que da el rol."""

    def __init__(self, pantalla: PantallaUsuarios, app: Any, usuario_id: int, nombre: str) -> None:
        super().__init__(pantalla)
        self.pantalla = pantalla
        self.usuario_id = usuario_id
        self.title(f"Permisos de {nombre}")
        self.geometry("500x600")

        ok, detalle = pantalla.ejecutar(
            lambda sesion, actor: detalle_permisos(sesion, actor, usuario_id)
        )
        if not ok:
            self.destroy()
            return

        ctk.CTkLabel(
            self,
            text="«Según el rol» usa lo que ya da su rol. Conceder o Denegar lo cambia solo para este usuario.",
            wraplength=460,
            justify="left",
        ).pack(padx=16, pady=(14, 8))

        zona = ctk.CTkScrollableFrame(self)
        zona.pack(fill="both", expand=True, padx=12, pady=4)

        self.original: dict[tuple[str, str], bool | None] = {}
        self.menus: dict[tuple[str, str], ctk.CTkOptionMenu] = {}
        fila = 0
        for modulo, acciones in CATALOGO.items():
            ctk.CTkLabel(
                zona, text=NOMBRES_MODULOS[modulo], font=ctk.CTkFont(weight="bold")
            ).grid(row=fila, column=0, columnspan=2, sticky="w", pady=(10, 2))
            fila += 1
            for accion in acciones:
                clave = (modulo, accion)
                da_el_rol = "  ✓ en el rol" if clave in detalle["rol"] else ""
                ctk.CTkLabel(zona, text=f"{accion}{da_el_rol}").grid(
                    row=fila, column=0, sticky="w", padx=(12, 8)
                )
                menu = ctk.CTkOptionMenu(zona, values=list(OPCION_A_VALOR), width=130)
                valor = detalle["individuales"].get(clave)
                menu.set(VALOR_A_OPCION[valor])
                menu.grid(row=fila, column=1, pady=2)
                self.original[clave] = valor
                self.menus[clave] = menu
                fila += 1

        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=12)
        self.after(150, self._tomar_foco)

    def _tomar_foco(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001  (la ventana pudo cerrarse antes)
            pass

    def guardar(self) -> None:
        cambios = [
            (modulo, accion, OPCION_A_VALOR[menu.get()])
            for (modulo, accion), menu in self.menus.items()
            if OPCION_A_VALOR[menu.get()] != self.original[(modulo, accion)]
        ]

        def aplicar(sesion: Any, actor: Any) -> None:
            for modulo, accion, valor in cambios:
                establecer_permiso_individual(sesion, actor, self.usuario_id, modulo, accion, valor)

        ok, _ = self.pantalla.ejecutar(aplicar, exito=f"Permisos actualizados ({len(cambios)} cambios).")
        if ok:
            self.destroy()


class DialogoClave(ctk.CTkToplevel):
    def __init__(self, pantalla: PantallaUsuarios, usuario_id: int, nombre: str) -> None:
        super().__init__(pantalla)
        self.pantalla = pantalla
        self.usuario_id = usuario_id
        self.title(f"Nueva contraseña para {nombre}")
        self.geometry("360x190")
        self.clave = ctk.CTkEntry(self, width=260, placeholder_text="Nueva contraseña", show="•")
        self.clave.pack(pady=(28, 10))
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack()
        self.after(150, self._tomar_foco)

    def _tomar_foco(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001
            pass

    def guardar(self) -> None:
        ok, _ = self.pantalla.ejecutar(
            lambda sesion, actor: restablecer_contrasena(sesion, actor, self.usuario_id, self.clave.get()),
            exito="Contraseña actualizada.",
        )
        if ok:
            self.destroy()
