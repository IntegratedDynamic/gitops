# Implementation Plan: Replace Infisical with OSS Secrets Backend

**Branch**: `001-replace-infisical-oss-secrets` | **Date**: 2026-06-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-replace-infisical-oss-secrets/spec.md`

## Summary

Deploy an OSS secrets backend (OpenBao recommended, final tool chosen by human per constitution Principle II) as an ArgoCD-managed platform Application. Backend state is persisted to Scaleway Object Storage (S3) so secrets survive full cluster destroy/recreate. A PostSync Kubernetes Job handles init and unseal on every cluster boot from S3-stored keys. External Secrets Operator (ESO) bridges the backend to workloads via native Kubernetes Secrets. Infisical is not deployed in this repo; no live migration is required.

## Technical Context

**Language/Version**: YAML / HCL config only (no application code — GitOps repo)

**Primary Dependencies**:
- OpenBao Helm chart (or HashiCorp Vault Helm chart — human decides, see research.md)
- External Secrets Operator Helm chart (`https://charts.external-secrets.io`)
- Scaleway Object Storage (S3-compatible, fr-par region) — provisioned by Task 1

**Storage**: Scaleway Object Storage (S3 backend for OpenBao state + `openbao/init-keys/` prefix for unseal keys)

**Testing**: `helm lint`, `helm template`, `kubectl apply --dry-run=client`, CI pipeline (minikube ephemeral cluster)

**Target Platform**: Kubernetes — `local` (minikube) and `scaleway` (Kapsule)

**Project Type**: GitOps / platform infrastructure

**Performance Goals**: Secret retrieval < 5 seconds from workload perspective (SC-002)

**Constraints**:
- S3 backend does not support HA on Scaleway (no DynamoDB-compatible locking) → single replica
- `scaleway-s3-credentials` Kubernetes Secret must be created by infra Terraform before ArgoCD first sync
- Auto-unseal via Scaleway KMS is not currently viable (no PKCS#11/KMIP endpoint)

**Scale/Scope**: `local` + `scaleway` environments; single-replica secrets backend per cluster

## Constitution Check

*GATE: Must pass before implementation. Re-checked after design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. OSS-first | ✅ if OpenBao; ⚠️ if Vault BSL; ❌ if Scaleway SM | OpenBao (MPL 2.0) satisfies fully. Vault BSL acceptable for self-hosted. Scaleway SM requires explicit human approval. |
| II. Human decides tooling | ✅ | Three alternatives presented in research.md; human selects before implementation |
| III. Enterprise-grade | ✅ | Secrets management with audit log, policy-based access, namespace isolation |
| IV. Validation by steps | ✅ | Depends on Task 1 (S3 bucket) ✅; CI validates restore scenario (SC-001) |
| V. GitOps-first | ✅ | All config in this repo; deployed via ArgoCD; zero manual kubectl applies |
| VI. Scaleway-sovereign | ✅ | State on Scaleway S3; backend self-hosted on Scaleway Kapsule |
| VII. CI-verifiable acceptance | ✅ | Destroy/recreate scenario executable in CI (see quickstart.md) |

**Gate result**: PASS — no violations, assuming OSS tool (OpenBao or Vault BSL) is selected.

## Project Structure

### Documentation (this feature)

```text
specs/001-replace-infisical-oss-secrets/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: tool comparison, auto-unseal analysis
├── data-model.md        # Phase 1: entities, K8s resource hierarchy, state transitions
├── quickstart.md        # Phase 1: end-to-end validation scenarios (incl. destroy/recreate)
├── contracts/
│   ├── argocd-applications.md   # ArgoCD Application manifest shapes + sync ordering
│   └── secrets-consumption.md  # ExternalSecret pattern, KV path convention, policies
└── tasks.md             # Phase 2 output (/speckit-tasks command)
```

### Source Code Layout (gitops repo root)

```text
platform/
├── local/
│   ├── ingress-nginx.yml          # existing
│   ├── kube-prometheus-stack.yml  # existing
│   ├── openbao.yml                # NEW: OpenBao ArgoCD Application (external Helm)
│   └── external-secrets.yml       # NEW: ESO ArgoCD Application (external Helm)
└── scaleway/
    ├── kube-prometheus-stack.yml  # existing
    ├── openbao.yml                # NEW: env-specific overrides (same chart, scaleway values)
    └── external-secrets.yml       # NEW: ESO for scaleway

apps/
└── openbao-init/                  # NEW: in-house Helm chart for init/unseal Job
    ├── Chart.yaml
    ├── values.yaml                # defaults: openbao address, S3 bucket name
    ├── values-local.yaml          # local overrides
    ├── values-scaleway.yaml       # scaleway overrides
    └── templates/
        ├── serviceaccount.yaml    # SA for the init Job
        ├── role.yaml              # RBAC to read scaleway-s3-credentials Secret
        ├── rolebinding.yaml
        ├── configmap-policies.yaml  # OpenBao policies (HCL) per namespace
        ├── job-init.yaml          # PostSync hook Job (init + unseal + configure)
        └── clustersecretstore.yaml  # ESO ClusterSecretStore pointing to OpenBao

clusters/
├── local/
│   └── templates/
│       ├── demo.yaml              # existing
│       ├── platform.yaml          # existing (picks up new openbao.yml + eso.yml)
│       └── openbao-init.yaml      # NEW: ArgoCD Application for apps/openbao-init
└── scaleway/
    └── templates/
        ├── platform.yaml          # existing (picks up new platform/scaleway/ files)
        └── openbao-init.yaml      # NEW: ArgoCD Application for apps/openbao-init
```

**Structure Decision**: Platform-level tools (OpenBao, ESO) follow the `platform/<env>/` pattern (single YAML, external Helm chart), consistent with `ingress-nginx` and `kube-prometheus-stack`. The init/unseal Job is custom logic → in-house Helm chart under `apps/openbao-init/`. This matches the `apps/demo/` pattern for in-house charts.

## Complexity Tracking

No constitution violations. No complexity justification required.

---

## Implementation Phases (for `/speckit-tasks`)

### Phase A — Tool Decision ✅ DECIDED

**OpenBao selected (2026-06-21)** — MPL 2.0, CNCF sandbox, Vault-compatible API.
Helm chart: `https://openbao.github.io/openbao-helm`, chart name: `openbao`.

### Phase B — Platform Application Manifests

1. Write `platform/local/openbao.yml` — ArgoCD Application pointing to chosen Helm chart
2. Write `platform/scaleway/openbao.yml` — same chart, env-specific values
3. Write `platform/local/external-secrets.yml` — ESO Helm chart
4. Write `platform/scaleway/external-secrets.yml`
5. Validate with `helm lint` and `kubectl apply --dry-run=client`

### Phase C — Init/Unseal Helm Chart (`apps/openbao-init/`)

1. Scaffold Helm chart: `Chart.yaml`, `values.yaml`, `values-local.yaml`, `values-scaleway.yaml`
2. Write PostSync hook Job: shell script logic for init/unseal (reads from S3, calls OpenBao API)
3. Write ServiceAccount + RBAC for the Job
4. Write `configmap-policies.yaml` with per-app HCL policies
5. Write `clustersecretstore.yaml` (ESO ClusterSecretStore)
6. Validate with `helm lint apps/openbao-init/` and `helm template`

### Phase D — Cluster Application Templates

1. Write `clusters/local/templates/openbao-init.yaml` — ArgoCD Application for the init chart
2. Write `clusters/scaleway/templates/openbao-init.yaml`
3. Add ArgoCD sync-wave annotations to control ordering (openbao → openbao-init → ESO → apps)
4. Validate with `helm template loc clusters/local/ --set revision=<branch>`

### Phase E — Local Validation (SC-001 through SC-005)

1. Start minikube, manually create `scaleway-s3-credentials` Secret
2. Push branch, let ArgoCD reconcile (or manual sync)
3. Run Scenario 1 from quickstart.md: verify OpenBao unsealed, write canary secret
4. Run Scenario 2: `minikube delete`, `minikube start`, verify canary secret restored
5. Run Scenario 3: verify ESO syncs secret to workload namespace
6. Run Scenario 4: verify no Infisical resources

### Phase F — CI Pipeline (SC-007 / constitution Principle VII)

1. Write GitHub Actions workflow (or extend existing) to execute destroy/recreate scenario
2. Pipeline uses CI-injected Scaleway credentials for the `scaleway-s3-credentials` Secret
3. Assert all success criteria in CI (no manual validation)
