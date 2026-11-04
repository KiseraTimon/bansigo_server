"""add social auth and firebase federation fields

Revision ID: c1a2b3d4e5f6
Revises: bf929eee8fd4
Create Date: 2026-11-04 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'bf929eee8fd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to accommodate Google, Facebook, and Firebase authentication."""
    op.add_column('users', sa.Column('auth_provider', sa.String(length=20), server_default='local', nullable=False))
    op.add_column('users', sa.Column('firebase_uid', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_users_firebase_uid'), 'users', ['firebase_uid'], unique=True)
    op.alter_column('users', 'phone', existing_type=sa.String(length=30), nullable=True)
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
    op.alter_column('users', 'phone', existing_type=sa.String(length=30), nullable=False)
    op.drop_index(op.f('ix_users_firebase_uid'), table_name='users')
    op.drop_column('users', 'firebase_uid')
    op.drop_column('users', 'auth_provider')
