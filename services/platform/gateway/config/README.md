# gateway-config

## Manually triggering a backup for `cert-restore`

`templates/cert-restore-job.yaml` is a PreSync hook that restores the
`cert-manager`/`gateway` namespaces' Secrets (TLS cert, ACME account key) from
a Velero backup before this Application's ClusterIssuers/Gateway get created —
so a cluster rebuild finds a still-valid cert instead of triggering a fresh
ACME order (see `bootstrap/values.yaml`
for why that matters — Let's Encrypt's rate limit already bit us once, 2026-07-25).

The restore script only accepts a backup that is **labeled**
`velero.io/schedule-name=velero-cert-secrets` (see
`templates/cert-restore-configmap.yaml`) — this is what "a backup from the
schedule" means, on purpose: it guarantees the restored data actually came
from the `velero-cert-secrets` schedule (which backs up exactly
`cert-manager`+`gateway`), not some unrelated ad-hoc backup that happens to
share a naming convention.

If you need a backup available *right now* — for a rebuild, without waiting
for the schedule's next `0 * * * *` tick — trigger one explicitly **from the
schedule**:

```bash
kubectl --context <ctx> exec -n velero deploy/velero -c velero -- \
  /velero backup create --from-schedule velero-cert-secrets --wait
```

**A plain `velero backup create <name>` (without `--from-schedule`) will NOT
work** — it does not get the `velero.io/schedule-name` label, so
`cert-restore` will never consider it eligible and will keep waiting
(confirmed live, 2026-07-29: pre-existing manual backups `manual-test-*` and
`velero-bucket-test-*` only carried `velero.io/storage-location`, no
`velero.io/schedule-name` — invisible to the restore script).

Verify a backup will actually be picked up:

```bash
kubectl --context <ctx> get backup -n velero -l velero.io/schedule-name=velero-cert-secrets
```
