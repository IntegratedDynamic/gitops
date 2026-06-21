# Feature Specification: Replace Infisical with OSS Secrets Backend

**Feature Branch**: `001-replace-infisical-oss-secrets`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "Task 2 — Remplacer Infisical par un backend de secrets OSS. Done quand : Infisical retiré, backend secrets OSS en place, état persisté hors cluster éphémère (S3 Scaleway), secrets restaurables après destroy/recreate cluster."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Secrets Accessible via New Backend (Priority: P1)

An operator needs to store and retrieve secrets from the new OSS secrets backend running in the cluster. The backend is deployed via ArgoCD (GitOps) and accessible by workloads. This is the foundational capability: without it, no workload can function.

**Why this priority**: Core capability — everything else depends on the backend being operational.

**Independent Test**: Can be validated by deploying the backend chart, writing a test secret, and reading it back from a pod in the cluster.

**Acceptance Scenarios**:

1. **Given** the OSS secrets backend is deployed via ArgoCD, **When** an operator writes a secret to the backend API, **Then** the secret is stored and retrievable from within the cluster.
2. **Given** the backend is running, **When** a workload requests a secret, **Then** the secret is injected within 5 seconds.
3. **Given** the backend is unreachable, **When** a workload requests a secret, **Then** the workload receives an appropriate error and the backend failure is observable in cluster monitoring.

---

### User Story 2 - Secrets Survive Cluster Destroy/Recreate (Priority: P2)

An operator destroys the ephemeral cluster and recreates it. All secrets previously stored in the backend must be automatically restored from Scaleway Object Storage (S3) without any manual re-entry.

**Why this priority**: This is the key resilience requirement — persistent state is the primary problem with ephemeral clusters, and the whole reason Infisical is being replaced.

**Independent Test**: Destroy cluster, recreate it, verify secrets are available without human intervention. CI pipeline executes this flow.

**Acceptance Scenarios**:

1. **Given** secrets are stored in the backend and the backend's state is persisted to Scaleway S3, **When** the cluster is destroyed and recreated, **Then** the backend is restored and all previously stored secrets are accessible.
2. **Given** the cluster is freshly created, **When** ArgoCD reconciles the backend Application, **Then** the backend automatically unseals/initialises from the Scaleway S3 state without operator input.
3. **Given** the S3 bucket is empty (first deploy), **When** the backend initialises, **Then** a fresh secrets store is created and the initial credentials/unseal keys are persisted to S3.

---

### User Story 3 - Infisical Fully Removed (Priority: P3)

Infisical pods, CRDs, Helm releases, and all GitOps manifests referencing Infisical are absent from the cluster and from the `gitops` repository.

**Why this priority**: Cleanup is mandatory for the "Done when" criterion but does not block P1/P2 functionality.

**Independent Test**: `kubectl get pods -A | grep infisical` returns empty; `git grep -r infisical` (case-insensitive) in the gitops repo returns no active manifests.

**Acceptance Scenarios**:

1. **Given** Infisical was previously deployed, **When** Infisical removal manifests are applied via ArgoCD, **Then** no Infisical pods, CRDs, or Helm resources remain in the cluster.
2. **Given** the gitops repo has been updated, **When** ArgoCD syncs, **Then** no Application or Helm release for Infisical exists in the cluster.
3. **Given** workloads previously sourced secrets from Infisical, **When** Infisical is removed, **Then** those workloads retrieve their secrets from the new backend without interruption.

---

### Edge Cases

- What happens when the Scaleway S3 bucket is temporarily unavailable during backend startup (network partition)?
- How does the backend behave if the S3 state is corrupted or partially written (mid-write crash)?
- What happens if the cluster is destroyed before the first S3 state flush completes?
- How are initial unseal/root credentials stored so they survive cluster recreation but are not exposed in Git?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The secrets backend MUST be an open-source tool available under a licence that requires no paid tier for self-hosted operation (constitution Principle I).
- **FR-002**: The secrets backend MUST be deployed as a GitOps-managed ArgoCD Application in the `gitops` repository, following the existing `platform/<env>/` or `apps/<name>/` conventions.
- **FR-003**: The secrets backend MUST persist its state to the Scaleway Object Storage bucket provisioned by Task 1, such that all secrets survive a full cluster destroy/recreate cycle.
- **FR-004**: On cluster recreate, the backend MUST automatically restore from S3 state without requiring manual operator input (i.e., auto-unseal or equivalent mechanism).
- **FR-005**: The backend MUST expose a secrets API accessible from within-cluster workloads (pod-level network reach).
- **FR-006**: All Infisical manifests, Helm releases, CRDs, and ArgoCD Applications MUST be removed from the `gitops` repo and from the cluster.
- **FR-007**: Workloads that previously sourced secrets from Infisical MUST be migrated to source secrets from the new backend without manual secret re-entry (secrets migrated, not lost).
- **FR-008**: The tool choice (OpenBao vs HashiCorp Vault OSS vs Scaleway Secret Manager) SHALL be deferred to the `/speckit-plan` phase where alternatives are presented and the human makes the final decision (constitution Principle II).
- **FR-009**: The backend configuration (addresses, auth methods, policies) MUST be fully version-controlled in the `gitops` repo (constitution Principle V).
- **FR-010**: CI MUST include a step that validates secrets are restorable after cluster recreate (constitution Principle VII).

### Key Entities

- **Secrets Backend**: The chosen OSS tool instance (tool TBD at plan phase); owns the secrets API, access control, and audit log.
- **Backend State**: The durable, encrypted blob persisted to Scaleway S3; contains all secrets and backend configuration; survives cluster lifecycle.
- **S3 Bucket**: Scaleway Object Storage bucket from Task 1; acts as the external persistence layer for backend state.
- **Secret**: A named key/value (or key/file) pair managed by the backend; consumed by workloads via injection or API call.
- **ArgoCD Application**: GitOps resource in `gitops` repo that declares the backend's desired state; reconciled by ArgoCD.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After cluster destroy and recreate, 100% of previously stored secrets are available to workloads without manual re-entry — verifiable by a CI pipeline that writes secrets, destroys/recreates the cluster, and asserts secret presence.
- **SC-002**: Secret retrieval by a workload completes in under 5 seconds under normal operating conditions.
- **SC-003**: Zero Infisical resources (pods, CRDs, Helm releases, ArgoCD Applications) remain in the cluster after migration — verifiable by `kubectl get all -A` and `helm list -A` returning no Infisical results.
- **SC-004**: Zero Infisical references remain in active GitOps manifests in the `gitops` repo — verifiable by `git grep -ri infisical` returning no matches in `apps/`, `platform/`, `clusters/`, or `bootstrap/`.
- **SC-005**: The backend is deployed exclusively via ArgoCD (GitOps), with no manually applied manifests — verifiable by ArgoCD reporting all backend resources as Synced.
- **SC-006**: The tool used is 100% open-source with no paid-tier requirement for the deployed functionality (constitution Principle I) — verifiable by licence review at plan phase.

## Assumptions

- The Scaleway S3 bucket provisioned by Task 1 (S3 backup foundation) is available, accessible from within the cluster, and has appropriate write permissions for the backend.
- The tool choice (OpenBao / HashiCorp Vault OSS / Scaleway Secret Manager) is deferred to `/speckit-plan`; Scaleway Secret Manager is a candidate but may conflict with Principle I (OSS-first) pending licence/cost review.
- Existing Infisical integrations use a known, documented method (e.g. `InfisicalSecret` CRDs or environment variable injection) that can be mapped to the new backend's equivalent — the exact migration path will be defined at plan time.
- The cluster environments in scope are `local` (minikube) and `staging` (Scaleway Kapsule), consistent with the current `gitops` repo structure.
- Auto-unseal credentials (e.g. Vault/OpenBao transit key or KMS reference) will be stored in S3 alongside the backend state, or injected via a mechanism that does not require human presence on cluster restart.
- A production environment is not yet in scope; only `local` and `staging` need to be validated.
