# Tasks: Replace Infisical with OSS Secrets Backend (OpenBao)

**Input**: Design documents from `specs/001-replace-infisical-oss-secrets/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tool decision**: OpenBao (MPL 2.0) — confirmed 2026-06-21

**No tests requested** — validation is done via the quickstart.md scenarios and the CI pipeline.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to ([US1], [US2], [US3])
- Exact file paths in every description

---

## Phase 1: Setup — Init Chart Scaffold

**Purpose**: Create the `apps/openbao-init/` Helm chart structure. All subsequent phases add templates into this chart.

- [x] T001 Create `apps/openbao-init/Chart.yaml` — name: `openbao-init`, version: `0.1.0`, description: "OpenBao init, unseal, and ESO configuration"
- [x] T002 Create `apps/openbao-init/values.yaml` with defaults: `openbao.address`, `openbao.namespace`, `s3.bucket`, `s3.region`, `s3.endpoint`, `s3.keysPrefix`, `policies` list (empty), `eso.clusterSecretStoreName`
- [x] T003 [P] Create `apps/openbao-init/values-local.yaml` — overrides: `openbao.address: http://openbao.openbao.svc.cluster.local:8200`, `s3.bucket: <bucket-from-task-1>`, `s3.endpoint: https://s3.fr-par.scw.cloud`
- [x] T004 [P] Create `apps/openbao-init/values-scaleway.yaml` — same bucket/endpoint as local (same Scaleway S3), different `s3.keysPrefix: openbao/init-keys/scaleway.json` to avoid collision with local env keys

**Checkpoint**: `apps/openbao-init/` exists with chart metadata and all values files

---

## Phase 2: Foundational — Platform Manifests (OpenBao + ESO)

**Purpose**: Declare OpenBao and External Secrets Operator as ArgoCD Applications for both environments. These are prerequisites for any secrets to be accessible.

**⚠️ CRITICAL**: US1 cannot proceed until this phase is complete (OpenBao must be declared before the init job can target it)

- [x] T005 Write `platform/local/openbao.yml` — ArgoCD Application pointing to `https://openbao.github.io/openbao-helm` chart `openbao`; destination namespace `openbao`; Helm values inline: `server.ha.enabled: false`, `server.standalone.config` with S3 storage stanza (bucket, region, endpoint `https://s3.fr-par.scw.cloud`, `s3_force_path_style = true`, credentials via env vars from `scaleway-s3-credentials` Secret); `server.extraEnv` with `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from `scaleway-s3-credentials`; `syncOptions: [CreateNamespace=true]`
- [x] T006 [P] Write `platform/scaleway/openbao.yml` — identical structure to `platform/local/openbao.yml`; same S3 endpoint (Scaleway fr-par); pin same chart version
- [x] T007 [P] Write `platform/local/external-secrets.yml` — ArgoCD Application pointing to `https://charts.external-secrets.io` chart `external-secrets`; destination namespace `external-secrets`; no custom values needed for v1; `syncOptions: [CreateNamespace=true]`
- [x] T008 [P] Write `platform/scaleway/external-secrets.yml` — identical to `platform/local/external-secrets.yml`; pin same chart version
- [x] T009 Validate all four platform manifests: run `kubectl --context minikube apply --dry-run=client -f platform/local/openbao.yml`, same for the other three files; fix any schema errors

**Checkpoint**: Four platform manifests pass `--dry-run=client`; ArgoCD can render them once deployed

---

## Phase 3: User Story 1 — Secrets Accessible via New Backend (Priority: P1) 🎯 MVP

**Goal**: OpenBao is deployed via ArgoCD, the init Job unseals it on boot, and a secret can be written and read.

**Independent Test**: Scenario 1 from `specs/001-replace-infisical-oss-secrets/quickstart.md` — deploy, verify `bao status` shows `Sealed: false`, write `kv/apps/test/smoke-test value=hello`, read it back successfully.

### Init Job RBAC

- [x] T010 [US1] Write `apps/openbao-init/templates/serviceaccount.yaml` — ServiceAccount named `openbao-init` in `{{ .Release.Namespace }}`; used by the init Job to access the `scaleway-s3-credentials` Secret
- [x] T011 [P] [US1] Write `apps/openbao-init/templates/role.yaml` — Role named `openbao-init`; rules: `get` on `secrets` resource, resource name `scaleway-s3-credentials`
- [x] T012 [P] [US1] Write `apps/openbao-init/templates/rolebinding.yaml` — RoleBinding binding `openbao-init` Role to `openbao-init` ServiceAccount

### Policies ConfigMap

- [x] T013 [US1] Write `apps/openbao-init/templates/configmap-policies.yaml` — ConfigMap named `openbao-policies`; data keys are policy names (e.g. `demo-read.hcl`); each value is an HCL policy granting `["read", "list"]` on `kv/data/apps/<app>/*`; policies driven by `{{ .Values.policies }}` list in values so new apps can be added without template changes

### Init/Unseal Job

- [x] T014 [US1] Write `apps/openbao-init/templates/job-init.yaml` — Kubernetes Job with `argocd.argoproj.io/hook: PostSync` and `argocd.argoproj.io/hook-delete-policy: HookSucceeded` annotations; image: `alpine/k8s` or equivalent with `curl`, `jq`, `aws-cli`; serviceAccountName: `openbao-init`; env vars: `OPENBAO_ADDR` from values, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from `scaleway-s3-credentials` Secret; shell script logic (in a ConfigMap or inline):
  1. Wait for OpenBao to respond on `:8200/v1/sys/health` (retry loop, 60s timeout)
  2. Read `bao status -format=json`; extract `.initialized` and `.sealed`
  3. **If not initialized**: call `bao operator init -key-shares=5 -key-threshold=3 -format=json`; write JSON to S3 at `{{ .Values.s3.keysPrefix }}`; extract 3 unseal keys and unseal; enable KV v2 (`bao secrets enable -path=kv kv-v2`); enable Kubernetes auth (`bao auth enable kubernetes`; configure with in-cluster API server); apply all policies from ConfigMap; create `external-secrets` Kubernetes auth role bound to `external-secrets` ServiceAccount in `external-secrets` namespace with all policies; revoke root token
  4. **If initialized but sealed**: read JSON from S3; extract 3 unseal key shares; call `bao operator unseal` 3 times

### ESO ClusterSecretStore

- [x] T015 [P] [US1] Write `apps/openbao-init/templates/clustersecretstore.yaml` — `ClusterSecretStore` CR named `{{ .Values.eso.clusterSecretStoreName }}`; provider: vault; server: `{{ .Values.openbao.address }}`; path: `kv`; version: `v2`; auth.kubernetes.mountPath: `kubernetes`; auth.kubernetes.role: `external-secrets`; auth.kubernetes.serviceAccountRef: `external-secrets` SA in `external-secrets` namespace

### Cluster Application Templates

- [x] T016 [US1] Write `clusters/local/templates/openbao-init.yaml` — ArgoCD Application for `apps/openbao-init` chart; `source.repoURL: {{ .Values.repoURL }}`; `source.targetRevision: {{ .Values.revision }}`; `source.path: apps/openbao-init`; `source.helm.valueFiles: [values-local.yaml]`; destination namespace: `openbao`; automated sync with prune + selfHeal + CreateNamespace=true
- [x] T017 [P] [US1] Write `clusters/scaleway/templates/openbao-init.yaml` — identical to T016 but `source.helm.valueFiles: [values-scaleway.yaml]`

### Sync Wave Ordering

- [x] T018 [US1] Add `argocd.argoproj.io/sync-wave` annotations to all six affected manifests:
  - `platform/local/openbao.yml` and `platform/scaleway/openbao.yml` → wave `"0"` (server starts first)
  - `clusters/local/templates/openbao-init.yaml` and `clusters/scaleway/templates/openbao-init.yaml` → wave `"1"` (init job after server)
  - `platform/local/external-secrets.yml` and `platform/scaleway/external-secrets.yml` → wave `"2"` (ESO after init configures ClusterSecretStore)

### Validation

- [x] T019 [US1] Validate init chart: run `helm lint apps/openbao-init/ -f apps/openbao-init/values-local.yaml` and `helm template openbao-init apps/openbao-init/ -f apps/openbao-init/values-local.yaml`; fix any lint errors
- [ ] T020 [US1] Local smoke test — Scenario 1 from `specs/001-replace-infisical-oss-secrets/quickstart.md`: start minikube, manually create `scaleway-s3-credentials` Secret, push branch, trigger ArgoCD sync, verify `bao status` shows `Sealed: false`, write `kv/apps/test/smoke-test value=hello`, read it back

**Checkpoint**: `bao kv get kv/apps/test/smoke-test` returns `value = hello`. US1 is complete and independently validated.

---

## Phase 4: User Story 2 — Secrets Survive Cluster Destroy/Recreate (Priority: P2)

**Goal**: A canary secret written before cluster destruction is automatically available after cluster recreate — no operator input required.

**Independent Test**: Scenario 2 from `specs/001-replace-infisical-oss-secrets/quickstart.md` — write canary, `minikube delete`, `minikube start`, ArgoCD re-syncs, canary value matches pre-destroy value. CI pipeline executes this automatically.

### CI Pipeline

- [x] T021 [US2] Create `.github/workflows/ci.yml` with two jobs:
  - **job `helm-lint`**: runs on every PR; steps: checkout → `helm lint apps/openbao-init/ -f apps/openbao-init/values-local.yaml` → `helm lint apps/openbao-init/ -f apps/openbao-init/values-scaleway.yaml` → `helm template boot bootstrap/ --set env=local --set revision=main` → `helm template loc clusters/local/ --set revision=main`
  - **job `secrets-restore`**: runs on every PR; needs: minikube, kubectl, argocd CLI, `bao` CLI, `aws` CLI; secrets: `SCW_ACCESS_KEY_ID`, `SCW_SECRET_ACCESS_KEY`, `SCW_S3_BUCKET`; steps: (1) start minikube, (2) install ArgoCD, (3) apply seed Application pointing to this repo + branch, (4) create `scaleway-s3-credentials` Secret in `openbao` namespace, (5) wait for ArgoCD sync + init Job completion, (6) write canary secret `kv/apps/test/canary value=survive-<run-id>`, (7) `minikube delete`, (8) `minikube start`, (9) install ArgoCD, (10) re-apply seed Application, (11) create `scaleway-s3-credentials` Secret, (12) wait for sync + init Job, (13) assert canary value matches step 6, (14) assert `bao status` shows `Sealed: false`
- [ ] T022 [US2] Local validation — Scenario 2 from `specs/001-replace-infisical-oss-secrets/quickstart.md`: manually execute destroy/recreate cycle; confirm canary secret restored; document any deviations

**Checkpoint**: CI `secrets-restore` job passes. SC-001 verified. US2 complete.

---

## Phase 5: User Story 3 — Infisical Fully Removed (Priority: P3)

**Goal**: Confirm no Infisical artifacts exist in the gitops repo or the cluster; enforce this permanently in CI.

**Independent Test**: Scenario 4 from `specs/001-replace-infisical-oss-secrets/quickstart.md` — `git grep -ri infisical apps/ platform/ clusters/ bootstrap/` returns empty; `kubectl get pods -A | grep -i infisical` returns empty.

### CI Enforcement

- [x] T023 [US3] Add `infisical-absent` job to `.github/workflows/ci.yml`: (1) `git grep -ri infisical apps/ platform/ clusters/ bootstrap/` must exit non-zero (no matches); (2) on the `secrets-restore` job's cluster: `kubectl get pods -A -o name | grep -i infisical` must return empty; fail the job if either check finds a match
- [x] T024 [US3] Local validation — Scenario 4 from `specs/001-replace-infisical-oss-secrets/quickstart.md`: run the grep and kubectl checks locally; confirm all pass

**Checkpoint**: `infisical-absent` CI job passes. SC-003 and SC-004 verified. US3 complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: ESO end-to-end integration, cluster chart rendering, documentation.

- [x] T025 [P] Validate cluster chart rendering for local: `helm template boot bootstrap/ --set env=local --set revision=main` and `helm template loc clusters/local/ --set revision=main`; confirm `openbao-init.yaml` Application appears in output
- [x] T026 [P] Validate cluster chart rendering for scaleway: `helm template loc clusters/scaleway/ --set revision=main`; confirm `openbao-init.yaml` Application appears in output
- [ ] T027 Local ESO integration test — Scenario 3 from `specs/001-replace-infisical-oss-secrets/quickstart.md`: apply test `ExternalSecret` in `default` namespace; wait 15s; verify `kubectl get secret test-secret -n default` exists and value matches what was written to OpenBao
- [x] T028 Update `CLAUDE.md` validation commands section with the new `openbao-init` lint/template commands (mirror the existing `helm lint apps/demo/` pattern)

**Checkpoint**: All six CI jobs pass on a PR against main. All four quickstart scenarios pass locally.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 (chart scaffold must exist) — blocks US1
- **Phase 3 (US1 MVP)**: Depends on Phase 2 completion — T010–T019 can largely run in parallel within the phase
- **Phase 4 (US2)**: Depends on Phase 3 checkpoint (destroy/recreate requires a working US1 deployment)
- **Phase 5 (US3)**: Depends on Phase 2 (platform manifests must exist to confirm Infisical is absent); CI job can be written in parallel with Phase 4
- **Phase 6 (Polish)**: Depends on Phases 3–5 complete

### User Story Dependencies

| Story | Depends on | Can parallelise with |
|-------|-----------|---------------------|
| US1 (P1) | Phase 2 complete | — |
| US2 (P2) | US1 checkpoint (T020 passed) | — |
| US3 (P3) | Phase 2 complete (for CI enforcement) | US2 (CI file already exists after T021) |

### Within-Phase Parallel Opportunities

**Phase 2**: T006, T007, T008 can all run in parallel once T005 establishes the manifest pattern.

**Phase 3**: After T001–T004 (scaffold) and T010–T012 (RBAC):
- T013 (policies ConfigMap) and T015 (ClusterSecretStore) can run in parallel
- T016 and T017 (cluster templates) can run in parallel
- T018 sync-wave edits touch multiple files but are independent per-file

---

## Parallel Examples

### Parallel: Phase 2 Platform Manifests
```
T005 → T006 [P] (scaleway openbao.yml, same pattern)
     → T007 [P] (local external-secrets.yml, independent)
     → T008 [P] (scaleway external-secrets.yml, independent)
```

### Parallel: Phase 3 RBAC + ConfigMap
```
After T010 (ServiceAccount):
  T011 [P] role.yaml
  T012 [P] rolebinding.yaml
  T013   configmap-policies.yaml (independent)
  T015 [P] clustersecretstore.yaml (independent)
```

### Parallel: Phase 3 Cluster Templates
```
T016 [US1] clusters/local/templates/openbao-init.yaml
T017 [P][US1] clusters/scaleway/templates/openbao-init.yaml
(different files, no dependencies on each other)
```

---

## Implementation Strategy

### MVP (US1 only — Phases 1–3)

1. Phase 1: Scaffold chart (T001–T004)
2. Phase 2: Platform manifests (T005–T009)
3. Phase 3: Init job + RBAC + cluster templates + sync waves (T010–T019)
4. **STOP and VALIDATE**: Run Scenario 1 from quickstart.md (T020)
5. If smoke test passes → US1 is shipped; secrets backend is operational

### Incremental Delivery

1. MVP (Phases 1–3) → OpenBao operational ✅
2. Phase 4 (US2) → Destroy/recreate proven in CI ✅
3. Phase 5 (US3) → Infisical-absent gate in CI ✅
4. Phase 6 (Polish) → All validation scenarios pass ✅

---

## Notes

- All manifests must use `{{ .Values.repoURL }}` and `{{ .Values.revision }}` for in-house charts (see `clusters/local/templates/demo.yaml` as reference)
- Pin external Helm chart versions explicitly — never use floating refs
- The `scaleway-s3-credentials` Secret is created by infra Terraform, not by this repo — the init Job **reads** it but never creates it
- Init Job must be idempotent: multiple runs must not re-initialise an already-initialised OpenBao
- Root token must be revoked at the end of the init script; subsequent access uses Kubernetes auth
- See `contracts/argocd-applications.md` for exact manifest shapes and sync-wave table
- See `contracts/secrets-consumption.md` for KV path convention and policy naming
