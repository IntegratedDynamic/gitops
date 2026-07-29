# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

ArgoCD GitOps repository for a Kubernetes setup. Deployment happens by pushing to `main` — ArgoCD watches this repo and reconciles automatically.

The companion infrastructure repo (Terraform + Minikube) bootstraps ArgoCD and seeds it with a `bootstrap` Application that points here.

## Directory roles

**`bootstrap/`** — A Helm chart that is the entry point referenced by external repos (e.g. the Terraform infra repo). The provisioner points an ArgoCD Application at this path and passes `env` (which cluster) and `revision` (which git ref). The chart's `templates/<env>.yaml` creates, directly, the two objects that discover every Application for that cluster (see below) — there is no intermediate `clusters/<env>/` chart.

**`services/<bucket>/<name>/`** — One directory per service, `<bucket>` being `platform` (infra: openbao, cert-manager, gateway, dex, external-dns, monitoring, velero, argocd-config, secrets-sync, ingress-nginx, external-secrets) or `products` (revenue-generating apps: demo). Everything about a service lives together:

- In-house Helm charts as subfolders (`init/`, `config/`, `chart/`, etc. — the name describes what the chart does). `values.yaml` is the baseline; `values-<env>.yaml` holds per-environment overrides. Charts are never duplicated across environments.
- `applications/<env>/` — that service's ArgoCD Applications for a given cluster, in one of two formats (see below).

**`charts/<name>/`** — Shared library charts consumed as a Helm dependency by a service's chart (e.g. `charts/sso-guard`, pulled in by `services/products/demo/chart`). Never deployed as their own Application.

### The two `applications/<env>/` file formats

- **`*.vendor.yaml`** — a complete, hand-written ArgoCD `Application` manifest that loads an external Helm chart (openbao-helm, cert-manager, dex, envoy-gateway...). Free-form: inline values, `ignoreDifferences`, OCI sources, `ServerSideApply`, whatever that tool needs. Discovered by a plain directory-recurse Application (`services-vendor-<env>`, created by `bootstrap/templates/<env>.yaml`) that applies anything matching `services/*/*/applications/<env>/*.vendor.yaml` as-is — no templating.
- **`*.app.yaml`** — a small params file (`name`, `namespace`, `chartPath`, `valueFile`, `syncWave`) for an Application that loads one of *our own* charts from this repo. Expanded by the `services-app-<env>` ApplicationSet (git `files` generator, `goTemplate: true`, matching `services/*/*/applications/<env>/*.app.yaml`), whose template injects `repoURL`/`targetRevision` — this is what keeps `gitops_revision` propagating without a hand-maintained per-Application file.

Adding or removing an Application for an existing service never requires touching `bootstrap/` — just add/remove a file in that service's `applications/<env>/` folder.

### Revision propagation (feature-branch testing)

`revision` threads from the provisioner through the whole tree: the infra repo's `gitops_revision` → the `bootstrap` Application's `revision` Helm param → the `services-vendor-<env>` Application's `source.targetRevision` (so it reads `*.vendor.yaml` files from that branch) → the `services-app-<env>` ApplicationSet's generator/template (so both the git generator and every generated Application's `targetRevision` point at that branch). It defaults to `main` everywhere, so setting `gitops_revision` to a feature branch makes the *entire* tree deploy from that branch — letting you validate changes on the local cluster before merging to `main`.

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
# Lint a service's Helm chart
helm lint services/products/demo/chart -f services/products/demo/chart/values-local.yaml
helm lint services/platform/openbao/init -f services/platform/openbao/init/values-local.yaml
helm lint services/platform/openbao/init -f services/platform/openbao/init/values-scaleway.yaml

# Render a chart to inspect output
helm template demo services/products/demo/chart -f services/products/demo/chart/values-local.yaml
helm template openbao-init services/platform/openbao/init -f services/platform/openbao/init/values-local.yaml

# Render bootstrap (confirm revision propagation into services-vendor-<env> / services-app-<env>)
helm template boot bootstrap/ --set env=local --set revision=<branch>
helm template boot bootstrap/ --set env=scaleway --set revision=<branch>

# Validate a vendor Application manifest
kubectl --context minikube apply --dry-run=client -f services/platform/monitoring/applications/local/chart.vendor.yaml
kubectl --context minikube apply --dry-run=client -f services/platform/openbao/applications/local/chart.vendor.yaml
```

## Adding things

**New in-house service (e.g. a new business app or a new `<name>-init`/`<name>-config` chart):**

1. Create the Helm chart under `services/<bucket>/<name>/<subfolder>/` (`<bucket>` = `platform` or `products`)
2. Add `services/<bucket>/<name>/applications/<env>/<subfolder>.app.yaml` with `name`, `namespace`, `chartPath`, `valueFile`, `syncWave` — the `services-app-<env>` ApplicationSet picks it up automatically, no other file to touch. See `services/platform/openbao/applications/local/init.app.yaml` as a template.

**New vendor tool (e.g. cert-manager on a new env):** Add `services/<bucket>/<name>/applications/<env>/chart.vendor.yaml`, a complete Application manifest pointing at the external chart — see `services/platform/openbao/applications/scaleway/chart.vendor.yaml` as a template. The `services-vendor-<env>` Application picks it up automatically.

**New cluster environment (e.g. staging):**

1. `services/<bucket>/<name>/values-staging.yaml` for each chart that needs overrides
2. `services/<bucket>/<name>/applications/staging/` for every service that should run there (vendor and/or app files)
3. `bootstrap/templates/staging.yaml` guarded by `{{- if eq .Values.env "staging" }}`, creating that env's `services-vendor-staging` Application and `services-app-staging` ApplicationSet — copy `bootstrap/templates/local.yaml` and adjust the env name

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
