# gitops

ArgoCD GitOps repository. Contains all application and platform definitions deployed to Kubernetes clusters.

The companion infrastructure repository (Terraform + Minikube) bootstraps ArgoCD and points it here.

---

## How it works

ArgoCD manages itself entirely through this repo via an **App-of-Apps** pattern:

```
[Terraform] ──bootstraps──> bootstrap    (ArgoCD Application)
                                │
                                └──watches──> clusters/local/
                                                    │
                                          ┌─────────┴──────────┐
                                          ▼                     ▼
                                       platform              demo (+ future apps)
                                          │
                                    platform/local/
                                    (ingress-nginx, ...)
```

- **Terraform** creates a single seed Application called `bootstrap`
- **`bootstrap`** reads `bootstrap/local.yaml` and creates the `local` Application
- **`local`** reads `clusters/local/` and creates one Application per file found there
- Each Application then manages its own resources on the cluster

---

## Repository structure

```
gitops/
│
├── bootstrap/
│   └── local.yaml              # "local" ArgoCD Application (watches clusters/local/)
│
├── clusters/
│   └── local/                  # One directory per cluster environment
│       ├── demo.yml            # Deploys the demo Helm chart (values-local.yaml)
│       └── platform.yml        # Deploys platform tools (points to platform/local/)
│
├── platform/
│   └── local/                  # Platform tools for the local cluster
│       └── ingress-nginx.yml   # ArgoCD Application: ingress-nginx Helm release
│
└── apps/
    └── demo/                   # Helm chart for the demo nginx app
        ├── Chart.yaml
        ├── values.yaml         # Default values (production-ish baseline)
        ├── values-local.yaml   # Local overrides (smaller resources, demo.local host)
        └── templates/
            ├── deployment.yaml
            ├── service.yaml
            └── ingress.yaml
```

---

## Adding a new application

1. Create a Helm chart under `apps/<your-app>/`:

```
apps/your-app/
├── Chart.yaml
├── values.yaml           # sensible defaults, treat as prod baseline
├── values-local.yaml     # local overrides
└── templates/
    └── ...
```

2. Add an ArgoCD Application in `clusters/local/your-app.yml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: your-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/IntegratedDynamic/gitops.git
    targetRevision: main
    path: apps/your-app
    helm:
      valueFiles:
        - values-local.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: your-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

ArgoCD picks it up automatically — no manual sync needed.

---

## Adding a new cluster environment

Say you're adding `staging`:

1. **Add environment values** for each app that needs overrides:
   ```
   apps/demo/values-staging.yaml
   ```

2. **Add platform tools** for the new cluster:
   ```
   platform/staging/ingress-nginx.yml   # e.g. with LoadBalancer instead of NodePort
   ```

3. **Add cluster entry point** in `clusters/staging/`:
   ```
   clusters/staging/demo.yml      # same structure as local, different valueFiles
   clusters/staging/platform.yml  # points to platform/staging/
   ```

4. **Add a bootstrap manifest** in `bootstrap/`:
   ```
   bootstrap/staging.yaml   # same structure as local.yaml, points to clusters/staging/
   ```

5. **Point Terraform** (or your cluster provisioner) at `bootstrap/staging.yaml` to seed it.

Only the values files and cluster entry points differ — the charts themselves are never duplicated.

---

## Adding a platform tool (e.g. cert-manager)

Platform tools are ArgoCD Applications that install Helm charts from external repositories.
Add a file per tool under `platform/<env>/`:

```yaml
# platform/local/cert-manager.yml
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

The `platform` App-of-Apps picks it up automatically.

---

## Accessing the demo app (local)

After `mise run reset && mise run dev` in the infrastructure repo:

```bash
# Add demo.local to /etc/hosts
echo "$(minikube ip)  demo.local" | sudo tee -a /etc/hosts

# Check it's up
curl http://demo.local
```
