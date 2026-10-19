"""Errores de negocio. Sus mensajes están pensados para mostrarse al usuario."""

from __future__ import annotations


class ErrorDeNegocio(Exception):
    """Operación rechazada por una regla del sistema."""


class CredencialesInvalidas(ErrorDeNegocio):
    def __init__(self) -> None:
        # Mismo mensaje para correo inexistente y clave errónea: no revela cuál falló.
        super().__init__("Correo o contraseña incorrectos.")


class PermisoDenegado(ErrorDeNegocio):
    """Equivale a un 403 Forbidden."""

    codigo_http = 403

    def __init__(self, modulo: str, accion: str) -> None:
        self.modulo = modulo
        self.accion = accion
        super().__init__(f"No tienes permiso para '{accion}' en el módulo '{modulo}'.")
