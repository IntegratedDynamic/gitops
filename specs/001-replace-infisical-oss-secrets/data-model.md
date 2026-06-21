# Data Model: OSS Secrets Backend

**Feature**: 001-replace-infisical-oss-secrets
**Date**: 2026-06-21

This document describes the logical entities and their Kubernetes/GitOps representations for the OSS secrets backend deployment.

---

## Logical Entities

### SecretsBackend (OpenBao / Vault instance)

The core runtime: a single-replica pod serving the secrets API.

| Attribute | Value / Constraint |
|-----------|-------------------|
| Deployment | ArgoCD Application → external Helm chart |
| Replicas | 1 (S3 backend does not support HA on Scaleway) |
| Namespace | `openbao` |
| Ports | 8200 (API/UI), 8201 (cluster — unused in single-replica) |
| Storage | S3 backend (Scaleway Object Storage) |
| State | Persisted to S3 on every write; survives cluster destroy |
| Seal state | Starts sealed; unsealed by init Job on every boot |

### Secret

A named key/value pair managed by the backend.

| Attribute | Constraint |
|-----------|-----------|
| Path | Hierarchical (e.g. `kv/apps/demo/db-password`) |
| Versioning | KV v2 engine — retains version history |
| Access control | Governed by Policy entities |
| Consumer | External Secrets Operator ExternalSecret CR |

### Policy

Defines what paths a given identity can read/write.

| Attribute | Constraint |
|-----------|-----------|
| Scope | Per-namespace or per-application |
| Format | HCL (stored in-cluster; managed via init Job or Vault provider) |
| Minimum | One read-only policy per consuming namespace |

### AuthMethod

How workloads and operators authenticate to the backend.

| Method | Use case |
|--------|---------|
| Kubernetes auth | In-cluster workloads and ESO; bound to ServiceAccount |
| Token | Init Job bootstrap only; root token stored in S3, rotated immediately |

### InitJob (Kubernetes Job)

An ArgoCD post-sync hook Job that bootstraps or unseals the backend on every cluster boot.

| Attribute | Value |
|-----------|-------|
| Trigger | ArgoCD PostSync hook on the secrets-backend Application |
| Function | Init (first boot) or unseal (subsequent boots) |
| S3 path | `openbao/init-keys/<cluster-env>.json` |
| Credentials | `scaleway-s3-credentials` Secret in `openbao` namespace |
| Idempotent | Yes — no-op if already initialised and unsealed |

### S3BucketState

The external persistence layer. One S3 path per environment.

| Attribute | Value |
|-----------|-------|
| Provider | Scaleway Object Storage (fr-par) |
| Bucket | Shared with Task 1 S3 backup bucket (separate prefix) |
| Prefix — backend data | `openbao/data/` (written by OpenBao storage backend) |
| Prefix — init keys | `openbao/init-keys/` (written by init Job) |
| Encryption | SSE with Scaleway-managed keys |
| Access | Limited to init Job ServiceAccount (IAM policy) |

### ExternalSecretsCR

The Kubernetes Custom Resource that syncs a secret from the backend into a native `v1/Secret`.

| Attribute | Value |
|-----------|-------|
| Kind | `ExternalSecret` (External Secrets Operator) |
| Source | SecretStore pointing to OpenBao Kubernetes auth |
| Target | Native `v1/Secret` in the consuming namespace |
| Refresh interval | Configurable per secret (default: 1h) |

---

## Kubernetes Resource Hierarchy

```
Namespace: openbao
├── Deployment: openbao                    # main server pod (1 replica)
├── Service: openbao                       # ClusterIP :8200
├── ServiceAccount: openbao               # for Kubernetes auth
├── ConfigMap: openbao-config             # HCL config (S3 backend, listener)
├── Secret: scaleway-s3-credentials       # created by infra Terraform
└── Job: openbao-init (PostSync hook)     # init/unseal on each boot

Namespace: openbao-system (ESO)
├── Deployment: external-secrets          # ESO controller
├── ClusterSecretStore: openbao           # cluster-wide ESO SecretStore
└── (per app namespace) ExternalSecret    # syncs secret into v1/Secret

Namespace: <app> (e.g. demo)
└── Secret: <name>                        # synced by ESO from OpenBao
```

---

## State Transitions

### First Boot (initialisation)
```
OpenBao Pod starts → sealed (no data in S3)
    → InitJob: detect "not initialized"
    → Call /v1/sys/init (5 key shares, threshold 3)
    → Store root token + unseal keys to S3 (openbao/init-keys/<env>.json)
    → Call /v1/sys/unseal × 3 (with 3 of 5 key shares)
    → OpenBao: unsealed ✅
    → InitJob: enable KV v2, Kubernetes auth method, create policies
    → InitJob: revoke root token (use AppRole or K8s auth for subsequent access)
```

### Subsequent Boots (cluster recreate or pod restart)
```
OpenBao Pod starts → sealed (data in S3, keys in S3)
    → InitJob: detect "initialized but sealed"
    → Read unseal keys from S3
    → Call /v1/sys/unseal × 3
    → OpenBao: unsealed ✅
    → InitJob: no-op on KV/auth (already configured)
```

### Secret Consumption
```
Workload pod scheduled
    → ESO ExternalSecret reconciles
    → ESO authenticates to OpenBao via Kubernetes auth (ServiceAccount token)
    → ESO reads secret from KV v2 path
    → ESO writes/updates v1/Secret in workload namespace
    → Workload reads from v1/Secret (env var or volume mount)
```

---

## Validation Rules

- `openbao/init-keys/<env>.json` MUST exist in S3 before cluster recreate can self-heal (created on first init)
- `scaleway-s3-credentials` Secret MUST be present in `openbao` namespace before ArgoCD sync runs the PostSync hook
- Init Job MUST be idempotent — multiple runs must not re-initialise an already-initialised backend
- Root token MUST be revoked after initial setup; subsequent admin access via Kubernetes auth + admin policy
