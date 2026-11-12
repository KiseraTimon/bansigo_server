"""add delivery routing and waypoint fields

Revision ID: d2b3c4d5e6f7
Revises: c1a2b3d4e5f6
Create Date: 2026-11-05 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade deliveries table with routing engine and waypoint fields."""
    op.add_column('deliveries', sa.Column('routing_algorithm', sa.String(length=30), nullable=True))
    op.add_column('deliveries', sa.Column('route_waypoints', sa.Text(), nullable=True))
    op.add_column('deliveries', sa.Column('pickup_latitude', sa.Numeric(precision=9, scale=6), nullable=True))
    op.add_column('deliveries', sa.Column('pickup_longitude', sa.Numeric(precision=9, scale=6), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('deliveries', 'pickup_longitude')
    op.drop_column('deliveries', 'pickup_latitude')
    op.drop_column('deliveries', 'route_waypoints')
    op.drop_column('deliveries', 'routing_algorithm')
