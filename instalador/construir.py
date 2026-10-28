"""Empaqueta la aplicación como programa de Windows con PyInstaller (carpeta ``dist/Inventario``).

Uso (en Windows, con las dependencias y ``pyinstaller`` instalados):

    python instalador/construir.py

El programa resultante guarda su base de datos, respaldos y fotos en ``%LOCALAPPDATA%\\Inventario``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import PyInstaller.__main__

RAIZ = Path(__file__).resolve().parent.parent
SEPARADOR = os.pathsep  # ";" en Windows, ":" en Linux/macOS


def main() -> int:
    os.chdir(RAIZ)
    PyInstaller.__main__.run(
        [
            "main.py",
            "--noconfirm",
            "--clean",
            "--windowed",  # sin ventana de consola
            "--name", "Inventario",
            "--paths", str(RAIZ),
            # Piezas que PyInstaller no siempre detecta solo:
            "--collect-all", "customtkinter",
            "--collect-all", "argon2",
            "--collect-all", "_argon2_cffi_bindings",
            "--collect-submodules", "alembic",
            "--collect-submodules", "app",
            "--hidden-import", "seed",
            # env.py y las migraciones se cargan como archivos (no como módulos), así que PyInstaller
            # no ve lo que importan: se declaran aquí.
            "--hidden-import", "logging.config",
            "--hidden-import", "logging.handlers",
            "--hidden-import", "sqlite3",
            "--collect-submodules", "sqlalchemy.dialects.sqlite",
            # Recursos del programa. Las migraciones van en «migraciones» para no chocar con el paquete alembic.
            "--add-data", f"alembic{SEPARADOR}migraciones",
            "--add-data", f"alembic.ini{SEPARADOR}.",
            "--add-data", f"assets{SEPARADOR}assets",
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
