"""Initial schema — all v3.1 models

Revision ID: 3d18d54d005c
Revises: 
Create Date: 2026-03-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '3d18d54d005c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === users ===
    op.create_table(
        'users',
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='viewer'),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_approved', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('totp_secret_enc', sa.Text(), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # === api_keys ===
    op.create_table(
        'api_keys',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False),
        sa.Column('key_prefix', sa.String(10), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_api_keys_user_id', 'api_keys', ['user_id'])

    # === connections ===
    op.create_table(
        'connections',
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('db_type', sa.String(50), nullable=False),
        sa.Column('host', sa.String(500), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('database_name', sa.String(255), nullable=True),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False),
        sa.Column('ssl_mode', sa.String(50), nullable=False, server_default=sa.text("'require'")),
        sa.Column('query_timeout', sa.Integer(), nullable=False, server_default=sa.text('30')),
        sa.Column('max_rows', sa.Integer(), nullable=False, server_default=sa.text('10000')),
        sa.Column('max_result_bytes', sa.Integer(), nullable=False, server_default=sa.text('52428800')),
        sa.Column('allowed_schemas', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('pool_min_size', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('pool_max_size', sa.Integer(), nullable=False, server_default=sa.text('5')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )

    # === llm_providers ===
    op.create_table(
        'llm_providers',
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('provider_type', sa.String(50), nullable=False),
        sa.Column('encrypted_api_key', sa.Text(), nullable=True),
        sa.Column('base_url', sa.String(500), nullable=True),
        sa.Column('model_sql', sa.String(100), nullable=False),
        sa.Column('model_insight', sa.String(100), nullable=True),
        sa.Column('model_suggestion', sa.String(100), nullable=True),
        sa.Column('max_tokens_sql', sa.Integer(), nullable=False, server_default=sa.text('2048')),
        sa.Column('max_tokens_insight', sa.Integer(), nullable=False, server_default=sa.text('1024')),
        sa.Column('temperature_sql', sa.Float(), nullable=False, server_default=sa.text('0.1')),
        sa.Column('temperature_insight', sa.Float(), nullable=False, server_default=sa.text('0.3')),
        sa.Column('data_residency', sa.String(20), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text('99')),
        sa.Column('daily_token_budget', sa.Integer(), nullable=False, server_default=sa.text('1000000')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # === notification_platforms ===
    op.create_table(
        'notification_platforms',
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('platform_type', sa.String(50), nullable=False),
        sa.Column('encrypted_config', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_inbound_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_outbound_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )

    # === platform_user_mappings ===
    op.create_table(
        'platform_user_mappings',
        sa.Column('platform_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform_user_id', sa.String(255), nullable=False),
        sa.Column('internal_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['platform_id'], ['notification_platforms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['internal_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('platform_id', 'platform_user_id', name='uq_platform_user'),
    )

    # === role_permissions ===
    op.create_table(
        'role_permissions',
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('allowed_tables', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('denied_columns', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
    )

    # === department_permissions ===
    op.create_table(
        'department_permissions',
        sa.Column('department', sa.String(100), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('allowed_tables', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('denied_columns', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
    )

    # === user_permissions ===
    op.create_table(
        'user_permissions',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('allowed_tables', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('denied_tables', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('denied_columns', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
    )

    # === audit_logs ===
    op.create_table(
        'audit_logs',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('llm_provider_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('notification_platform_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('request_id', sa.String(50), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('generated_sql', sa.Text(), nullable=True),
        sa.Column('execution_status', sa.String(50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('result_bytes', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('llm_provider_type', sa.String(50), nullable=True),
        sa.Column('llm_model_used', sa.String(100), nullable=True),
        sa.Column('llm_tokens_used', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('prev_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        comment='Append-only: NO UPDATE/DELETE privileges for app user',
    )
    op.create_index('idx_audit_user', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_created', 'audit_logs', ['created_at'])
    op.create_index('idx_audit_status', 'audit_logs', ['execution_status'])

    # === saved_queries ===
    op.create_table(
        'saved_queries',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('sql_query', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('sensitivity', sa.String(20), nullable=False, server_default=sa.text("'normal'")),
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id']),
    )

    # === conversations ===
    op.create_table(
        'conversations',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id']),
    )

    # === conversation_messages ===
    op.create_table(
        'conversation_messages',
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('question', sa.Text(), nullable=True),
        sa.Column('sql_query', sa.Text(), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('chart_config', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    )

    # === schedules ===
    op.create_table(
        'schedules',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('saved_query_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('cron_expression', sa.String(100), nullable=False),
        sa.Column('timezone', sa.String(100), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column('output_format', sa.String(20), nullable=False, server_default=sa.text("'csv'")),
        sa.Column('delivery_targets', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_status', sa.String(50), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['saved_query_id'], ['saved_queries.id'], ondelete='SET NULL'),
    )

    # === llm_token_usage ===
    op.create_table(
        'llm_token_usage',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('llm_provider_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('date', sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column('tokens_used', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('query_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['llm_provider_id'], ['llm_providers.id']),
        sa.UniqueConstraint('user_id', 'llm_provider_id', 'date', name='uq_token_usage_daily'),
    )

    # === key_rotation_registry ===
    op.create_table(
        'key_rotation_registry',
        sa.Column('key_purpose', sa.String(50), nullable=False),
        sa.Column('key_version', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('key_rotation_registry')
    op.drop_table('llm_token_usage')
    op.drop_table('schedules')
    op.drop_table('conversation_messages')
    op.drop_table('conversations')
    op.drop_table('saved_queries')
    op.drop_index('idx_audit_status', 'audit_logs')
    op.drop_index('idx_audit_created', 'audit_logs')
    op.drop_index('idx_audit_user', 'audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('user_permissions')
    op.drop_table('department_permissions')
    op.drop_table('role_permissions')
    op.drop_table('platform_user_mappings')
    op.drop_table('notification_platforms')
    op.drop_table('llm_providers')
    op.drop_table('connections')
    op.drop_table('api_keys')
    op.drop_index('ix_users_email', 'users')
    op.drop_table('users')
