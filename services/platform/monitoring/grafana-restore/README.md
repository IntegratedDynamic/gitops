# grafana-restore

See `services/platform/gateway/cert-restore/README.md` for the full
"chicken-and-egg" background on the `enabled` toggle and why this is a
plain Job gated by a Terraform-level wait (`module.wait_restore_healthy`)
rather than an ArgoCD PreSync hook — this chart mirrors it exactly, just for
Grafana's own PVC instead of the wildcard TLS cert.

## Manually triggering a backup for grafana-restore

`templates/job.yaml` restores Grafana's PVC (CSI VolumeSnapshot-backed)
from a Velero backup before `grafana`'s own Deployment/PVC get created. The
restore script only accepts a backup labeled
`velero.io/schedule-name=velero-grafana-data` (see `templates/configmap.yaml`).

To trigger one available right now, without waiting for the schedule's next
tick:

```bash
kubectl --context <ctx> exec -n velero deploy/velero -c velero -- \
  /velero backup create --from-schedule velero-grafana-data --wait
```

Verify a backup will actually be picked up:

```bash
kubectl --context <ctx> get backup -n velero -l velero.io/schedule-name=velero-grafana-data
```
