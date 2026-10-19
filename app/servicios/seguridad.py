"""Hash y verificación de contraseñas (argon2)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.servicios.errores import ErrorDeNegocio

LARGO_MINIMO_CLAVE = 8

_hasher = PasswordHasher()
_hash_falso: str | None = None


def validar_contrasena(clave: str) -> None:
    if len(clave) < LARGO_MINIMO_CLAVE:
        raise ErrorDeNegocio(
            f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres."
        )


def hashear_contrasena(clave: str) -> str:
    validar_contrasena(clave)
    return _hasher.hash(clave)


def verificar_contrasena(hash_guardado: str, clave: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, clave)
    except (VerificationError, InvalidHashError):
        return False


def verificar_contra_hash_falso(clave: str) -> None:
    """Gasta el mismo tiempo que una verificación real cuando el correo no existe,
    para que la demora no delate qué correos están registrados."""
    global _hash_falso
    if _hash_falso is None:
        _hash_falso = _hasher.hash("contrasena-de-relleno")
    verificar_contrasena(_hash_falso, clave)
