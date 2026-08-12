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

### The `applications/<env>/` file formats — env-dependent

**`local`** still uses the original two-format split:

- **`*.vendor.yaml`** — a complete, hand-written ArgoCD `Application` manifest that loads an external Helm chart. Free-form: inline values, `ignoreDifferences`, OCI sources, `ServerSideApply`, whatever that tool needs. Discovered by a plain directory-recurse Application (`services-vendor-local`, created by `bootstrap/templates/local.yaml`) that applies anything matching `services/*/*/applications/local/*.vendor.yaml` as-is — no templating.
- **`*.app.yaml`** — a small params file (`name`, `namespace`, `chartPath`, `valueFile`, `syncWave`) for an Application that loads one of *our own* charts from this repo. Expanded by the `services-app-local` ApplicationSet (git `files` generator, `goTemplate: true`, matching `services/*/*/applications/local/*.app.yaml`), whose template injects `repoURL`/`targetRevision`.

**`scaleway` was migrated off that split (2026-08-11)** — the two-format system meant sync-wave ordering could never work across a vendor chart and the in-house `-init`/`-config` app that fed it OpenBao-sourced Secrets (confirmed live: Velero/external-dns/Dex/Grafana/the DNS01 ACME webhook all raced OpenBao's restore on a fresh cluster boot). A first fix tried an ApplicationSet + Progressive Syncs (`RollingSync`) — also confirmed live NOT to work: RollingSync doesn't gate the *first-ever* creation/sync of Applications an ApplicationSet generates, only staged updates to an already-existing fleet, so every "stage" synced simultaneously on a fresh cluster anyway.

What actually works, and what `scaleway` uses now: **no `*.app.yaml`/`*.vendor.yaml` files and no ApplicationSet at all** for this env. Every scaleway Application (22 of them, both external-Helm-chart and in-house) is defined as one entry in `bootstrap/values.yaml`'s `scalewayApps` list (`name`, `namespace`, `chartPath`, `valueFile`, `wave`) and rendered directly by `bootstrap/templates/scaleway.yaml` as a literal `Application` manifest — a managed resource of the `bootstrap` Application's own sync, where plain `argocd.argoproj.io/sync-wave` genuinely is honored (proven mechanism, not Beta, works for both first sync and later updates). External charts still get a thin local wrapper chart instead of a hand-written manifest: a `Chart.yaml` declaring the real chart as a Helm `dependencies:` entry (see any `services/platform/*/chart/Chart.yaml` on scaleway, e.g. `services/platform/openbao/chart`), with its values re-nested one level under the dependency's name in `values-<env>.yaml`. Ordering is six coarse waves (`0`=openbao, `1`=eso, `2`=velero, `3`=platform, `4`=monitoring, `5`=products) — see the comment atop `bootstrap/values.yaml`'s `scalewayApps` list.

Adding or removing a scaleway Application means editing `bootstrap/values.yaml`'s `scalewayApps` list directly (not dropping a file in that service's `applications/scaleway/` folder — that pattern is `local`-only now).

### Revision propagation (feature-branch testing)

`revision` threads from the provisioner through the whole tree: the infra repo's `gitops_revision` → the `bootstrap` Application's `revision` Helm param → each env's generator/template. For `local`: `services-vendor-local`'s `source.targetRevision` plus `services-app-local`'s ApplicationSet generator/template. For `scaleway`: every `scalewayApps` entry's rendered `Application.spec.source.targetRevision` in `bootstrap/templates/scaleway.yaml`, templated straight from `.Values.revision`. It defaults to `main` everywhere, so setting `gitops_revision` to a feature branch makes the *entire* tree deploy from that branch — letting you validate changes before merging to `main`.

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

**New vendor tool on `local`:** Add `services/<bucket>/<name>/applications/local/chart.vendor.yaml`, a complete Application manifest pointing at the external chart — see `services/platform/openbao/applications/local/chart.vendor.yaml` as a template. The `services-vendor-local` Application picks it up automatically.

**New vendor tool on `scaleway`:** no `*.vendor.yaml` here (see above) — create a thin wrapper chart instead (`services/<bucket>/<name>/chart/Chart.yaml` with a `dependencies:` entry for the real chart, `values-scaleway.yaml` with its values nested under the dependency's name) plus `services/<bucket>/<name>/applications/scaleway/chart.app.yaml` (`name`, `namespace`, `chartPath`, `valueFile`, `stage`) — see `services/platform/openbao/chart` + `bootstrap/values.yaml` as a template. The `services-scaleway` ApplicationSet picks it up automatically; pick whichever of the six stages matches what it depends on (or add its own stage + `RollingSync` step in `bootstrap/templates/scaleway.yaml` if it doesn't fit any of them).

**New cluster environment (e.g. staging):**

1. `services/<bucket>/<name>/values-staging.yaml` for each chart that needs overrides
2. `services/<bucket>/<name>/applications/staging/` for every service that should run there (vendor and/or app files)
3. `bootstrap/templates/staging.yaml` guarded by `{{- if eq .Values.env "staging" }}`, creating that env's `services-vendor-staging` Application and `services-app-staging` ApplicationSet — copy `bootstrap/templates/local.yaml` and adjust the env name
