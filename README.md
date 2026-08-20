# gitops

ArgoCD GitOps repository. Contains all application and platform definitions deployed to Kubernetes clusters.

The companion infrastructure repository (Terraform + Minikube) bootstraps ArgoCD and points it here.

---

## Daily login (quick reference)

Two logins to redo regularly (not one-time setup) — both expire, so run them again
whenever a command starts failing with an auth error:

```bash
# Terraform state (S3 backend, infrastructure repo) — needed before any terraform command.
aws sso login --profile infrastructure

# OpenBao CLI (bao) — needed to read/write secrets directly with `bao kv ...`
# against the OIDC-gated OpenBao instance this repo deploys (platform/<env>/openbao.yml).
# Requires BAO_ADDR pointed at the exposed UI (export BAO_ADDR="https://openbao.scalepack.fr/").
# Token TTL is short (role-dependent, ~1h for the admin role) — relogin when it expires.
bao login -method=oidc
```

---

## How it works

ArgoCD manages itself entirely through this repo, one directory per service, via two discovery
mechanisms per cluster instead of a hand-maintained app-of-apps chart:

```
[Terraform] ──bootstraps──> bootstrap    (ArgoCD Application)
                                │
                                └──creates, for env=local──┐
                                                            │
                       ┌────────────────────────────────────┴───────────────────────────────┐
                       ▼                                                                     ▼
            services-vendor-local                                                 services-app-local
          (Application, directory recurse)                                          (ApplicationSet)
                       │                                                                     │
          watches every services/*/*/applications/local/*.vendor.yaml          expands every services/*/*/applications/local/*.app.yaml
          and applies it as-is (external Helm charts:                          into a full Application (in-house charts: demo,
          ingress-nginx, kube-prometheus-stack, openbao...)                    openbao-init, secrets-sync...), injecting repoURL/revision
```

- **Terraform** creates a single seed Application called `bootstrap`
- **`bootstrap`** reads `bootstrap/templates/local.yaml`, which creates `services-vendor-local` and `services-app-local` directly (no intermediate `clusters/local/` chart)
- Each service's own `services/<bucket>/<name>/applications/local/` folder is what "registers" its Applications — nothing outside that folder needs to change to add or remove one

---

## Repository structure

```
gitops/
│
├── bootstrap/
│   └── templates/local.yaml     # creates services-vendor-local + services-app-local
│
├── services/
│   ├── platform/                # infra: openbao, cert-manager, gateway, dex, monitoring, ...
│   │   └── openbao/
│   │       ├── init/            # in-house chart, restore-at-boot Job only — no ESO
│   │       │                    #   coupling; the ClusterSecretStore it feeds lives in
│   │       │                    #   services/platform/secrets-sync/config instead
│   │       │   ├── Chart.yaml
│   │       │   ├── values.yaml
│   │       │   ├── values-local.yaml
│   │       │   └── templates/...
│   │       └── applications/
│   │           └── local/
│   │               ├── chart.vendor.yaml   # loads the openbao-helm chart, as-is
│   │               └── init.app.yaml       # {name, namespace, chartPath, valueFile, syncWave}
│   │
│   └── products/                # revenue-generating apps
│       └── demo/
│           ├── chart/            # the demo nginx Helm chart
│           └── applications/
│               └── local/app.app.yaml
│
└── charts/
    └── sso-guard/                # shared library chart, consumed as a dependency (not deployed on its own)
```

---

## Adding a new in-house service

1. Create the Helm chart under `services/<bucket>/<your-service>/<subfolder>/` (`<bucket>` is `platform` for infra, `products` for revenue apps):

```
services/products/your-app/chart/
├── Chart.yaml
├── values.yaml           # sensible defaults, treat as prod baseline
├── values-local.yaml     # local overrides
└── templates/
    └── ...
```

2. Register it by adding a params file — no other file to touch:

```yaml
# services/products/your-app/applications/local/app.app.yaml
name: your-app
namespace: your-app
chartPath: services/products/your-app/chart
valueFile: values-local.yaml
syncWave: "0"
```

The `services-app-local` ApplicationSet picks it up automatically — no manual sync needed.

---

## Adding a new cluster environment

Say you're adding `staging`:

1. **Add environment values** for each chart that needs overrides:
   ```
   services/products/demo/chart/values-staging.yaml
   ```

2. **Register every service** that should run on staging, under its own `applications/staging/`:
   ```
   services/platform/ingress-nginx/applications/staging/chart.vendor.yaml
   services/products/demo/applications/staging/app.app.yaml
   ```

3. **Add a bootstrap manifest** in `bootstrap/templates/staging.yaml` — copy `local.yaml`, rename `services-vendor-local`/`services-app-local` to `-staging`, and change the `directory.include` / generator `files.path` glob from `local` to `staging`.

4. **Point Terraform** (or your cluster provisioner) at `bootstrap/` with `env=staging` to seed it.

Only the values files and `applications/staging/` entries differ — the charts themselves are never duplicated.

---

## Adding a vendor tool (e.g. cert-manager)

Vendor tools are ArgoCD Applications that install Helm charts from external repositories — written as
a complete, self-contained manifest (no shared template, since these tend to need very different
things: inline values, `ignoreDifferences`, OCI sources...). Add one file per tool per env:

```yaml
# services/platform/cert-manager/applications/local/chart.vendor.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cert-manager
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://charts.jetstack.io
    chart: cert-manager
    targetRevision: v1.17.0
    helm:
      values: |
        installCRDs: true
  destination:
    server: https://kubernetes.default.svc
    namespace: cert-manager
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

The `services-vendor-local` Application (a plain directory-recurse source) picks it up automatically.

---

## Local development workflow

**Smoke test** (destroy + rebuild everything from scratch):
```bash
# from the infrastructure repo
mise run reset && mise run dev
```

ArgoCD takes a few minutes to reconcile all apps — be patient. The difference between "still syncing" and "actually stuck" is visible in:
```bash
kubectl --context minikube get applications -n argocd
```

**If `bootstrap`'s sync operation looks stuck** (same `operationState.message` for several minutes, no new Applications appearing): check what revision it's actually running against —
```bash
kubectl get application bootstrap -n argocd -o jsonpath='{.status.operationState.operation.sync.revision}'
```
Confirmed live 2026-08-20: a hard refresh (`kubectl annotate application bootstrap -n argocd argocd.argoproj.io/refresh=hard --overwrite`) or re-patching `.operation` with a new sync request does **not** reliably restart an in-flight operation — it can keep retrying against a stale revision it captured when it first started, even after newer commits landed on the tracked branch. What actually forces a genuinely fresh operation:
```bash
kubectl patch application bootstrap -n argocd --type merge -p '{"operation":null}'
```
Clearing `.operation` outright (not just re-setting it) makes the controller pick up a brand new operation against current `HEAD` on its own, via the existing automated+selfHeal sync policy — no need to manually re-specify `sync.revision` yourself.

**Important:** before running, check `infrastructure/02-cluster/local/nico.auto.tfvars` — it contains the `gitops_revision` variable that controls which branch of this repo ArgoCD will deploy from. If you're testing a feature branch, set it there:
```hcl
gitops_revision = "feat/your-branch"
```
If it points to `main` and your changes aren't merged yet, ArgoCD will deploy the old code.

**Validate OpenBao is up:**
```bash
kubectl --context minikube get clustersecretstore openbao
# READY=True → OpenBao running, unsealed, ESO connected
```

---

## Accessing the demo app (local)

After `mise run reset && mise run dev` in the infrastructure repo:

```bash
# Add demo.local to /etc/hosts
echo "$(minikube ip)  demo.local" | sudo tee -a /etc/hosts

# Check it's up
curl http://demo.local
```
