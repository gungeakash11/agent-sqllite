"""m2_document_chunks_and_progress_fields

Revision ID: 6cf4d8db879f
Revises: 943d567f7f9c
Create Date: 2026-07-14 01:33:43.433207

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6cf4d8db879f'
down_revision: Union[str, Sequence[str], None] = '943d567f7f9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_chunks table for M2 semantic chunking + embeddings
    op.create_table('document_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('review_job_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(1536), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_job_id'], ['review_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_review_job_id'), 'document_chunks', ['review_job_id'], unique=False)

    # Add M3 progress tracking columns to review_jobs
    op.add_column('review_jobs', sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('review_jobs', sa.Column('current_stage', sa.String(length=255), nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('review_jobs', 'current_stage')
    op.drop_column('review_jobs', 'progress_pct')
    op.drop_index(op.f('ix_document_chunks_review_job_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_table('document_chunks')
