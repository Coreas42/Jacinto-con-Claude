"""Servicios: productos que se venden sin controlar existencias

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("productos") as lote:
        lote.add_column(sa.Column("es_servicio", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("productos") as lote:
        lote.drop_column("es_servicio")
