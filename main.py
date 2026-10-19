"""Punto de entrada del sistema de inventario y ventas.

Uso:
    python main.py            Abre la aplicación de escritorio
    python main.py --migrar   Aplica las migraciones pendientes a la base de datos
    python main.py --salud    Verifica la base de datos y las migraciones (sin ventana)
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import crear_motor
from app.migraciones import migrar_a_ultima
from app.salud import verificar_salud


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description="Sistema de inventario y ventas")
    analizador.add_argument(
        "--migrar", action="store_true", help="aplica las migraciones pendientes"
    )
    analizador.add_argument(
        "--salud", action="store_true", help="verifica el estado del sistema y sale"
    )
    opciones = analizador.parse_args(argumentos)

    if opciones.migrar:
        migrar_a_ultima()
        print("Base de datos actualizada.")
        return 0

    motor = crear_motor()

    if opciones.salud:
        salud = verificar_salud(motor)
        print(json.dumps(salud, ensure_ascii=False, indent=2))
        return 0 if salud["estado"] == "ok" else 1

    from app.ui.aplicacion import abrir_aplicacion

    abrir_aplicacion(motor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
