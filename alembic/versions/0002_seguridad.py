"""Seguridad: usuarios, roles, permisos y bitácora

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=50), nullable=False),
        sa.Column("descripcion", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("nombre", name=op.f("uq_roles_nombre")),
    )
    op.create_table(
        "permisos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("modulo", sa.String(length=50), nullable=False),
        sa.Column("accion", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permisos")),
        sa.UniqueConstraint("modulo", "accion", name=op.f("uq_permisos_modulo")),
    )
    op.create_table(
        "roles_permisos",
        sa.Column("rol_id", sa.Integer(), nullable=False),
        sa.Column("permiso_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rol_id"], ["roles.id"], name=op.f("fk_roles_permisos_rol_id_roles")
        ),
        sa.ForeignKeyConstraint(
            ["permiso_id"], ["permisos.id"], name=op.f("fk_roles_permisos_permiso_id_permisos")
        ),
        sa.PrimaryKeyConstraint("rol_id", "permiso_id", name=op.f("pk_roles_permisos")),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("correo", sa.String(length=150), nullable=False),
        sa.Column("hash_contrasena", sa.String(length=255), nullable=False),
        sa.Column("rol_id", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["rol_id"], ["roles.id"], name=op.f("fk_usuarios_rol_id_roles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
        sa.UniqueConstraint("correo", name=op.f("uq_usuarios_correo")),
    )
    op.create_table(
        "usuarios_permisos",
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("permiso_id", sa.Integer(), nullable=False),
        sa.Column("concedido", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_usuarios_permisos_usuario_id_usuarios")
        ),
        sa.ForeignKeyConstraint(
            ["permiso_id"], ["permisos.id"], name=op.f("fk_usuarios_permisos_permiso_id_permisos")
        ),
        sa.PrimaryKeyConstraint("usuario_id", "permiso_id", name=op.f("pk_usuarios_permisos")),
    )
    op.create_table(
        "bitacora_auditoria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("accion", sa.String(length=60), nullable=False),
        sa.Column("entidad", sa.String(length=60), nullable=True),
        sa.Column("entidad_id", sa.Integer(), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_bitacora_auditoria_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bitacora_auditoria")),
    )


def downgrade() -> None:
    op.drop_table("bitacora_auditoria")
    op.drop_table("usuarios_permisos")
    op.drop_table("usuarios")
    op.drop_table("roles_permisos")
    op.drop_table("permisos")
    op.drop_table("roles")
