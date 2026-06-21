# Quickstart: Validate OSS Secrets Backend

**Feature**: 001-replace-infisical-oss-secrets
**Date**: 2026-06-21

Step-by-step guide to validate the secrets backend end-to-end, including the cluster destroy/recreate scenario required by SC-001.

---

## Prerequisites

1. Minikube running: `minikube status`
2. ArgoCD running: `kubectl --context minikube get pods -n argocd`
3. Scaleway S3 bucket (from Task 1) accessible with valid credentials
4. The `scaleway-s3-credentials` Kubernetes Secret exists in the `openbao` namespace (created by infra Terraform or manually for local testing):

```bash
kubectl --context minikube create namespace openbao --dry-run=client -o yaml | kubectl apply -f -
kubectl --context minikube create secret generic scaleway-s3-credentials \
  --namespace openbao \
  --from-literal=access_key=<SCW_ACCESS_KEY_ID> \
  --from-literal=secret_key=<SCW_SECRET_ACCESS_KEY>
```

---

## Scenario 1: Initial Deployment (User Story 1 — P1)

**Goal**: Verify secrets backend is deployed, initialised, and accessible.

```bash
# 1. Sync the platform Application (triggers openbao deployment)
kubectl --context minikube get applications -n argocd

# 2. Wait for openbao pod to be running
kubectl --context minikube get pods -n openbao -w

# 3. Verify init Job completed successfully
kubectl --context minikube get jobs -n openbao
kubectl --context minikube logs job/openbao-init -n openbao

# 4. Check OpenBao seal status (should report: Sealed false)
kubectl --context minikube exec -n openbao deploy/openbao -- \
  bao status

# 5. Write a test secret (requires a valid token from the init Job logs or S3)
export VAULT_ADDR="http://$(kubectl --context minikube get svc openbao -n openbao -o jsonpath='{.spec.clusterIP}'):8200"
bao kv put kv/apps/test/smoke-test value="hello"

# 6. Read it back
bao kv get kv/apps/test/smoke-test
```

**Expected**: `value = hello` printed. No errors. `bao status` shows `Sealed: false`.

---

## Scenario 2: Destroy and Recreate (User Story 2 — P1 for SC-001)

**Goal**: Verify secrets survive full cluster lifecycle.

```bash
# Step 1: Write a canary secret before destroy
bao kv put kv/apps/test/canary value="survive-destroy-$(date +%s)"
export CANARY=$(bao kv get -field=value kv/apps/test/canary)
echo "Canary: $CANARY"

# Step 2: Destroy the cluster
minikube delete

# Step 3: Recreate cluster and bootstrap ArgoCD
# (follow infra repo bootstrap procedure — applies Terraform or minikube + ArgoCD seed)
minikube start
# ... re-apply ArgoCD seed Application pointing to this gitops repo ...

# Step 4: Ensure S3 credentials Secret exists in the new cluster (infra bootstrap should create it)
kubectl --context minikube get secret scaleway-s3-credentials -n openbao

# Step 5: Wait for ArgoCD to reconcile and init Job to complete
kubectl --context minikube get jobs -n openbao -w
kubectl --context minikube logs job/openbao-init -n openbao

# Step 6: Verify OpenBao is unsealed
kubectl --context minikube exec -n openbao deploy/openbao -- bao status

# Step 7: Read back canary secret — must match pre-destroy value
bao kv get -field=value kv/apps/test/canary
# Expected output: same value as $CANARY above
```

**Expected**: Canary secret value matches. `bao status` shows `Sealed: false`. No manual intervention required between step 2 and step 7.

---

## Scenario 3: ESO Secret Sync (Integration Validation)

**Goal**: Verify External Secrets Operator syncs a secret into a workload namespace.

```bash
# 1. Apply a test ExternalSecret (see contracts/secrets-consumption.md for format)
kubectl --context minikube apply -f - <<EOF
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: test-secret
  namespace: default
spec:
  refreshInterval: "10s"
  secretStoreRef:
    name: openbao
    kind: ClusterSecretStore
  target:
    name: test-secret
    creationPolicy: Owner
  data:
    - secretKey: value
      remoteRef:
        key: apps/test/canary
        property: value
EOF

# 2. Wait for sync (refreshInterval: 10s)
sleep 15

# 3. Verify the v1/Secret was created
kubectl --context minikube get secret test-secret -n default -o jsonpath='{.data.value}' | base64 -d
# Expected: same value as the canary secret written in Scenario 1/2
```

---

## Scenario 4: Infisical Removal Validation (User Story 3 — P3)

```bash
# Verify no Infisical pods, CRDs, or Helm releases exist
kubectl --context minikube get pods -A | grep -i infisical
# Expected: no output

helm --kube-context minikube list -A | grep -i infisical
# Expected: no output

kubectl --context minikube get crd | grep -i infisical
# Expected: no output

# Verify no Infisical references in active GitOps manifests
git grep -ri infisical apps/ platform/ clusters/ bootstrap/
# Expected: no output
```

---

## CI Pipeline Validation (SC-001, SC-003, SC-004, SC-005)

The CI pipeline must automate Scenarios 1, 2, and 4. Minimum CI steps:

1. Start minikube (ephemeral CI runner)
2. Apply `scaleway-s3-credentials` Secret (from CI secrets)
3. Trigger ArgoCD sync
4. Assert: init Job completed, OpenBao unsealed, canary secret written
5. Destroy and recreate minikube
6. Re-apply `scaleway-s3-credentials` Secret
7. Re-trigger ArgoCD sync
8. Assert: OpenBao unsealed, canary secret matches pre-destroy value
9. Assert: no Infisical resources exist

Timing constraint (SC-002): step 8 secret retrieval must complete within 5 seconds of OpenBao reaching the unsealed state.

---

## References

- [ArgoCD Application manifests](contracts/argocd-applications.md)
- [Secrets consumption interface](contracts/secrets-consumption.md)
- [Data model and state transitions](data-model.md)
- [Tool selection research](research.md)
