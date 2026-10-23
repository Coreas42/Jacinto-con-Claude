"""Gastos del negocio

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gastos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("categoria", sa.String(length=30), nullable=False),
        sa.Column("descripcion", sa.String(length=200), nullable=False),
        sa.Column("monto", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("estado", sa.String(length=20), server_default="activo", nullable=False),
        sa.Column("anulado_por", sa.Integer(), nullable=True),
        sa.Column("anulado_en", sa.DateTime(), nullable=True),
        sa.Column("motivo_anulacion", sa.String(length=200), nullable=True),
        sa.CheckConstraint("monto > 0", name=op.f("ck_gastos_monto_positivo")),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], name=op.f("fk_gastos_sucursal_id_sucursales")),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_gastos_usuario_id_usuarios")),
        sa.ForeignKeyConstraint(["anulado_por"], ["usuarios.id"], name=op.f("fk_gastos_anulado_por_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gastos")),
    )
    op.create_index(op.f("ix_gastos_fecha"), "gastos", ["fecha"])


def downgrade() -> None:
    op.drop_index(op.f("ix_gastos_fecha"), table_name="gastos")
    op.drop_table("gastos")
