# Research: Replace Infisical with OSS Secrets Backend

**Feature**: 001-replace-infisical-oss-secrets
**Date**: 2026-06-21
**Status**: Findings complete — tool choice deferred to human (constitution Principle II)

---

## Context

Infisical has zero presence in this repo (no manifests, no CRDs, no Helm releases). This is a greenfield installation of a secrets backend, not a live migration. The primary technical constraints are:

- Deployed via ArgoCD (GitOps) in the existing `platform/<env>/` pattern
- Durable state must survive full cluster destroy/recreate on Scaleway Object Storage (S3-compatible)
- Must auto-recover without operator intervention after cluster recreate
- OSS-first (constitution Principle I); human decides tooling (Principle II)

---

## Decision 1: Tool Choice

*Human decision required before implementation can proceed.*

### Option A — OpenBao

- **Decision**: Use OpenBao as the secrets backend
- **Rationale**: True MPL 2.0 open-source fork of HashiCorp Vault, created after Vault's BSL license change in 2023. Drop-in API-compatible with Vault. Active CNCF sandbox project. Free for all uses with no commercial restrictions.
- **License**: Mozilla Public License 2.0 — satisfies constitution Principle I (OSS-first) with zero ambiguity
- **Helm chart**: `https://openbao.github.io/openbao-helm` → chart `openbao`
- **S3 backend**: Supported via Vault-compatible S3 storage configuration (works with Scaleway Object Storage using `s3_force_path_style = true`)
- **Ecosystem**: Smaller than HashiCorp Vault but growing; compatible with Vault clients, SDKs, and External Secrets Operator
- **Risk**: Less mature than Vault; smaller community, fewer battle-tested production deployments

### Option B — HashiCorp Vault OSS

- **Decision**: Use HashiCorp Vault (latest OSS build under BSL 1.1)
- **Rationale**: The most widely adopted secrets backend in the Kubernetes ecosystem. Largest community, most documentation, richest integrations. BSL 1.1 permits self-hosted use within your own organisation without restriction.
- **License**: Business Source License 1.1 (since v1.14, 2023) — self-hosted internal use is permitted; redistribution as a service is not. Satisfies constitution Principle I in spirit (no paid tier for our use case) but not in letter (not "open source" by OSI definition).
- **Helm chart**: `https://helm.releases.hashicorp.com` → chart `vault`
- **S3 backend**: Fully supported, production-tested
- **Ecosystem**: Largest in class; External Secrets Operator, Vault Agent Injector, CSI provider, many tutorials
- **Risk**: BSL ambiguity if the organisation's use case grows; HashiCorp (now IBM) may tighten terms

### Option C — Scaleway Secret Manager

- **Decision**: Use Scaleway's managed Secret Manager, integrated via External Secrets Operator
- **Rationale**: Fully managed, zero operational burden. Native Scaleway sovereignty (Principle VI). No cluster-level deployment needed; secrets live outside the cluster lifecycle by design.
- **License**: Proprietary SaaS (Scaleway managed service)
- **Integration**: External Secrets Operator (ESO) with Scaleway provider
- **Pricing**: Charged per API call + per-secret storage (consult current Scaleway pricing page — not included here as prices change)
- **Risk**: Violates constitution Principle I (not open-source, not self-hosted). Ongoing per-secret cost. Vendor-dependent.
- **Note**: Option C REQUIRES explicit human approval per constitution Principle I ("Aucun service tiers payant n'est adopté sans l'accord explicite de l'humain"). Do not select without confirming cost acceptability.

### Comparison Matrix

| Criterion | OpenBao (A) | Vault OSS/BSL (B) | Scaleway SM (C) |
|-----------|-------------|-------------------|-----------------|
| OSS-first (P.I) | ✅ MPL 2.0 | ⚠️ BSL 1.1 | ❌ Proprietary |
| Human approval needed | No | No | Yes (cost + non-OSS) |
| Self-hosted | Yes | Yes | No (managed) |
| Paid tier risk | None | None | Yes (API billing) |
| S3 state backend | ✅ | ✅ | N/A (managed) |
| Auto-unseal options | KMS / init job | KMS / init job | N/A |
| Helm chart maturity | Medium | High | N/A (ESO) |
| API compatibility | Vault-compatible | Reference | Scaleway API |
| Community size | Medium (CNCF) | Large | Small |
| Scaleway sovereign (P.VI) | Self-hosted on SCW | Self-hosted on SCW | ✅ Managed on SCW |
| **Constitution compliance** | **Full** | **Partial** | **Requires approval** |

**Decision (confirmed 2026-06-21)**: **Option A — OpenBao**. MPL 2.0 fully satisfies constitution Principle I with no ambiguity. API-compatible with Vault so tooling (ESO, Vault Agent) works unchanged. Active CNCF project with a clear governance path.

---

## Decision 2: Storage Backend Strategy

*Decision: Use S3 storage backend (Scaleway Object Storage)*

OpenBao and Vault both support the `s3` storage stanza, which is compatible with any S3-API-compliant object store. Scaleway Object Storage is S3-compatible and will be used as the primary storage backend.

**Configuration parameters** (Scaleway Object Storage, Paris region):
```hcl
storage "s3" {
  bucket              = "<bucket-name-from-task-1>"
  region              = "fr-par"
  endpoint            = "https://s3.fr-par.scw.cloud"
  access_key          = "<SCW_ACCESS_KEY_ID>"
  secret_key          = "<SCW_SECRET_ACCESS_KEY>"
  s3_force_path_style = true
}
```

**Limitation**: The S3 storage backend does not support high-availability (HA) locking without DynamoDB. Scaleway Object Storage does not offer a DynamoDB-compatible locking API. This means HA mode (`ha_enabled = true`) is not supported with the S3 backend on Scaleway. A single-replica deployment is required.

**Alternative considered — Raft (integrated storage)**:
- Raft is self-contained, no S3 dependency for runtime
- Requires PersistentVolumeClaim (PVC) that would be lost on full cluster destroy
- On cluster recreate, a snapshot restore from S3 is needed (more complex)
- Rejected for this use case: S3 backend is simpler and directly satisfies "state persisted to S3"

---

## Decision 3: Auto-Unseal / Init Strategy

*Decision: S3-backed init Job (Option 3A below)*

The core challenge: on a fresh cluster, OpenBao starts in a sealed state. It needs unseal keys to become operational. Human intervention would break SC-001 (CI-verifiable auto-restore). Three options evaluated:

### Option 3A: S3-backed init Job (recommended)

A Kubernetes Job runs as a post-sync ArgoCD hook. It:
1. Checks if OpenBao is already initialised (`/v1/sys/health`)
2. If **not initialised**: calls `/v1/sys/init` → stores root token + unseal keys as JSON in an S3 object (prefixed `openbao/init-keys/`)
3. If **initialised but sealed**: reads the keys JSON from S3 → calls `/v1/sys/unseal` with each key share

**S3 credentials bootstrap problem**: The init Job needs S3 credentials on a fresh cluster before ArgoCD has run. Solution: the infra repo's Terraform creates a `scaleway-s3-credentials` Kubernetes Secret in the `openbao` namespace during cluster bootstrap (before ArgoCD seed Application is applied). This is a cross-repo dependency documented in the quickstart.

**Security note**: Unseal keys in S3 are unencrypted at rest (S3 object). Mitigation: use S3 bucket versioning + SSE (server-side encryption with Scaleway-managed keys), restrict bucket policy to the init Job's service account.

### Option 3B: Scaleway Key Manager (KMS auto-unseal)

OpenBao supports PKCS#11 and KMIP transit seals. Scaleway Key Manager (SKM) exposes an API but does not (as of 2026-06) expose a PKCS#11 or KMIP endpoint compatible with Vault/OpenBao transit seal. Therefore **not currently viable without a custom proxy**.

### Option 3C: Bank-Vaults Operator

[Bank-Vaults](https://bank-vaults.dev/) is an OSS operator (Apache 2.0) that handles Vault/OpenBao lifecycle including init, unseal, and backup/restore. Adds an additional operator dependency but provides a production-grade solution.

**Trade-off**: Adds complexity (one more operator, CRD, controller) but handles edge cases (partial unseal, key rotation) better than Option 3A.

**Option 3A selected for v1** (simpler, fewer moving parts, constitution Principle I on complexity). Bank-Vaults can be evaluated later.

---

## Decision 4: Kubernetes Integration (How Workloads Consume Secrets)

*Decision: External Secrets Operator (ESO)*

Since Infisical is not deployed, there are no existing workload integrations to migrate. For new integrations, two patterns are viable:

| Pattern | How it works | Trade-off |
|---------|-------------|-----------|
| **External Secrets Operator** | ESO `ExternalSecret` CR syncs secrets from OpenBao into native `Secret` objects | Works with any workload; decoupled from vault agent |
| **Vault Agent Injector** | Sidecar injects secrets as files into pods via annotations | Tighter coupling; richer templating |
| **CSI provider** | Mount secrets as volumes via Secrets Store CSI Driver | Native volume mount; no sidecar |

**Recommendation**: External Secrets Operator (ESO) — most decoupled, cloud-agnostic (can later switch secret backend without changing workloads), active CNCF project. ESO will be a separate platform Application.

---

## Resolved Unknowns

| Unknown | Resolution |
|---------|-----------|
| Tool choice | Presented above — human decides |
| Storage backend | S3 (Scaleway Object Storage) — supports cluster recreate natively |
| Auto-unseal | S3-backed init Job — no additional paid services needed |
| HA mode | Not supported with S3 backend on Scaleway; single replica |
| Workload integration | External Secrets Operator (ESO) |
| S3 credentials bootstrap | Terraform in infra repo creates `scaleway-s3-credentials` Secret before ArgoCD seed |
| Infisical migration | No live migration needed — Infisical never deployed in this repo |
| Scaleway KMS auto-unseal | Not viable currently (no PKCS#11/KMIP endpoint) |

---

## Cross-Repo Dependency

The S3-backed init Job requires Scaleway S3 credentials (access key + secret key) to be present as a Kubernetes Secret at the time of OpenBao's first boot. This Secret must be created by the infra repo's Terraform before the ArgoCD seed Application runs. This dependency must be documented in the infra repo's bootstrap sequence.
