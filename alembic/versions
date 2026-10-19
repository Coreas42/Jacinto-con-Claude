"""Entorno de Alembic: toma la URL de DATABASE_URL y los modelos de la app."""

from logging.config import fileConfig

from alembic import context

from app.config import cargar_configuracion
from app.db import Base, crear_motor
import app.modelos  # noqa: F401  (registra los modelos en Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Si quien llama fijó la URL (p. ej. las pruebas), se respeta.
    return config.get_main_option("sqlalchemy.url") or cargar_configuracion().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url().replace("%%", "%"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    motor = crear_motor(_url().replace("%%", "%"))
    with motor.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            # Necesario para que ALTER TABLE funcione en SQLite.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
