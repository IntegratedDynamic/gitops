# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

ArgoCD GitOps repository for a Kubernetes setup. Deployment happens by pushing to `main` — ArgoCD watches this repo and reconciles automatically.

The companion infrastructure repo (Terraform + Minikube) bootstraps ArgoCD and seeds it with a `bootstrap` Application that points here.

## Directory roles

**`bootstrap/`** — A Helm chart that is the entry point referenced by external repos (e.g. the Terraform infra repo). The provisioner points an ArgoCD Application at this path and passes `env` (which cluster) and `revision` (which git ref). The chart's `templates/<env>.yaml` creates that cluster's top-level Application, which then watches the matching `clusters/<env>/` directory.

**`clusters/<env>/`** — A Helm chart: the cluster root app-of-apps. Its `templates/` hold `projects.yaml` (the `platform` / `apps` AppProjects, sync-wave `-1`) and one Application per **domain** (`platform.yaml`, `apps.yaml`), each pointing at the matching domain chart and threading `revision`/`repoURL` down.

**`apps/<name>/`** — Helm charts for in-house applications. `values.yaml` is the baseline; `values-<env>.yaml` holds per-environment overrides. Charts are never duplicated across environments.

**`platform/<env>/`** — The **platform domain** app-of-apps, organised as a nested tree **domain → sub-domain → service → applications** to group things visually/logically in the ArgoCD UI:
- `platform/<env>/` is a Helm chart whose `templates/` emit one Application per sub-domain (`secrets`, `observability`, `ingress`).
- A sub-domain that contains a git-tracked child (needs `revision`) is itself a Helm chart (`platform/<env>/secrets/`); a sub-domain whose children are only external Helm charts is a plain **directory** source of `.yml` manifests (`platform/<env>/observability/`, `ingress/`).
- A **service** app-of-apps groups multiple Applications under one node — used only when a service has >1 app (`platform/<env>/secrets/openbao/` = openbao server + init/restore job). Single-app services are a leaf directly under their sub-domain.
- Each Application carries `domain` / `subdomain` / `service` labels (UI "Labels" filter) and `project: platform`.

**`workloads/<env>/`** — The **apps domain** app-of-apps (in-house workloads, `project: apps`). Currently just `demo`.

> **Chart vs directory rule:** any app-of-apps node that creates a child pointing at *this* git repo is a Helm chart (so it can thread `revision`/`repoURL` as `helm.parameters`); a node whose children are all external Helm charts (pinned versions, no git ref) is a directory source. This keeps external `helm.values` blocks (e.g. Grafana dashboards) out of Go-templating. Parent charts `.helmignore` their sub-node dirs so `helm template` only renders their own `templates/`.

### Revision propagation (feature-branch testing)

`revision` threads from the provisioner through the whole app-of-apps tree: the infra repo's `gitops_revision` → the `bootstrap` Application's `revision` Helm param → the cluster root (`clusters/<env>`) → each domain app (`platform`, `apps`) → sub-domain (`platform-secrets`) → service (`openbao-stack`) → the leaf Applications' `source.targetRevision`. Every git-tracked app-of-apps chart re-passes `revision`/`repoURL` as `helm.parameters`. It defaults to `main` everywhere, so setting `gitops_revision` to a feature branch makes the *entire* tree deploy from that branch — letting you validate changes on the local cluster before merging to `main`.

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

# Render the app-of-apps charts (confirm revision propagation through the tree)
helm template boot bootstrap/ --set env=local --set revision=<branch>
helm template loc  clusters/local/                 --set revision=<branch> --set repoURL=<repo>
helm template plat platform/local/                 --set revision=<branch> --set repoURL=<repo>
helm template sec  platform/local/secrets/          --set revision=<branch> --set repoURL=<repo>
helm template obao platform/local/secrets/openbao/  --set revision=<branch> --set repoURL=<repo>
helm template apps workloads/local/                 --set revision=<branch> --set repoURL=<repo>

# Validate the directory-source platform manifests (external Helm charts)
kubectl --context minikube apply --dry-run=client -f platform/local/observability/
kubectl --context minikube apply --dry-run=client -f platform/local/ingress/
```

## Adding things

**New in-house app (apps domain):** Create `apps/<name>/` Helm chart + a leaf Application template under `workloads/<env>/templates/<name>.yaml` using `{{ .Values.revision }}` / `{{ .Values.repoURL }}`, `project: apps` and a `domain: apps` label. See `workloads/local/templates/demo.yaml`.

**New platform tool (external Helm chart):** Add a leaf Application under the right sub-domain, with `project: platform` and `domain`/`subdomain` labels:
- observability/ingress (directory sub-domains) → drop a `.yml` next to `platform/<env>/observability/kube-prometheus-stack.yml`.
- secrets or any chart sub-domain → add a manifest under `platform/<env>/secrets/templates/`.

**New sub-domain:** add a template to `platform/<env>/templates/` (chart source if it will hold a git-tracked child, else directory source) — see `platform/local/templates/secrets.yaml` (chart) vs `observability.yaml` (directory).

**New multi-app service:** wrap its Applications in a service app-of-apps chart under the sub-domain, e.g. `platform/local/secrets/openbao/` — and `.helmignore` that dir from the parent chart.

**New cluster environment (e.g. staging):**
1. `apps/<name>/values-staging.yaml` for each app that needs overrides
2. `clusters/staging/` chart (root: `projects.yaml` + `platform.yaml` + `apps.yaml`)
3. `platform/staging/` domain chart + its sub-domain/service sub-trees, and `workloads/staging/`
4. `bootstrap/templates/staging.yaml` guarded by `{{- if eq .Values.env "staging" }}` as the entry point for external provisioners

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
