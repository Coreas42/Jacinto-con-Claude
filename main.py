"""Punto de entrada del sistema de inventario y ventas.

Uso:
    python main.py            Abre la aplicación de escritorio
    python main.py --migrar   Aplica las migraciones pendientes a la base de datos
    python main.py --salud    Verifica la base de datos, las migraciones y el inventario (sin ventana)
    python main.py --respaldo Crea un respaldo de la base de datos SQLite
    python main.py --restaurar ARCHIVO   Restaura un respaldo (cierra la aplicación antes)
    python main.py --autoprueba   Prueba de humo (base temporal); la usa la construcción del instalador

Al abrir la aplicación se aplican solas las migraciones pendientes y se crean los permisos nuevos,
así que actualizar a una versión nueva no requiere comandos extra.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.db import crear_fabrica_sesiones, crear_motor, sesion_transaccional
from app.migraciones import migrar_a_ultima
from app.salud import verificar_salud

# Módulos de la interfaz que la prueba de humo debe poder importar (detecta piezas que falten al empaquetar).
MODULOS_UI = [
    "customtkinter", "PIL", "app.ui.aplicacion", "app.ui.tema", "app.ui.comun",
    "app.ui.inicio_pantalla", "app.ui.productos_pantalla", "app.ui.inventario_pantalla",
    "app.ui.ventas_pantalla", "app.ui.clientes_pantalla", "app.ui.proveedores_pantalla",
    "app.ui.gastos_pantalla", "app.ui.reportes_pantalla", "app.ui.usuarios_pantalla",
    "app.ui.bitacora_pantalla", "app.ui.configuracion_pantalla",
]


def _respaldo_diario() -> None:
    """Un respaldo por día al abrir la aplicación (se desactiva con RESPALDO_AUTOMATICO=false)."""
    if os.getenv("RESPALDO_AUTOMATICO", "true").strip().lower() in {"0", "false", "no"}:
        return
    from app.respaldo import archivo_de_la_base, respaldo_automatico
    from app.servicios.errores import ErrorDeNegocio

    try:
        if not archivo_de_la_base().is_file():
            return  # primera vez: todavía no hay nada que respaldar
    except ErrorDeNegocio:
        pass  # no es SQLite: respaldo_automatico lo avisa
    try:
        creado = respaldo_automatico()
        if creado:
            print(f"Respaldo diario creado: {creado}")
    except Exception as error:  # noqa: BLE001  (un respaldo fallido no debe impedir trabajar)
        print(f"Aviso: no se pudo crear el respaldo diario: {error}", file=sys.stderr)


def _preparar_base(motor) -> None:
    """Deja la base al día: migraciones pendientes y permisos nuevos (ambos son seguros de repetir)."""
    from app.servicios.permisos import sembrar_permisos_y_roles

    migrar_a_ultima()
    with sesion_transaccional(crear_fabrica_sesiones(motor)) as sesion:
        sembrar_permisos_y_roles(sesion)


def _autoprueba(modulos_ui: list[str] | None = None) -> int:
    """Prueba de humo: base temporal, migraciones, administrador, inicio de sesión, salud e importación de la interfaz.

    Escribe el resultado en ``autoprueba.txt`` (el .exe no tiene consola). Devuelve 0 si todo salió bien.
    """
    import importlib
    import tempfile
    import traceback
    from pathlib import Path

    from app.config import DIRECTORIO_DATOS

    lineas: list[str] = []
    correcto = True
    try:
        # Windows no deja borrar un archivo SQLite mientras algún motor siga abierto: no es un fallo de la prueba.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporal:
            url = f"sqlite:///{(Path(temporal) / 'prueba.db').as_posix()}"
            migrar_a_ultima(url)
            lineas.append("migraciones: OK")
            motor = crear_motor(url)
            try:
                from app.servicios.autenticacion import iniciar_sesion
                from seed import sembrar

                fabrica = crear_fabrica_sesiones(motor)
                with sesion_transaccional(fabrica) as sesion:
                    sembrar(sesion, "Prueba", "prueba@local", "claveSegura1", con_ejemplos=False)
                lineas.append("administrador: OK")
                with sesion_transaccional(fabrica) as sesion:
                    iniciar_sesion(sesion, "prueba@local", "claveSegura1")
                lineas.append("inicio de sesión (argon2): OK")
                salud = verificar_salud(motor, revisar_inventario=True)
                lineas.append(f"salud: {salud['estado']}")
                correcto = salud["estado"] == "ok"
            finally:
                motor.dispose()
        for modulo in MODULOS_UI if modulos_ui is None else modulos_ui:
            importlib.import_module(modulo)
        lineas.append("interfaz: OK")
    except Exception:  # noqa: BLE001
        correcto = False
        lineas.append(traceback.format_exc())
    lineas.append("RESULTADO: " + ("OK" if correcto else "FALLÓ"))
    try:
        (DIRECTORIO_DATOS / "autoprueba.txt").write_text("\n".join(lineas), encoding="utf-8")
    except OSError:
        pass
    print("\n".join(lineas))
    return 0 if correcto else 1


def _error_fatal(error: BaseException) -> None:
    """Sin consola (el .exe), un fallo al arrancar se guarda en ``error.log`` y se muestra en una ventana."""
    import traceback

    from app.config import DIRECTORIO_DATOS

    detalle = traceback.format_exc()
    try:
        (DIRECTORIO_DATOS / "error.log").write_text(detalle, encoding="utf-8")
    except OSError:
        pass
    try:
        from tkinter import Tk, messagebox

        raiz = Tk()
        raiz.withdraw()
        messagebox.showerror(
            "Inventario",
            f"No se pudo abrir el programa:\n\n{error}\n\nEl detalle quedó en:\n{DIRECTORIO_DATOS / 'error.log'}",
        )
        raiz.destroy()
    except Exception:  # noqa: BLE001
        print(detalle, file=sys.stderr)


def main(argumentos: list[str] | None = None) -> int:
    # El .exe sin consola no tiene stdout/stderr: se redirigen para que print() y los registros no fallen.
    for nombre in ("stdout", "stderr"):
        if getattr(sys, nombre) is None:
            setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8"))

    analizador = argparse.ArgumentParser(description="Sistema de inventario y ventas")
    analizador.add_argument(
        "--migrar", action="store_true", help="aplica las migraciones pendientes"
    )
    analizador.add_argument(
        "--salud", action="store_true", help="verifica el estado del sistema y sale"
    )
    analizador.add_argument("--autoprueba", action="store_true", help="prueba de humo con una base temporal y sale")
    analizador.add_argument("--respaldo", action="store_true", help="crea un respaldo y sale")
    analizador.add_argument("--restaurar", metavar="ARCHIVO", help="restaura la base desde un respaldo y sale")
    opciones = analizador.parse_args(argumentos)

    if opciones.autoprueba:
        return _autoprueba()

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

    try:
        _respaldo_diario()  # antes de migrar: así queda una copia de cómo estaba la base
        _preparar_base(motor)
        from app.ui.aplicacion import abrir_aplicacion

        abrir_aplicacion(motor)
    except Exception as error:  # noqa: BLE001
        _error_fatal(error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
