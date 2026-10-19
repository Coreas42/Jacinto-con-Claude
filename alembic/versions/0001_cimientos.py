"""Cimientos: sucursales y configuración

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sucursales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("direccion", sa.String(length=200), nullable=True),
        sa.Column("activa", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("creada_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sucursales")),
        sa.UniqueConstraint("nombre", name=op.f("uq_sucursales_nombre")),
    )
    op.create_table(
        "configuracion",
        sa.Column("clave", sa.String(length=80), nullable=False),
        sa.Column("valor", sa.String(length=255), nullable=False),
        sa.Column("descripcion", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("clave", name=op.f("pk_configuracion")),
    )


def downgrade() -> None:
    op.drop_table("configuracion")
    op.drop_table("sucursales")
