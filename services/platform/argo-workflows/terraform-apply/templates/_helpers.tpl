{{/*
Derives a Terraform workspace name from a root's path, matching the infra
repo's naming convention (2026-08-24 workspace-naming refacto,
infrastructure repo's CLAUDE.md "Backend keys are decoupled from paths"):
the path flattened with hyphens, suffixed "-dev" -- e.g.
"11-secrets/openbao/managed" -> "11-secrets-openbao-managed-dev".

Single source of truth so root/workspace can never drift apart the way they
did before (values-scaleway.yaml used to hardcode both independently, and
went stale when the infra repo renumbered its roots -- see gitops#45).
Takes a root path string, returns the derived workspace name.
*/}}
{{- define "terraform-apply.workspace" -}}
{{- . | replace "/" "-" }}-dev
{{- end -}}
