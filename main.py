"""Punto de entrada del sistema de inventario y ventas.

Uso:
    python main.py            Abre la aplicación de escritorio
    python main.py --migrar   Aplica las migraciones pendientes a la base de datos
    python main.py --salud    Verifica la base de datos, las migraciones y el inventario (sin ventana)
    python main.py --respaldo Crea un respaldo de la base de datos SQLite
    python main.py --restaurar ARCHIVO   Restaura un respaldo (cierra la aplicación antes)
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import crear_motor
from app.migraciones import migrar_a_ultima
from app.salud import verificar_salud


def _respaldo_diario() -> None:
    """Un respaldo por día al abrir la aplicación (se desactiva con RESPALDO_AUTOMATICO=false)."""
    import os

    if os.getenv("RESPALDO_AUTOMATICO", "true").strip().lower() in {"0", "false", "no"}:
        return
    from app.respaldo import respaldo_automatico

    try:
        creado = respaldo_automatico()
        if creado:
            print(f"Respaldo diario creado: {creado}")
    except Exception as error:  # noqa: BLE001  (un respaldo fallido no debe impedir trabajar)
        print(f"Aviso: no se pudo crear el respaldo diario: {error}", file=sys.stderr)


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description="Sistema de inventario y ventas")
    analizador.add_argument(
        "--migrar", action="store_true", help="aplica las migraciones pendientes"
    )
    analizador.add_argument(
        "--salud", action="store_true", help="verifica el estado del sistema y sale"
    )
    analizador.add_argument("--respaldo", action="store_true", help="crea un respaldo y sale")
    analizador.add_argument("--restaurar", metavar="ARCHIVO", help="restaura la base desde un respaldo y sale")
    opciones = analizador.parse_args(argumentos)

    if opciones.respaldo or opciones.restaurar:
        from app.respaldo import crear_respaldo, restaurar_respaldo
        from app.servicios.errores import ErrorDeNegocio

        try:
            if opciones.respaldo:
                print(f"Respaldo creado: {crear_respaldo()}")
            else:
                seguridad = restaurar_respaldo(opciones.restaurar)
                print(f"Base restaurada. La versión anterior quedó guardada en: {seguridad}")
        except ErrorDeNegocio as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        return 0

    if opciones.migrar:
        migrar_a_ultima()
        print("Base de datos actualizada.")
        return 0

    motor = crear_motor()

    if opciones.salud:
        salud = verificar_salud(motor, revisar_inventario=True)
        print(json.dumps(salud, ensure_ascii=False, indent=2))
        return 0 if salud["estado"] == "ok" else 1

    _respaldo_diario()

    from app.ui.aplicacion import abrir_aplicacion

    abrir_aplicacion(motor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
