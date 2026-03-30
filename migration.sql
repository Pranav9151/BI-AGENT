BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 3d18d54d005c

CREATE TABLE users (
    email VARCHAR(255) NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    hashed_password VARCHAR(255) NOT NULL, 
    role VARCHAR(50) DEFAULT 'analyst' NOT NULL, 
    department VARCHAR(100), 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    is_approved BOOLEAN DEFAULT 'false' NOT NULL, 
    totp_secret_enc TEXT, 
    totp_enabled BOOLEAN DEFAULT 'false' NOT NULL, 
    failed_login_attempts INTEGER DEFAULT '0' NOT NULL, 
    locked_until TIMESTAMP WITH TIME ZONE, 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_role ON users (role);

CREATE TABLE api_keys (
    user_id UUID NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    key_hash VARCHAR(255) NOT NULL, 
    key_prefix VARCHAR(10) NOT NULL, 
    last_used_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT 'now()' NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE connections (
    name VARCHAR(255) NOT NULL, 
    db_type VARCHAR(50) NOT NULL, 
    host VARCHAR(500), 
    port INTEGER, 
    database_name VARCHAR(255), 
    encrypted_credentials TEXT NOT NULL, 
    ssl_mode VARCHAR(50) DEFAULT 'require' NOT NULL, 
    query_timeout INTEGER DEFAULT '30' NOT NULL, 
    max_rows INTEGER DEFAULT '10000' NOT NULL, 
    max_result_bytes INTEGER DEFAULT '10485760' NOT NULL, 
    allowed_schemas TEXT[], 
    pool_min_size INTEGER DEFAULT '1' NOT NULL, 
    pool_max_size INTEGER DEFAULT '10' NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    created_by UUID, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE TABLE llm_providers (
    name VARCHAR(255) NOT NULL, 
    provider_type VARCHAR(50) NOT NULL, 
    encrypted_api_key TEXT, 
    base_url VARCHAR(500), 
    model_sql VARCHAR(100) NOT NULL, 
    model_insight VARCHAR(100) NOT NULL, 
    model_suggestion VARCHAR(100), 
    max_tokens_sql INTEGER DEFAULT '2000' NOT NULL, 
    max_tokens_insight INTEGER DEFAULT '500' NOT NULL, 
    temperature_sql FLOAT DEFAULT '0.0' NOT NULL, 
    temperature_insight FLOAT DEFAULT '0.3' NOT NULL, 
    data_residency VARCHAR(100), 
    priority INTEGER DEFAULT '100' NOT NULL, 
    daily_token_budget INTEGER, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    is_default BOOLEAN DEFAULT 'false' NOT NULL, 
    created_by UUID, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE TABLE notification_platforms (
    name VARCHAR(100) NOT NULL, 
    platform_type VARCHAR(50) NOT NULL, 
    encrypted_config TEXT NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    is_inbound_enabled BOOLEAN DEFAULT 'false' NOT NULL, 
    is_outbound_enabled BOOLEAN DEFAULT 'true' NOT NULL, 
    created_by UUID, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE TABLE role_permissions (
    role VARCHAR(50) NOT NULL, 
    connection_id UUID NOT NULL, 
    allowed_tables TEXT[] DEFAULT '{}' NOT NULL, 
    denied_columns TEXT[] DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id) ON DELETE CASCADE
);

CREATE TABLE department_permissions (
    department VARCHAR(100) NOT NULL, 
    connection_id UUID NOT NULL, 
    allowed_tables TEXT[] DEFAULT '{}' NOT NULL, 
    denied_columns TEXT[] DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id) ON DELETE CASCADE
);

CREATE TABLE user_permissions (
    user_id UUID NOT NULL, 
    connection_id UUID NOT NULL, 
    allowed_tables TEXT[] DEFAULT '{}' NOT NULL, 
    denied_tables TEXT[] DEFAULT '{}' NOT NULL, 
    denied_columns TEXT[] DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE audit_logs (
    user_id UUID, 
    connection_id UUID, 
    llm_provider_id UUID, 
    notification_platform_id UUID, 
    conversation_id UUID, 
    request_id VARCHAR(50), 
    question TEXT NOT NULL, 
    generated_sql TEXT, 
    execution_status VARCHAR(50) NOT NULL, 
    error_message TEXT, 
    row_count INTEGER, 
    result_bytes INTEGER, 
    duration_ms INTEGER, 
    llm_provider_type VARCHAR(50), 
    llm_model_used VARCHAR(100), 
    llm_tokens_used INTEGER, 
    ip_address VARCHAR(45), 
    prev_hash VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id), 
    FOREIGN KEY(llm_provider_id) REFERENCES llm_providers (id), 
    FOREIGN KEY(notification_platform_id) REFERENCES notification_platforms (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_execution_status ON audit_logs (execution_status);

CREATE TABLE saved_queries (
    user_id UUID NOT NULL, 
    connection_id UUID NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    description TEXT, 
    question TEXT NOT NULL, 
    sql_query TEXT NOT NULL, 
    tags TEXT[] DEFAULT '{}', 
    sensitivity VARCHAR(20) DEFAULT 'normal' NOT NULL, 
    is_shared BOOLEAN DEFAULT 'false' NOT NULL, 
    is_pinned BOOLEAN DEFAULT 'false' NOT NULL, 
    run_count INTEGER DEFAULT '0' NOT NULL, 
    last_run_at TIMESTAMP WITH TIME ZONE, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_saved_queries_user_id ON saved_queries (user_id);

CREATE INDEX ix_saved_queries_sensitivity ON saved_queries (sensitivity);

CREATE TABLE conversations (
    user_id UUID NOT NULL, 
    connection_id UUID NOT NULL, 
    title VARCHAR(255), 
    message_count INTEGER DEFAULT '0' NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES connections (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversations_user_id ON conversations (user_id);

CREATE TABLE conversation_messages (
    conversation_id UUID NOT NULL, 
    role VARCHAR(20) NOT NULL, 
    question TEXT, 
    sql_query TEXT, 
    result_summary TEXT, 
    row_count INTEGER, 
    duration_ms INTEGER, 
    chart_config JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversation_messages_conversation_id ON conversation_messages (conversation_id);

CREATE TABLE schedules (
    user_id UUID NOT NULL, 
    saved_query_id UUID NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    cron_expression VARCHAR(100) NOT NULL, 
    timezone VARCHAR(100) DEFAULT 'UTC' NOT NULL, 
    output_format VARCHAR(20) DEFAULT 'csv' NOT NULL, 
    delivery_targets JSONB DEFAULT '[]' NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    last_run_at TIMESTAMP WITH TIME ZONE, 
    last_run_status VARCHAR(50), 
    next_run_at TIMESTAMP WITH TIME ZONE, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(saved_query_id) REFERENCES saved_queries (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_schedules_user_id ON schedules (user_id);

CREATE INDEX ix_schedules_is_active ON schedules (is_active);

CREATE TABLE llm_token_usage (
    user_id UUID NOT NULL, 
    llm_provider_id UUID, 
    date DATE NOT NULL, 
    tokens_used INTEGER DEFAULT '0' NOT NULL, 
    query_count INTEGER DEFAULT '0' NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(llm_provider_id) REFERENCES llm_providers (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_token_usage_user_provider_date UNIQUE (user_id, llm_provider_id, date)
);

CREATE TABLE key_rotation_registry (
    key_purpose VARCHAR(50) NOT NULL, 
    key_version INTEGER NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    activated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    retired_at TIMESTAMP WITH TIME ZONE, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_key_rotation_purpose_version UNIQUE (key_purpose, key_version)
);

CREATE TABLE platform_user_mappings (
    platform_id UUID NOT NULL, 
    platform_user_id VARCHAR(255) NOT NULL, 
    internal_user_id UUID NOT NULL, 
    is_verified BOOLEAN DEFAULT 'false' NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID DEFAULT gen_random_uuid() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(internal_user_id) REFERENCES users (id) ON DELETE CASCADE, 
    FOREIGN KEY(platform_id) REFERENCES notification_platforms (id) ON DELETE CASCADE, 
    CONSTRAINT uq_platform_user UNIQUE (platform_id, platform_user_id)
);

INSERT INTO alembic_version (version_num) VALUES ('3d18d54d005c') RETURNING alembic_version.version_num;

COMMIT;
-- Phase 8: Settings & Dashboards

CREATE TABLE platform_settings (
    key VARCHAR(100) NOT NULL,
    value TEXT NOT NULL DEFAULT '{}',
    updated_by UUID,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_platform_settings_key UNIQUE (key),
    FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_platform_settings_key ON platform_settings (key);

CREATE TABLE dashboards (
    user_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    is_default BOOLEAN DEFAULT FALSE NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_dashboards_user_id ON dashboards (user_id);
