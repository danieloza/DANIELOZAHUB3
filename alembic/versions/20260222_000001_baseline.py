"""baseline

Revision ID: 20260222_000001
Revises:
Create Date: 2026-02-22 00:00:01
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260222_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Baseline migration for existing repositories that already use runtime migrations.
    # Future schema changes should be added as alembic revisions on top of this.
    pass


def downgrade() -> None:
    pass
