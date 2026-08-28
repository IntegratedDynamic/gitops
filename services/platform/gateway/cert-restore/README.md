# cert-restore

## The "first init" chicken-and-egg — restore hooks need a backup to already exist

This chart and `services/platform/monitoring/grafana-restore` (and,
separately, `services/platform/openbao/init` — a different mechanism, not
Velero-backed) share the same shape: wait for a Velero `Backup` labeled with
the schedule they care about, then restore it, before the consumer domain
that actually needs the restored data (`gateway-config`, `grafana`) gets its
own Application created — enforced via a real Terraform-level wait
(`module.wait_restore_healthy` in the infra repo's `10-cluster/scaleway/argocd.tf`),
not an ArgoCD PreSync hook (see `templates/job.yaml` for why that changed
2026-08-27). The restore script's own budget (`templates/configmap.yaml`,
~25 minutes) is designed to fail *open*, not closed — if no backup ever
shows up, it gives up and lets this domain report Healthy with fresh/empty
state rather than blocking forever. That's correct once the schedule has
actual history behind it.

It is **not** correct on the very first deploy of a brand-new schedule: a
`Schedule` object only creates its first `Backup` on its next cron tick (up
to an hour away for an hourly schedule), so a fresh chart/schedule has
*zero* backup history for the entire time this hook is willing to wait —
every sync pays the full budget for nothing, every time, until the first
backup actually lands. This isn't a failure exactly (the hook does
eventually give up and proceed), but it turns every rebuild into a
25-minute wait for no reason.

The fix (2026-08-14, mirrors `services/platform/openbao/init`'s own
`restore.enabled` gate): this chart's values expose an `enabled` boolean
gating **all four** of its templates (`serviceaccount`, `configmap`, `job`,
`rbac`) as a chart-wide no-op when `false`. Rule of thumb for setting it:

- **`false`** — a schedule/chart with no backup history yet (its very
  first deploy, or right after being added). Skip the hook entirely; there
  is nothing to restore anyway, and skipping avoids the wasted wait.
- **`true`** — a schedule that's been running long enough to have real
  backups. `enabled` here defaults `true` for exactly this reason
  (confirmed live across multiple real cluster rebuilds); a fresh
  `grafana-restore`-style hook should start `false` and flip to `true`
  once `kubectl get backup -n velero -l velero.io/schedule-name=<name>`
  shows at least one.

There is no automatic way to tell "no backup yet" apart from "backup
exists but Velero hasn't synced it into this cluster yet" from inside the
restore script alone — that's the real chicken-and-egg, and the `enabled`
toggle is the deliberately simple manual answer to it (a proper fix would
need the hook to distinguish those two cases itself; not built yet).

## Manually triggering a backup for cert-restore

`templates/job.yaml` restores the `cert-manager`/`gateway` namespaces'
Secrets (TLS cert, ACME account key) from a Velero backup before
`gateway-config`'s ClusterIssuers/Gateway get created — so a cluster
rebuild finds a still-valid cert instead of triggering a fresh ACME order
(see `services/platform/gateway/config`'s own `values-scaleway.yaml`
`activeClusterIssuer` comment for why that matters — Let's Encrypt's rate
limit already bit us once, 2026-07-25).

The restore script only accepts a backup that is **labeled**
`velero.io/schedule-name=velero-cert-secrets` (see `templates/configmap.yaml`)
— this is what "a backup from the schedule" means, on purpose: it
guarantees the restored data actually came from the `velero-cert-secrets`
schedule (which backs up exactly `cert-manager`+`gateway`), not some
unrelated ad-hoc backup that happens to share a naming convention.

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
