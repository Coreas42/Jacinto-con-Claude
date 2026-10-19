"""Datos iniciales: permisos, roles, una sucursal y el primer administrador.

Uso:
    python seed.py

Variables opcionales (también se leen del archivo .env):
    ADMIN_NOMBRE       nombre del administrador (por defecto "Administrador")
    ADMIN_CORREO       correo de acceso (por defecto "admin@ejemplo.com")
    ADMIN_CONTRASENA   contraseña; si no se define, se pide por consola y, si se
                       deja vacía, se genera una aleatoria y se muestra una sola vez.

Se puede ejecutar varias veces: no duplica ni modifica lo que ya existe.
"""

from __future__ import annotations

import getpass
import os
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import crear_fabrica_sesiones, crear_motor, sesion_transaccional
from app.migraciones import migrar_a_ultima
from app.modelos import Sucursal, Usuario
from app.servicios.permisos import sembrar_permisos_y_roles
from app.servicios.usuarios import crear_administrador_inicial


def sembrar(sesion: Session, nombre: str, correo: str, clave: str) -> Usuario | None:
    """Siembra lo básico. Devuelve el administrador creado, o ``None`` si ya existía."""
    sembrar_permisos_y_roles(sesion)

    if sesion.scalar(select(Sucursal.id).limit(1)) is None:
        sesion.add(Sucursal(nombre="Principal"))

    correo = correo.strip().lower()
    if sesion.scalar(select(Usuario.id).where(Usuario.correo == correo)) is not None:
        return None
    return crear_administrador_inicial(sesion, nombre, correo, clave)


def _obtener_clave() -> tuple[str, bool]:
    """Devuelve (clave, fue_generada)."""
    clave = os.getenv("ADMIN_CONTRASENA", "")
    if not clave and sys.stdin.isatty():
        clave = getpass.getpass("Contraseña del administrador (Enter para generar una): ")
    if clave:
        return clave, False
    return secrets.token_urlsafe(12), True


def main() -> int:
    from app.config import cargar_configuracion  # noqa: F401  (carga .env)

    migrar_a_ultima()
    nombre = os.getenv("ADMIN_NOMBRE", "Administrador")
    correo = os.getenv("ADMIN_CORREO", "admin@ejemplo.com")
    clave, generada = _obtener_clave()

    motor = crear_motor()
    fabrica = crear_fabrica_sesiones(motor)
    with sesion_transaccional(fabrica) as sesion:
        admin = sembrar(sesion, nombre, correo, clave)

    if admin is None:
        print(f"Permisos y roles al día. El administrador {correo} ya existía; no se modificó.")
        return 0

    print(f"Administrador creado: {correo}")
    if generada:
        print(f"Contraseña generada (guárdala, no se vuelve a mostrar): {clave}")
    print("IMPORTANTE: cambia esta contraseña después del primer ingreso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
