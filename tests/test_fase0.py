"""Pruebas de la Fase 0: configuración, migración inicial y salud."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.config import cargar_configuracion
from app.db import crear_motor
from app.migraciones import migrar_a_ultima
from app.salud import verificar_salud


def test_configuracion_lee_variables_de_entorno(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///otra.db")
    monkeypatch.setenv("NOMBRE_EMPRESA", "Ferretería Prueba")
    monkeypatch.setenv("SQL_DEBUG", "true")
    config = cargar_configuracion()
    assert config.database_url == "sqlite:///otra.db"
    assert config.nombre_empresa == "Ferretería Prueba"
    assert config.sql_debug is True


def test_migracion_inicial_en_base_vacia(url_bd):
    migrar_a_ultima(url_bd)
    motor = crear_motor(url_bd)
    tablas = set(inspect(motor).get_table_names())
    assert {"sucursales", "configuracion", "alembic_version"} <= tablas
    motor.dispose()


def test_migrar_dos_veces_no_destruye_datos(url_bd):
    migrar_a_ultima(url_bd)
    motor = crear_motor(url_bd)
    with motor.begin() as conexion:
        conexion.execute(text("INSERT INTO sucursales (nombre) VALUES ('Central')"))
    migrar_a_ultima(url_bd)  # segunda vez: debe ser inocua
    with motor.connect() as conexion:
        nombres = conexion.execute(text("SELECT nombre FROM sucursales")).scalars().all()
    assert nombres == ["Central"]
    motor.dispose()


def test_salud_ok_con_migraciones_al_dia(motor):
    salud = verificar_salud(motor)
    assert salud["estado"] == "ok"
    assert salud["base_de_datos"] == "conectada"
    assert salud["migracion_actual"] == salud["migracion_esperada"]


def test_salud_detecta_base_sin_migrar(url_bd):
    motor = crear_motor(url_bd)  # base vacía, sin migraciones
    salud = verificar_salud(motor)
    assert salud["estado"] == "error"
    assert "--migrar" in salud["detalle"]
    motor.dispose()


def test_salud_detecta_base_inaccesible(tmp_path):
    motor = crear_motor(f"sqlite:///{tmp_path / 'no_existe' / 'x.db'}")
    salud = verificar_salud(motor)
    assert salud["estado"] == "error"
    assert salud["base_de_datos"] == "sin conexión"
    motor.dispose()


def test_nombre_de_sucursal_es_unico(motor):
    with pytest.raises(IntegrityError):
        with motor.begin() as conexion:
            conexion.execute(text("INSERT INTO sucursales (nombre) VALUES ('Central')"))
            conexion.execute(text("INSERT INTO sucursales (nombre) VALUES ('Central')"))


def test_llaves_foraneas_activas_en_sqlite(motor):
    with motor.connect() as conexion:
        assert conexion.execute(text("PRAGMA foreign_keys")).scalar() == 1
