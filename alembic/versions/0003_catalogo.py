"""Catálogo: categorías, productos e historial de cambios

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categorias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=80), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categorias")),
        sa.UniqueConstraint("nombre", name=op.f("uq_categorias_nombre")),
    )
    op.create_table(
        "productos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("codigo_barras", sa.String(length=50), nullable=True),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("categoria_id", sa.Integer(), nullable=False),
        sa.Column("marca", sa.String(length=80), nullable=True),
        sa.Column("costo_promedio", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("precio", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("stock_minimo", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["categoria_id"], ["categorias.id"], name=op.f("fk_productos_categoria_id_categorias")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_productos")),
        sa.UniqueConstraint("sku", name=op.f("uq_productos_sku")),
        sa.UniqueConstraint("codigo_barras", name=op.f("uq_productos_codigo_barras")),
    )
    op.create_table(
        "historial_productos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("campo", sa.String(length=30), nullable=False),
        sa.Column("valor_anterior", sa.String(length=100), nullable=True),
        sa.Column("valor_nuevo", sa.String(length=100), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_historial_productos_producto_id_productos")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_historial_productos_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historial_productos")),
    )


def downgrade() -> None:
    op.drop_table("historial_productos")
    op.drop_table("productos")
    op.drop_table("categorias")
