# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

ArgoCD GitOps repository for a Kubernetes setup. Deployment happens by pushing to `main` — ArgoCD watches this repo and reconciles automatically.

The companion infrastructure repo (Terraform + Minikube) bootstraps ArgoCD and seeds it with a `bootstrap` Application that points here.

## Directory roles

**`bootstrap/`** — A Helm chart that is the entry point referenced by external repos (e.g. the Terraform infra repo). The provisioner points an ArgoCD Application at this path and passes `env` (which cluster) and `revision` (which git ref). The chart's `templates/<env>.yaml` creates that cluster's top-level Application, which then watches the matching `clusters/<env>/` directory.

**`clusters/<env>/`** — A Helm chart holding the exhaustive declarative state of what runs in a given cluster. One template per Application under `templates/`; ArgoCD renders them all.

**`apps/<name>/`** — Helm charts for in-house applications. `values.yaml` is the baseline; `values-<env>.yaml` holds per-environment overrides. Charts are never duplicated across environments.

**`platform/<env>/`** — Shared cluster-level tools (ingress-nginx, kube-prometheus-stack, etc.) as ArgoCD Applications pointing to external Helm repos, stored as plain manifests (one `.yml` per tool). Factored out to avoid repeating common infrastructure across clusters.

### Revision propagation (feature-branch testing)

`revision` threads from the provisioner through the whole app-of-apps tree: the infra repo's `gitops_revision` → the `bootstrap` Application's `revision` Helm param → the cluster Application → the `platform`/`demo` Applications' `source.targetRevision`. It defaults to `main` everywhere, so setting `gitops_revision` to a feature branch makes the *entire* tree (including `platform/<env>/`) deploy from that branch — letting you validate changes on the local cluster before merging to `main`.

## Doctor commands

Always use `--context minikube` to avoid hitting the wrong cluster:

```bash
minikube status                                                    # cluster running?
kubectl --context minikube get pods -n argocd                     # ArgoCD healthy?
kubectl --context minikube get applications -n argocd             # apps synced?
kubectl --context minikube get pods -n ingress-nginx              # ingress up?
kubectl --context minikube get clustersecretstore openbao         # OpenBao + ESO ready?
```

## Validation commands

Always target the local cluster explicitly to avoid accidental execution against the wrong context (`minikube` is local, but the active context can change):

```bash
# Lint a Helm chart
helm lint apps/demo/ -f apps/demo/values-local.yaml
helm lint apps/openbao-init/ -f apps/openbao-init/values-local.yaml
helm lint apps/openbao-init/ -f apps/openbao-init/values-scaleway.yaml

# Render an app chart to inspect output
helm template demo apps/demo/ -f apps/demo/values-local.yaml
helm template openbao-init apps/openbao-init/ -f apps/openbao-init/values-local.yaml

# Render the app-of-apps charts (confirm revision propagation)
helm template boot bootstrap/ --set env=local --set revision=<branch>
helm template loc clusters/local/ --set revision=<branch> --set repoURL=<repo>
helm template loc clusters/scaleway/ --set revision=<branch> --set repoURL=<repo>

# Validate a platform Application manifest
kubectl --context minikube apply --dry-run=client -f platform/local/kube-prometheus-stack.yml
kubectl --context minikube apply --dry-run=client -f platform/local/openbao.yml
```

## Adding things

**New app:** Create `apps/<name>/` Helm chart + a `clusters/local/templates/<name>.yaml` Application template using `{{ .Values.revision }}` / `{{ .Values.repoURL }}`. See `clusters/local/templates/demo.yaml` as a template.

**New cluster environment (e.g. staging):**
1. `apps/<name>/values-staging.yaml` for each app that needs overrides
2. `platform/staging/` for cluster-level tools
3. `clusters/staging/` chart with the exhaustive Application templates
4. `bootstrap/templates/staging.yaml` guarded by `{{- if eq .Values.env "staging" }}` as the entry point for external provisioners

**New platform tool:** Add a file to `platform/<env>/` following `platform/local/ingress-nginx.yml`.

<!-- SPECKIT START -->
## Active Feature

**Feature**: Replace Infisical with OSS Secrets Backend
**Plan**: [specs/001-replace-infisical-oss-secrets/plan.md](specs/001-replace-infisical-oss-secrets/plan.md)
**Tasks**: [specs/001-replace-infisical-oss-secrets/tasks.md](specs/001-replace-infisical-oss-secrets/tasks.md)
**Status**: Tasks generated — ready for `/speckit-implement`
**Tool**: OpenBao (MPL 2.0) — decided 2026-06-21

### Quick reference

| Artifact | Path |
|----------|------|
| Spec | `specs/001-replace-infisical-oss-secrets/spec.md` |
| Plan | `specs/001-replace-infisical-oss-secrets/plan.md` |
| Research | `specs/001-replace-infisical-oss-secrets/research.md` |
| Data model | `specs/001-replace-infisical-oss-secrets/data-model.md` |
| Contracts | `specs/001-replace-infisical-oss-secrets/contracts/` |
| Quickstart | `specs/001-replace-infisical-oss-secrets/quickstart.md` |
| Tasks | `specs/001-replace-infisical-oss-secrets/tasks.md` |

### MVP scope (US1, Phases 1–3, tasks T001–T020)

1. Scaffold `apps/openbao-init/` Helm chart (T001–T004)
2. Write `platform/<env>/openbao.yml` + `external-secrets.yml` (T005–T009)
3. Write init Job, RBAC, policies, ClusterSecretStore, cluster templates, sync waves (T010–T018)
4. Validate: `helm lint apps/openbao-init/` + local Scenario 1 smoke test (T019–T020)

### Key constraints

- `scaleway-s3-credentials` Secret created by infra Terraform, not this repo — init Job reads it
- S3 backend: no HA on Scaleway (no DynamoDB locking) → single replica
- Init Job must be idempotent; root token revoked after first init
- All external Helm chart versions must be pinned explicitly
<!-- SPECKIT END -->
