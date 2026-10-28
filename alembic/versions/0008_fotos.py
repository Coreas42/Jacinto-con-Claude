"""Fotos de producto: nombre del archivo guardado en la carpeta de fotos

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("productos") as lote:
        lote.add_column(sa.Column("foto", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("productos") as lote:
        lote.drop_column("foto")
