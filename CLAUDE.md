# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

ArgoCD GitOps repository for a Kubernetes setup. Deployment happens by pushing to `main` — ArgoCD watches this repo and reconciles automatically.

The companion infrastructure repo (Terraform + Minikube) bootstraps ArgoCD and seeds it with a `bootstrap` Application that points here.

## Directory roles

**`bootstrap/`** — Entry points designed to be referenced by external repos (e.g. the Terraform infra repo) via git. Each file creates the top-level Application for a cluster, which then watches the matching `clusters/<env>/` directory.

**`clusters/<env>/`** — Exhaustive declarative state of what runs in a given cluster. One `.yml` file per Application; ArgoCD picks up every file here automatically.

**`apps/<name>/`** — Helm charts for in-house applications. `values.yaml` is the baseline; `values-<env>.yaml` holds per-environment overrides. Charts are never duplicated across environments.

**`platform/<env>/`** — Shared cluster-level tools (ingress-nginx, cert-manager, etc.) as ArgoCD Applications pointing to external Helm repos. Factored out to avoid repeating common infrastructure across clusters.

## Doctor commands

Always use `--context minikube` to avoid hitting the wrong cluster:

```bash
minikube status                                                    # cluster running?
kubectl --context minikube get pods -n argocd                     # ArgoCD healthy?
kubectl --context minikube get applications -n argocd             # apps synced?
kubectl --context minikube get pods -n ingress-nginx              # ingress up?
```

## Validation commands

Always target the local cluster explicitly to avoid accidental execution against the wrong context (`minikube` is local, but the active context can change):

```bash
# Lint a Helm chart
helm lint apps/demo/ -f apps/demo/values-local.yaml

# Render a chart to inspect output
helm template demo apps/demo/ -f apps/demo/values-local.yaml

# Validate an ArgoCD Application manifest
kubectl --context minikube apply --dry-run=client -f clusters/local/demo.yml
```

## Adding things

**New app:** Create `apps/<name>/` Helm chart + `clusters/local/<name>.yml` ArgoCD Application referencing the env override file. See `clusters/local/demo.yml` as a template.

**New cluster environment (e.g. staging):**
1. `apps/<name>/values-staging.yaml` for each app that needs overrides
2. `platform/staging/` for cluster-level tools
3. `clusters/staging/` with the exhaustive Application list
4. `bootstrap/staging.yaml` as the entry point for external provisioners

**New platform tool:** Add a file to `platform/<env>/` following `platform/local/ingress-nginx.yml`.
