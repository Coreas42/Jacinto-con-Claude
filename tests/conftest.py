import os
import sys

import pytest

from app.db import crear_motor
from app.migraciones import migrar_a_ultima


@pytest.fixture()
def url_bd(tmp_path):
    """URL de una base SQLite vacía y temporal por cada prueba."""
    return f"sqlite:///{tmp_path / 'prueba.db'}"


@pytest.fixture()
def motor(url_bd):
    """Motor sobre una base vacía a la que ya se aplicaron las migraciones."""
    migrar_a_ultima(url_bd)
    motor = crear_motor(url_bd)
    yield motor
    motor.dispose()


# ---- fixtures compartidas de servicios (Fase 2 en adelante) ----------------------

from app.db import crear_fabrica_sesiones  # noqa: E402
from app.servicios.permisos import sembrar_permisos_y_roles  # noqa: E402
from app.servicios.usuarios import crear_administrador_inicial, crear_usuario  # noqa: E402

CLAVE_PRUEBA = "claveSegura1"


@pytest.fixture()
def sesion_servicios(motor):
    """Sesión con permisos y roles sembrados (sin usuarios)."""
    sesion = crear_fabrica_sesiones(motor)()
    sembrar_permisos_y_roles(sesion)
    sesion.commit()
    yield sesion
    sesion.close()


@pytest.fixture()
def administrador(sesion_servicios):
    usuario = crear_administrador_inicial(sesion_servicios, "Admin", "admin@x.com", CLAVE_PRUEBA)
    sesion_servicios.commit()
    return usuario


@pytest.fixture()
def crear_con_rol(sesion_servicios, administrador):
    """Devuelve una función ``crear_con_rol("vendedor")`` que crea un usuario con ese rol."""

    def _crear(rol: str):
        usuario = crear_usuario(
            sesion_servicios, administrador, f"Usuario {rol}", f"{rol}@x.com", CLAVE_PRUEBA, rol
        )
        sesion_servicios.commit()
        return usuario

    return _crear


# ---- en GitHub Actions, cada prueba fallida también se publica como anotación ----------
# (así el motivo se ve en la página de resumen de la corrida, sin abrir los registros)


def _escapar(texto: str) -> str:
    return texto.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def pytest_runtest_logreport(report):
    if os.getenv("GITHUB_ACTIONS") and report.failed:
        detalle = report.longreprtext.strip()[-700:]
        sys.__stdout__.write(f"\n::error title=Prueba fallida::{_escapar(report.nodeid + chr(10) + detalle)}\n")
        sys.__stdout__.flush()
