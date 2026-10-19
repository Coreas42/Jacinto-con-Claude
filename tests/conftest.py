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
