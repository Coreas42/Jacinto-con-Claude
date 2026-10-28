"""Pruebas de la Fase 7f: arranque preparado para el programa empaquetado (.exe)."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.modelos import Permiso

RAIZ = Path(__file__).resolve().parent.parent


def test_preparar_base_deja_los_permisos_y_se_puede_repetir(motor):
    from main import _preparar_base

    _preparar_base(motor)
    _preparar_base(motor)
    from app.db import crear_fabrica_sesiones

    with crear_fabrica_sesiones(motor)() as sesion:
        assert sesion.scalar(select(func.count()).select_from(Permiso)) > 0


def test_la_autoprueba_pasa_con_una_base_temporal(tmp_path, monkeypatch):
    import app.config
    from main import _autoprueba

    monkeypatch.setattr(app.config, "DIRECTORIO_DATOS", tmp_path)
    assert _autoprueba(modulos_ui=[]) == 0
    informe = (tmp_path / "autoprueba.txt").read_text(encoding="utf-8")
    assert "migraciones: OK" in informe and "inicio de sesión (argon2): OK" in informe
    assert "RESULTADO: OK" in informe


def test_empaquetado_guarda_los_datos_fuera_del_programa(tmp_path):
    """Simula PyInstaller (``sys.frozen``): base, respaldos y fotos van a la carpeta de datos."""
    codigo = (
        "import sys; sys.frozen = True; sys._MEIPASS = %r\n"
        "import app.config as c, os\n"
        "from app.respaldo import carpeta_de_respaldos\n"
        "from app.servicios.fotos import carpeta_fotos\n"
        "print(c.DIRECTORIO_DATOS); print(c.RUTA_MIGRACIONES); print(os.environ['DATABASE_URL'])\n"
        "print(carpeta_de_respaldos()); print(carpeta_fotos())\n"
    ) % str(RAIZ)
    entorno = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "CARPETA_RESPALDOS", "CARPETA_FOTOS")}
    entorno["INVENTARIO_DATOS"] = str(tmp_path)
    salida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, env=entorno, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    datos, migraciones, url, respaldos, fotos = salida
    assert Path(datos) == tmp_path
    assert Path(migraciones) == RAIZ / "migraciones"
    assert url.startswith("sqlite:///") and url.endswith("/inventario.db") and str(tmp_path.as_posix()) in url
    assert Path(respaldos) == tmp_path / "respaldos" and Path(fotos) == tmp_path / "fotos"


def test_sin_empaquetar_todo_sigue_donde_siempre():
    import app.config as c

    assert c.EMPAQUETADO is False
    assert c.DIRECTORIO_DATOS == c.RAIZ_PROYECTO and c.RUTA_MIGRACIONES == c.RAIZ_PROYECTO / "alembic"
