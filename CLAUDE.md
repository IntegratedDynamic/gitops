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
```

## Validation commands

Always target the local cluster explicitly to avoid accidental execution against the wrong context (`minikube` is local, but the active context can change):

```bash
# Lint a Helm chart
helm lint apps/demo/ -f apps/demo/values-local.yaml

# Render an app chart to inspect output
helm template demo apps/demo/ -f apps/demo/values-local.yaml

# Render the app-of-apps charts (confirm revision propagation)
helm template boot bootstrap/ --set env=local --set revision=<branch>
helm template loc clusters/local/ --set revision=<branch>

# Validate a platform Application manifest
kubectl --context minikube apply --dry-run=client -f platform/local/kube-prometheus-stack.yml
```

## Adding things

**New app:** Create `apps/<name>/` Helm chart + a `clusters/local/templates/<name>.yaml` Application template using `{{ .Values.revision }}` / `{{ .Values.repoURL }}`. See `clusters/local/templates/demo.yaml` as a template.

**New cluster environment (e.g. staging):**
1. `apps/<name>/values-staging.yaml` for each app that needs overrides
2. `platform/staging/` for cluster-level tools
3. `clusters/staging/` chart with the exhaustive Application templates
4. `bootstrap/templates/staging.yaml` guarded by `{{- if eq .Values.env "staging" }}` as the entry point for external provisioners

**New platform tool:** Add a file to `platform/<env>/` following `platform/local/ingress-nginx.yml`.
