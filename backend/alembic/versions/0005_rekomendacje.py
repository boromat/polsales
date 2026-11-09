"""Etap 5 - rekomendacje: core.recommendations (z feedbackiem).

Revision ID: 0005_rekomendacje
Revises: 0004_asystent_ai
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
from app.db.base import Base
from app.db.models.recommendations import Recommendation

revision = "0005_rekomendacje"
down_revision = "0004_asystent_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=[Recommendation.__table__], checkfirst=True)
    op.execute(
        "ALTER TABLE core.recommendations ADD CONSTRAINT ck_rec_status "
        "CHECK (status IN ('active','archived','dismissed'))"
    )
    op.execute(
        "CREATE INDEX idx_rec_active ON core.recommendations (created_at DESC) WHERE status = 'active'"
    )
    op.execute("GRANT SELECT ON core.recommendations TO assistant_ro")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.recommendations CASCADE")
