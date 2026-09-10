-- 001: full 31-table authority model. No passwords or login creation.

CREATE SCHEMA IF NOT EXISTS devplm;

REVOKE ALL ON SCHEMA devplm FROM PUBLIC;

DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='devplm_api') THEN CREATE ROLE devplm_api NOLOGIN; END IF; IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='devplm_sync') THEN CREATE ROLE devplm_sync NOLOGIN; END IF; END $$;

CREATE TABLE IF NOT EXISTS devplm.schema_migrations (version text PRIMARY KEY, sha256 char(64) NOT NULL, applied_at timestamptz NOT NULL DEFAULT clock_timestamp());

CREATE TABLE devplm.tenants (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
name text NOT NULL, visibility_policy_ref text, source_root_ref text, UNIQUE(id), CHECK (tenant_pk=pk)
);

CREATE TABLE devplm.principals (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
display_name text NOT NULL, actor_type text NOT NULL CHECK(actor_type IN ('human','agent','service')), identity_binding_ref text, roles text[] NOT NULL DEFAULT '{}', UNIQUE(tenant_pk,id)
);

CREATE TABLE devplm.projects (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
name text NOT NULL, description text NOT NULL, type text NOT NULL CHECK(type IN ('software','agent','aigc')), kind text NOT NULL, example boolean NOT NULL, stage text NOT NULL, focus_requirement_pk uuid, onboarding jsonb, UNIQUE(tenant_pk,id), CHECK(project_pk=pk)
);

CREATE TABLE devplm.repositories (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
local_path text, remote_url text, branch text, availability text NOT NULL CHECK(availability IN ('reachable','unavailable')), unavailable_reason text
);

CREATE TABLE devplm.requirements (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, original text NOT NULL, understanding text NOT NULL, provenance text, status text NOT NULL, priority text, next_action text, steps jsonb NOT NULL, UNIQUE(tenant_pk,project_pk,id)
);

CREATE TABLE devplm.requirement_checks (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
requirement_pk uuid NOT NULL, position integer NOT NULL CHECK(position>=0), text text NOT NULL, checked boolean NOT NULL, UNIQUE(tenant_pk,project_pk,requirement_pk,position)
);

CREATE TABLE devplm.changes (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, narrative text NOT NULL, status text NOT NULL, round integer, history_note text, repository_pk uuid, UNIQUE(tenant_pk,project_pk,id)
);

CREATE TABLE devplm.change_requirements (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
change_pk uuid NOT NULL, requirement_pk uuid NOT NULL, UNIQUE(change_pk,requirement_pk)
);

CREATE TABLE devplm.change_commits (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
change_pk uuid NOT NULL, repository_pk uuid NOT NULL, declared_commit_sha text NOT NULL, git_commit_pk uuid, resolution_status text NOT NULL CHECK(resolution_status IN ('resolved','unavailable','missing')), resolution_reason text, UNIQUE(change_pk,declared_commit_sha)
);

CREATE TABLE devplm.git_commits (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
repository_pk uuid NOT NULL, sha text NOT NULL, parent_shas text[] NOT NULL, author_label text, authored_at timestamptz, committed_at timestamptz, subject text NOT NULL, file_count integer NOT NULL CHECK(file_count>=0), insertions integer, deletions integer, UNIQUE(repository_pk,sha)
);

CREATE TABLE devplm.git_file_changes (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
git_commit_pk uuid NOT NULL, old_path text, new_path text, change_kind text NOT NULL, added_lines integer, deleted_lines integer, patch text NOT NULL, hunks jsonb NOT NULL, before_blob_sha text, after_blob_sha text, extraction_status text NOT NULL CHECK(extraction_status IN ('available','unavailable','no_history','partial'))
);

CREATE TABLE devplm.test_cases (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, requirement_pk uuid NOT NULL, environment_ref text, expected text, actual text, result text NOT NULL, record_pk uuid
);

CREATE TABLE devplm.releases (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, status text NOT NULL, version_label text, environment_ref text, change_ids text[] NOT NULL DEFAULT '{}', test_ids text[] NOT NULL DEFAULT '{}', receipt_ref text, rollback_notes text
);

CREATE TABLE devplm.incidents (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, status text NOT NULL, severity text, symptom text, expected text, evidence_refs text[] NOT NULL DEFAULT '{}', cause text, resolution text
);

CREATE TABLE devplm.security_audits (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, status text NOT NULL, scope text, findings jsonb NOT NULL DEFAULT '[]', auditor_label text, evidence_refs text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE devplm.retrospectives (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, status text NOT NULL, observations text, interpretations text, decisions text, followup_requirement_ids text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE devplm.activity_records (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
title text NOT NULL, stage text NOT NULL, environment_ref text, actor_label text, detail text NOT NULL, before_description text, after_description text, result text, target_ref text
);

CREATE TABLE devplm.api_contracts (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
openapi_version text NOT NULL, title text NOT NULL, contract_version text NOT NULL, document jsonb NOT NULL, validation_profile text NOT NULL
);

CREATE TABLE devplm.environments (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
contract_pk uuid NOT NULL, server_ref text NOT NULL, label text, base_url text NOT NULL, deployment_state text, UNIQUE(tenant_pk,project_pk,server_ref)
);

CREATE TABLE devplm.master_objects (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
project_type text NOT NULL, object_type text NOT NULL, title text NOT NULL, status text, payload jsonb NOT NULL, UNIQUE(tenant_pk,project_pk,object_type,id)
);

CREATE TABLE devplm.object_links (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
from_pk uuid NOT NULL, from_kind text NOT NULL, relation text NOT NULL, to_pk uuid NOT NULL, to_kind text NOT NULL, UNIQUE(from_pk,relation,to_pk)
);

CREATE TABLE devplm.object_registry (
pk uuid PRIMARY KEY,
id text NOT NULL,
tenant_pk uuid NOT NULL,
project_pk uuid,
owner_pk uuid,
created_at timestamptz,
updated_at timestamptz,
deleted_at timestamptz,
revision text NOT NULL,
source_version text,
source_path text NOT NULL,
source_pointer text NOT NULL,
source_sha256 char(64) NOT NULL,
source_commit_sha text,
source_actor_label text,
ingest_key char(64) NOT NULL,
projection_epoch text NOT NULL,
projection_state text NOT NULL CHECK (projection_state IN ('staging','validated','published','stale','failed')),
projection_version text NOT NULL,
source_data jsonb NOT NULL,
UNIQUE (tenant_pk,pk),
UNIQUE (tenant_pk,project_pk,pk),
kind text NOT NULL, UNIQUE(tenant_pk,project_pk,kind,id)
);

CREATE TABLE devplm.discussions (
pk uuid PRIMARY KEY,
tenant_pk uuid NOT NULL,
project_pk uuid NOT NULL,
owner_pk uuid NOT NULL,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz,
revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
created_by uuid NOT NULL,
updated_by uuid NOT NULL,
idempotency_key text NOT NULL,
lifecycle_state text NOT NULL,
last_audit_pk uuid,
last_export_id text,
UNIQUE(tenant_pk,pk),
UNIQUE(tenant_pk,project_pk,pk),
target_pk uuid NOT NULL, title text NOT NULL, resolved_at timestamptz, CHECK(lifecycle_state IN ('open','resolving','resolved'))
);

CREATE TABLE devplm.discussion_posts (
pk uuid PRIMARY KEY,
tenant_pk uuid NOT NULL,
project_pk uuid NOT NULL,
owner_pk uuid NOT NULL,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz,
revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
created_by uuid NOT NULL,
updated_by uuid NOT NULL,
idempotency_key text NOT NULL,
lifecycle_state text NOT NULL,
last_audit_pk uuid,
last_export_id text,
UNIQUE(tenant_pk,pk),
UNIQUE(tenant_pk,project_pk,pk),
discussion_pk uuid NOT NULL, parent_post_pk uuid, body text NOT NULL, edited_at timestamptz, CHECK(lifecycle_state IN ('draft','posted','redacted'))
);

CREATE TABLE devplm.claims (
pk uuid PRIMARY KEY,
tenant_pk uuid NOT NULL,
project_pk uuid NOT NULL,
owner_pk uuid NOT NULL,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz,
revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
created_by uuid NOT NULL,
updated_by uuid NOT NULL,
idempotency_key text NOT NULL,
lifecycle_state text NOT NULL,
last_audit_pk uuid,
last_export_id text,
UNIQUE(tenant_pk,pk),
UNIQUE(tenant_pk,project_pk,pk),
target_pk uuid NOT NULL, claimant_pk uuid NOT NULL, expires_at timestamptz, released_at timestamptz, CHECK(lifecycle_state IN ('pending','active','releasing','released','expired'))
);

CREATE TABLE devplm.notifications (
pk uuid PRIMARY KEY,
tenant_pk uuid NOT NULL,
project_pk uuid NOT NULL,
owner_pk uuid NOT NULL,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz,
revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
created_by uuid NOT NULL,
updated_by uuid NOT NULL,
idempotency_key text NOT NULL,
lifecycle_state text NOT NULL,
last_audit_pk uuid,
last_export_id text,
UNIQUE(tenant_pk,pk),
UNIQUE(tenant_pk,project_pk,pk),
recipient_pk uuid NOT NULL, cause_audit_pk uuid, payload jsonb NOT NULL, delivered_at timestamptz, read_at timestamptz, CHECK(lifecycle_state IN ('queued','sending','delivered','read','failed'))
);

CREATE TABLE devplm.idempotency_requests (
pk uuid PRIMARY KEY,
tenant_pk uuid NOT NULL,
project_pk uuid NOT NULL,
owner_pk uuid NOT NULL,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz,
revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1),
created_by uuid NOT NULL,
updated_by uuid NOT NULL,
idempotency_key text NOT NULL,
lifecycle_state text NOT NULL,
last_audit_pk uuid,
last_export_id text,
UNIQUE(tenant_pk,pk),
UNIQUE(tenant_pk,project_pk,pk),
actor_pk uuid NOT NULL, operation text NOT NULL, request_sha256 char(64) NOT NULL, response_status integer, response_body jsonb, expires_at timestamptz NOT NULL, CHECK(lifecycle_state IN ('reserved','executing','completed','failed')), UNIQUE(tenant_pk,actor_pk,operation,idempotency_key)
);

CREATE TABLE devplm.collaboration_audit_events (
pk uuid PRIMARY KEY, tenant_pk uuid NOT NULL, project_pk uuid NOT NULL, owner_pk uuid NOT NULL,
actor_pk uuid NOT NULL, actor_type text NOT NULL CHECK(actor_type IN ('human','agent','service')),
action text NOT NULL, target_kind text NOT NULL,
discussion_pk uuid, post_pk uuid, claim_pk uuid, notification_pk uuid, idempotency_request_pk uuid,
before_value jsonb, after_value jsonb, expected_revision bigint, resulting_revision bigint,
idempotency_key text NOT NULL, request_id text NOT NULL,
result text NOT NULL CHECK(result IN ('accepted','succeeded','rejected','failed')), reason_code text,
created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz, revision integer NOT NULL DEFAULT 1 CHECK(revision=1), export_id text,
UNIQUE(tenant_pk,pk), UNIQUE(tenant_pk,project_pk,pk),
CHECK (num_nonnulls(discussion_pk,post_pk,claim_pk,notification_pk,idempotency_request_pk)<=1),
CHECK ((result IN ('rejected','failed')) OR num_nonnulls(discussion_pk,post_pk,claim_pk,notification_pk,idempotency_request_pk)=1),
CHECK ((discussion_pk IS NULL OR target_kind='discussions') AND (post_pk IS NULL OR target_kind='discussion_posts') AND (claim_pk IS NULL OR target_kind='claims') AND (notification_pk IS NULL OR target_kind='notifications') AND (idempotency_request_pk IS NULL OR target_kind='idempotency_requests'))
);

CREATE TABLE devplm.sync_jobs (
pk uuid PRIMARY KEY, tenant_pk uuid NOT NULL, project_pk uuid NOT NULL, owner_pk uuid NOT NULL,
actor_pk uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz, revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1), idempotency_key text NOT NULL,
UNIQUE(tenant_pk,pk), UNIQUE(tenant_pk,project_pk,pk),
source_snapshot text NOT NULL, previous_snapshot text, state text NOT NULL CHECK(state IN ('queued','validating','staging','published','failed')), error jsonb, published_snapshot text
);

CREATE TABLE devplm.presence (
pk uuid PRIMARY KEY, tenant_pk uuid NOT NULL, project_pk uuid NOT NULL, owner_pk uuid NOT NULL,
actor_pk uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz, revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1), idempotency_key text NOT NULL,
UNIQUE(tenant_pk,pk), UNIQUE(tenant_pk,project_pk,pk),
state text NOT NULL CHECK(state IN ('online','idle','offline')), last_seen_at timestamptz, expires_at timestamptz
);

CREATE TABLE devplm.collaboration_exports (
pk uuid PRIMARY KEY, tenant_pk uuid NOT NULL, project_pk uuid NOT NULL, owner_pk uuid NOT NULL,
actor_pk uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
deleted_at timestamptz, revision bigint NOT NULL DEFAULT 1 CHECK(revision>=1), idempotency_key text NOT NULL,
UNIQUE(tenant_pk,pk), UNIQUE(tenant_pk,project_pk,pk),
state text NOT NULL CHECK(state IN ('queued','running','completed','failed')), requested_scopes text[] NOT NULL,
high_watermark text, manifest_path text, sha256 char(64), error_code text, before_state text, after_state text
);

ALTER TABLE devplm.tenants ADD CONSTRAINT tenants_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.tenants ADD CONSTRAINT tenants_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.tenants ADD CONSTRAINT tenants_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.principals ADD CONSTRAINT principals_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.principals ADD CONSTRAINT principals_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.principals ADD CONSTRAINT principals_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.projects ADD CONSTRAINT projects_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.projects ADD CONSTRAINT projects_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.projects ADD CONSTRAINT projects_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.projects ADD CONSTRAINT projects_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.repositories ADD CONSTRAINT repositories_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.repositories ADD CONSTRAINT repositories_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.repositories ADD CONSTRAINT repositories_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.repositories ADD CONSTRAINT repositories_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.requirements ADD CONSTRAINT requirements_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirements ADD CONSTRAINT requirements_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirements ADD CONSTRAINT requirements_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirements ADD CONSTRAINT requirements_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.requirement_checks ADD CONSTRAINT requirement_checks_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirement_checks ADD CONSTRAINT requirement_checks_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirement_checks ADD CONSTRAINT requirement_checks_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirement_checks ADD CONSTRAINT requirement_checks_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.changes ADD CONSTRAINT changes_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.changes ADD CONSTRAINT changes_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.changes ADD CONSTRAINT changes_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.changes ADD CONSTRAINT changes_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.git_commits ADD CONSTRAINT git_commits_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_commits ADD CONSTRAINT git_commits_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_commits ADD CONSTRAINT git_commits_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_commits ADD CONSTRAINT git_commits_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.git_file_changes ADD CONSTRAINT git_file_changes_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_file_changes ADD CONSTRAINT git_file_changes_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_file_changes ADD CONSTRAINT git_file_changes_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_file_changes ADD CONSTRAINT git_file_changes_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.releases ADD CONSTRAINT releases_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.releases ADD CONSTRAINT releases_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.releases ADD CONSTRAINT releases_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.releases ADD CONSTRAINT releases_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.incidents ADD CONSTRAINT incidents_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.incidents ADD CONSTRAINT incidents_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.incidents ADD CONSTRAINT incidents_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.incidents ADD CONSTRAINT incidents_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.security_audits ADD CONSTRAINT security_audits_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.security_audits ADD CONSTRAINT security_audits_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.security_audits ADD CONSTRAINT security_audits_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.security_audits ADD CONSTRAINT security_audits_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.retrospectives ADD CONSTRAINT retrospectives_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.retrospectives ADD CONSTRAINT retrospectives_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.retrospectives ADD CONSTRAINT retrospectives_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.retrospectives ADD CONSTRAINT retrospectives_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.activity_records ADD CONSTRAINT activity_records_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.activity_records ADD CONSTRAINT activity_records_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.activity_records ADD CONSTRAINT activity_records_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.activity_records ADD CONSTRAINT activity_records_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.api_contracts ADD CONSTRAINT api_contracts_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.api_contracts ADD CONSTRAINT api_contracts_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.api_contracts ADD CONSTRAINT api_contracts_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.api_contracts ADD CONSTRAINT api_contracts_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.environments ADD CONSTRAINT environments_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.environments ADD CONSTRAINT environments_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.environments ADD CONSTRAINT environments_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.environments ADD CONSTRAINT environments_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.master_objects ADD CONSTRAINT master_objects_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.master_objects ADD CONSTRAINT master_objects_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.master_objects ADD CONSTRAINT master_objects_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.master_objects ADD CONSTRAINT master_objects_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.object_registry ADD CONSTRAINT object_registry_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_registry ADD CONSTRAINT object_registry_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_registry ADD CONSTRAINT object_registry_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_registry ADD CONSTRAINT object_registry_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.claims ADD CONSTRAINT claims_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.sync_jobs ADD CONSTRAINT sync_jobs_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.sync_jobs ADD CONSTRAINT sync_jobs_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.sync_jobs ADD CONSTRAINT sync_jobs_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.sync_jobs ADD CONSTRAINT sync_jobs_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.presence ADD CONSTRAINT presence_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.presence ADD CONSTRAINT presence_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.presence ADD CONSTRAINT presence_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.presence ADD CONSTRAINT presence_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.collaboration_exports ADD CONSTRAINT collaboration_exports_tenant_pk_fk FOREIGN KEY (tenant_pk) REFERENCES devplm.tenants (pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_exports ADD CONSTRAINT collaboration_exports_project_pk_fk FOREIGN KEY (tenant_pk,project_pk) REFERENCES devplm.projects (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_exports ADD CONSTRAINT collaboration_exports_owner_pk_fk FOREIGN KEY (tenant_pk,owner_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_exports ADD CONSTRAINT collaboration_exports_project_required CHECK(project_pk IS NOT NULL);

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_created_by_fk FOREIGN KEY (tenant_pk,created_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_updated_by_fk FOREIGN KEY (tenant_pk,updated_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_last_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,last_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_created_by_fk FOREIGN KEY (tenant_pk,created_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_updated_by_fk FOREIGN KEY (tenant_pk,updated_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_last_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,last_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_created_by_fk FOREIGN KEY (tenant_pk,created_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_updated_by_fk FOREIGN KEY (tenant_pk,updated_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_last_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,last_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_created_by_fk FOREIGN KEY (tenant_pk,created_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_updated_by_fk FOREIGN KEY (tenant_pk,updated_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_last_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,last_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_created_by_fk FOREIGN KEY (tenant_pk,created_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_updated_by_fk FOREIGN KEY (tenant_pk,updated_by) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_last_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,last_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_actor_pk_fk FOREIGN KEY (tenant_pk,actor_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.sync_jobs ADD CONSTRAINT sync_jobs_actor_pk_fk FOREIGN KEY (tenant_pk,actor_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.presence ADD CONSTRAINT presence_actor_pk_fk FOREIGN KEY (tenant_pk,actor_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_exports ADD CONSTRAINT collaboration_exports_actor_pk_fk FOREIGN KEY (tenant_pk,actor_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.projects ADD CONSTRAINT projects_focus_requirement_pk_fk FOREIGN KEY (tenant_pk,project_pk,focus_requirement_pk) REFERENCES devplm.requirements (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.requirement_checks ADD CONSTRAINT requirement_checks_requirement_pk_fk FOREIGN KEY (tenant_pk,project_pk,requirement_pk) REFERENCES devplm.requirements (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.changes ADD CONSTRAINT changes_repository_pk_fk FOREIGN KEY (tenant_pk,project_pk,repository_pk) REFERENCES devplm.repositories (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_change_pk_fk FOREIGN KEY (tenant_pk,project_pk,change_pk) REFERENCES devplm.changes (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_requirements ADD CONSTRAINT change_requirements_requirement_pk_fk FOREIGN KEY (tenant_pk,project_pk,requirement_pk) REFERENCES devplm.requirements (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_change_pk_fk FOREIGN KEY (tenant_pk,project_pk,change_pk) REFERENCES devplm.changes (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_repository_pk_fk FOREIGN KEY (tenant_pk,project_pk,repository_pk) REFERENCES devplm.repositories (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.change_commits ADD CONSTRAINT change_commits_git_commit_pk_fk FOREIGN KEY (tenant_pk,project_pk,git_commit_pk) REFERENCES devplm.git_commits (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_commits ADD CONSTRAINT git_commits_repository_pk_fk FOREIGN KEY (tenant_pk,project_pk,repository_pk) REFERENCES devplm.repositories (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.git_file_changes ADD CONSTRAINT git_file_changes_git_commit_pk_fk FOREIGN KEY (tenant_pk,project_pk,git_commit_pk) REFERENCES devplm.git_commits (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_requirement_pk_fk FOREIGN KEY (tenant_pk,project_pk,requirement_pk) REFERENCES devplm.requirements (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.test_cases ADD CONSTRAINT test_cases_record_pk_fk FOREIGN KEY (tenant_pk,project_pk,record_pk) REFERENCES devplm.activity_records (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.environments ADD CONSTRAINT environments_contract_pk_fk FOREIGN KEY (tenant_pk,project_pk,contract_pk) REFERENCES devplm.api_contracts (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_from_pk_fk FOREIGN KEY (tenant_pk,project_pk,from_pk) REFERENCES devplm.object_registry (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.object_links ADD CONSTRAINT object_links_to_pk_fk FOREIGN KEY (tenant_pk,project_pk,to_pk) REFERENCES devplm.object_registry (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussions ADD CONSTRAINT discussions_target_pk_fk FOREIGN KEY (tenant_pk,project_pk,target_pk) REFERENCES devplm.object_registry (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_discussion_pk_fk FOREIGN KEY (tenant_pk,project_pk,discussion_pk) REFERENCES devplm.discussions (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_thread_identity UNIQUE (tenant_pk,project_pk,discussion_pk,pk);

ALTER TABLE devplm.discussion_posts ADD CONSTRAINT discussion_posts_parent_post_pk_fk FOREIGN KEY (tenant_pk,project_pk,discussion_pk,parent_post_pk) REFERENCES devplm.discussion_posts (tenant_pk,project_pk,discussion_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_target_pk_fk FOREIGN KEY (tenant_pk,project_pk,target_pk) REFERENCES devplm.object_registry (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_cause_audit_pk_fk FOREIGN KEY (tenant_pk,project_pk,cause_audit_pk) REFERENCES devplm.collaboration_audit_events (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_discussion_pk_fk FOREIGN KEY (tenant_pk,project_pk,discussion_pk) REFERENCES devplm.discussions (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_post_pk_fk FOREIGN KEY (tenant_pk,project_pk,post_pk) REFERENCES devplm.discussion_posts (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_claim_pk_fk FOREIGN KEY (tenant_pk,project_pk,claim_pk) REFERENCES devplm.claims (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_notification_pk_fk FOREIGN KEY (tenant_pk,project_pk,notification_pk) REFERENCES devplm.notifications (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.collaboration_audit_events ADD CONSTRAINT collaboration_audit_events_idempotency_request_pk_fk FOREIGN KEY (tenant_pk,project_pk,idempotency_request_pk) REFERENCES devplm.idempotency_requests (tenant_pk,project_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.claims ADD CONSTRAINT claims_claimant_pk_fk FOREIGN KEY (tenant_pk,claimant_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.notifications ADD CONSTRAINT notifications_recipient_pk_fk FOREIGN KEY (tenant_pk,recipient_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE devplm.idempotency_requests ADD CONSTRAINT idempotency_requests_actor_pk_fk FOREIGN KEY (tenant_pk,actor_pk) REFERENCES devplm.principals (tenant_pk,pk) DEFERRABLE INITIALLY DEFERRED;

CREATE UNIQUE INDEX claims_one_active_target ON devplm.claims(tenant_pk,project_pk,target_pk) WHERE lifecycle_state IN ('pending','active','releasing') AND deleted_at IS NULL;

CREATE INDEX posts_thread_order ON devplm.discussion_posts(tenant_pk,project_pk,discussion_pk,created_at,pk);

CREATE INDEX registry_lookup ON devplm.object_registry(tenant_pk,project_pk,id);

CREATE OR REPLACE FUNCTION devplm.reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit events are append-only' USING ERRCODE='42501'; END $$;

CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON devplm.collaboration_audit_events FOR EACH ROW EXECUTE FUNCTION devplm.reject_audit_mutation();

CREATE FUNCTION devplm.require_current_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_revision bigint; current_audit uuid; current_actor uuid; valid_audit boolean;
BEGIN
  EXECUTE format('SELECT revision,last_audit_pk,updated_by FROM devplm.%I WHERE pk=$1',TG_TABLE_NAME)
    INTO current_revision,current_audit,current_actor USING NEW.pk;
  IF current_revision IS NULL THEN RETURN NULL; END IF;
  SELECT EXISTS(SELECT 1 FROM devplm.collaboration_audit_events a
    WHERE a.pk=current_audit AND a.tenant_pk=NEW.tenant_pk AND a.project_pk=NEW.project_pk
      AND a.target_kind=TG_TABLE_NAME AND a.result='succeeded'
      AND a.resulting_revision=current_revision AND a.actor_pk=current_actor
      AND COALESCE(a.discussion_pk,a.post_pk,a.claim_pk,a.notification_pk)=NEW.pk) INTO valid_audit;
  IF NOT valid_audit THEN RAISE EXCEPTION 'A successful collaboration write requires a matching transactional audit' USING ERRCODE='23514'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER discussions_requires_audit AFTER INSERT OR UPDATE ON devplm.discussions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION devplm.require_current_audit();

CREATE CONSTRAINT TRIGGER discussion_posts_requires_audit AFTER INSERT OR UPDATE ON devplm.discussion_posts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION devplm.require_current_audit();

CREATE CONSTRAINT TRIGGER claims_requires_audit AFTER INSERT OR UPDATE ON devplm.claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION devplm.require_current_audit();

CREATE CONSTRAINT TRIGGER notifications_requires_audit AFTER INSERT OR UPDATE ON devplm.notifications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION devplm.require_current_audit();

GRANT USAGE ON SCHEMA devplm TO devplm_api,devplm_sync;

REVOKE ALL ON ALL TABLES IN SCHEMA devplm FROM PUBLIC;

GRANT SELECT ON ALL TABLES IN SCHEMA devplm TO devplm_api;

GRANT SELECT ON ALL TABLES IN SCHEMA devplm TO devplm_sync;

GRANT UPDATE ON devplm.sync_jobs TO devplm_sync;

GRANT INSERT,UPDATE,DELETE ON devplm.tenants,devplm.principals,devplm.projects,devplm.repositories,devplm.requirements,devplm.requirement_checks,devplm.changes,devplm.change_requirements,devplm.change_commits,devplm.git_commits,devplm.git_file_changes,devplm.test_cases,devplm.releases,devplm.incidents,devplm.security_audits,devplm.retrospectives,devplm.activity_records,devplm.api_contracts,devplm.environments,devplm.master_objects,devplm.object_links,devplm.object_registry TO devplm_sync;

GRANT INSERT,UPDATE ON devplm.discussions,devplm.discussion_posts,devplm.claims,devplm.notifications,devplm.idempotency_requests TO devplm_api;

GRANT INSERT ON devplm.collaboration_audit_events TO devplm_api;

GRANT INSERT,UPDATE ON devplm.sync_jobs,devplm.presence,devplm.collaboration_exports TO devplm_api;

-- No API DELETE privilege; soft deletion occurs by authorized UPDATE. No API F/G mutation privilege.
