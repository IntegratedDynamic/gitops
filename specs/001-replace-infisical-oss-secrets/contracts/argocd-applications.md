# Contract: ArgoCD Application Manifests

**Feature**: 001-replace-infisical-oss-secrets
**Date**: 2026-06-21

This document defines the expected shape of ArgoCD Application manifests introduced by this feature. These are the GitOps "contracts" — the declarative interface between the gitops repo and ArgoCD.

---

## Application: openbao (platform tool)

Deployed under `platform/<env>/openbao.yml`. Points to the official OpenBao Helm chart.

```yaml
# platform/local/openbao.yml  (and platform/scaleway/openbao.yml with env-specific overrides)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: openbao
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://openbao.github.io/openbao-helm
    chart: openbao
    targetRevision: <chart-version>         # pin to exact version
    helm:
      values: |
        server:
          ha:
            enabled: false                  # S3 backend does not support HA on Scaleway
          standalone:
            config: |
              ui = true
              listener "tcp" {
                address     = "0.0.0.0:8200"
                tls_disable = true          # TLS terminated at ingress or cluster mesh
              }
              storage "s3" {
                bucket              = "<bucket-name>"
                region              = "fr-par"
                endpoint            = "https://s3.fr-par.scw.cloud"
                s3_force_path_style = true
                # credentials sourced from env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
              }
          extraEnv:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: scaleway-s3-credentials
                  key: access_key
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: scaleway-s3-credentials
                  key: secret_key
  destination:
    server: https://kubernetes.default.svc
    namespace: openbao
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Constraints**:
- `targetRevision` MUST be pinned to a specific chart version (no `latest` or `*`)
- `tls_disable = true` is acceptable for local; staging should configure TLS at ingress level
- `scaleway-s3-credentials` Secret MUST exist before first ArgoCD sync (created by infra Terraform)

---

## Application: openbao-init (init/unseal job)

Deployed under `clusters/<env>/templates/openbao-init.yaml`. Points to an in-house Helm chart at `apps/openbao-init/`.

```yaml
# clusters/local/templates/openbao-init.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: openbao-init
  namespace: argocd
spec:
  project: default
  source:
    repoURL: {{ .Values.repoURL }}
    targetRevision: {{ .Values.revision }}
    path: apps/openbao-init
    helm:
      valueFiles:
        - values-local.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: openbao
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Constraints**:
- Must deploy after the `openbao` Application (ArgoCD sync-wave or dependency annotation)
- The init Job itself is an ArgoCD PostSync hook within the `apps/openbao-init` chart

---

## Application: external-secrets (ESO)

Deployed under `platform/<env>/external-secrets.yml`. Points to the official ESO Helm chart.

```yaml
# platform/local/external-secrets.yml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-secrets
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://charts.external-secrets.io
    chart: external-secrets
    targetRevision: <chart-version>
  destination:
    server: https://kubernetes.default.svc
    namespace: external-secrets
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

---

## Sync Ordering

ArgoCD sync-wave annotations control deployment order:

| Wave | Application | Why |
|------|-------------|-----|
| 0 | `openbao` (platform) | Server must start before init job |
| 1 | `openbao-init` | Init/unseal after server ready |
| 2 | `external-secrets` (ESO) | ClusterSecretStore configured after server unsealed |
| 3 | `<app>` workloads | ExternalSecrets resolved after ESO + server ready |

Sync wave is set via `metadata.annotations: argocd.argoproj.io/sync-wave: "N"` on each Application manifest.

---

## ClusterSecretStore Contract

After ESO is deployed and OpenBao is unsealed, a `ClusterSecretStore` CR is created to connect ESO to OpenBao:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: openbao
spec:
  provider:
    vault:
      server: "http://openbao.openbao.svc.cluster.local:8200"
      path: "kv"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "external-secrets"
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
```

**Constraints**:
- `server` URL uses the cluster-internal DNS name (never an external URL for in-cluster use)
- `role` must match a Kubernetes auth role configured by the init Job
- The `ClusterSecretStore` is managed as part of the `apps/openbao-init` chart (post-unseal configuration)
