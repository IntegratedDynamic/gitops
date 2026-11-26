-- Run by templates/reporting-role.yaml, in one transaction, as the database owner.
-- Variables: :role (psql --set), :reader_password (environment READER_PASSWORD).
\getenv reader_password READER_PASSWORD

SELECT format('CREATE ROLE %I', :'role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role') \gexec

ALTER ROLE :"role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  NOBYPASSRLS CONNECTION LIMIT 5 PASSWORD :'reader_password';
ALTER ROLE :"role" SET default_transaction_read_only = on;
ALTER ROLE :"role" SET statement_timeout = '15s';

-- Start from nothing (also drops column grants), so a column removed below is
-- really revoked.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM :"role";
GRANT USAGE ON SCHEMA public TO :"role";

GRANT SELECT (id, username, name, email, type, is_active, last_login, date_joined)
  ON authentik_core_user TO :"role";
GRANT SELECT (group_uuid, name, is_superuser) ON authentik_core_group TO :"role";
GRANT SELECT (user_id, group_id) ON authentik_core_user_groups TO :"role";
GRANT SELECT (child_id, parent_id) ON authentik_core_groupparentage TO :"role";
GRANT SELECT (policybindingmodel_ptr_id, name, slug) ON authentik_core_application TO :"role";
GRANT SELECT (pbm_uuid, policy_engine_mode) ON authentik_policies_policybindingmodel TO :"role";
GRANT SELECT (policy_binding_uuid, enabled, policy_id, target_id, negate, group_id, user_id, expiring, expires)
  ON authentik_policies_policybinding TO :"role";
GRANT SELECT (policybindingmodel_ptr_id, name) ON authentik_core_source TO :"role";
GRANT SELECT (user_id, source_id) ON authentik_core_usersourceconnection TO :"role";
GRANT SELECT (user_id) ON authentik_stages_authenticator_webauthn_webauthndevice TO :"role";
GRANT SELECT (flow_uuid, slug) ON authentik_flows_flow TO :"role";
GRANT SELECT (name, flow_id, single_use, expiring, expires)
  ON authentik_stages_invitation_invitation TO :"role";
