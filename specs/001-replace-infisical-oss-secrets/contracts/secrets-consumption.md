# Contract: Secrets Consumption Interface

**Feature**: 001-replace-infisical-oss-secrets
**Date**: 2026-06-21

This document defines how application workloads consume secrets from the OSS secrets backend. This is the stable interface that application teams depend on.

---

## KV Secret Path Convention

All application secrets are stored in the KV v2 engine under a namespaced path:

```
kv/apps/<app-name>/<secret-name>
```

Examples:
```
kv/apps/demo/db-password
kv/apps/demo/api-key
kv/apps/monitoring/grafana-admin-password
```

**Rules**:
- Path prefix `kv/apps/` is the standard application secrets mount
- `<app-name>` matches the ArgoCD Application name and Kubernetes namespace name
- Secret names use kebab-case
- No nested subpaths beyond `kv/apps/<app>/<name>` (flat structure per app)

---

## ExternalSecret Usage Pattern

Application teams create an `ExternalSecret` CR in their namespace to sync a secret:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: <secret-name>
  namespace: <app-namespace>
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: openbao
    kind: ClusterSecretStore
  target:
    name: <secret-name>              # name of the resulting v1/Secret
    creationPolicy: Owner
  data:
    - secretKey: <field-name>        # key in the resulting v1/Secret
      remoteRef:
        key: apps/<app-name>/<secret-name>   # path in KV v2
        property: <field-name>       # field within the KV secret
```

**Example** — syncing a database password for the `demo` app:
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: demo-db-credentials
  namespace: demo
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: openbao
    kind: ClusterSecretStore
  target:
    name: demo-db-credentials
    creationPolicy: Owner
  data:
    - secretKey: password
      remoteRef:
        key: apps/demo/db-credentials
        property: password
    - secretKey: username
      remoteRef:
        key: apps/demo/db-credentials
        property: username
```

The resulting `v1/Secret` named `demo-db-credentials` is then consumed by pods via `envFrom` or `env.valueFrom.secretKeyRef` as standard Kubernetes patterns.

---

## Policy Naming Convention

Each application has a read-only policy named `<app-name>-read`:

```hcl
# Policy: demo-read
path "kv/data/apps/demo/*" {
  capabilities = ["read", "list"]
}
```

Policies are created by the init Job at bootstrap time from a config map in `apps/openbao-init/`.

---

## Auth Role Convention

Each application namespace has a Kubernetes auth role:

| Role name | Bound SA | Bound namespace | Policy |
|-----------|----------|----------------|--------|
| `external-secrets` | `external-secrets` | `external-secrets` | All app read policies |
| `<app>-workload` | `default` | `<app>` | `<app>-read` |

The `external-secrets` role is the primary one used by ESO. Per-app workload roles are optional for direct Vault agent usage.

---

## Out of Scope (this feature)

- Secret rotation automation (future feature)
- Dynamic database credentials (future feature)
- PKI / certificate issuance (future feature)
- Encryption-as-a-service (transit engine) (future feature)
