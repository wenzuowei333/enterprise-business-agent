"""prepare CRM AI unified compatibility read model

Revision ID: 20260830_0200
Revises: 20260830_0100
Create Date: 2026-08-30 16:00:00
"""

from alembic import context, op

from app.services.global_ai_backfill_service import (
    enrich_legacy_crm_read_models,
    revert_legacy_crm_read_models,
)


revision = "20260830_0200"
down_revision = "20260830_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        enrich_legacy_crm_read_models(op.get_bind())


def downgrade() -> None:
    if not context.is_offline_mode():
        revert_legacy_crm_read_models(op.get_bind())
