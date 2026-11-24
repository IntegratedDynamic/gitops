# velero-pvc-restore

Brings PersistentVolumeClaims back from the latest Velero CSI snapshot on a fresh
cluster, **before** the workload that owns them creates empty ones. Generic: used by
authentik (`services/platform/authentik/restore`, a thin wrapper) and Firefly III
(`nbrieussel/homelab-apps`, `bootstrap`).

It restores data nothing else can recreate (accounts, passkeys, finances), so it
fails closed instead of letting the workload start on an empty volume by mistake. It
is generated from the same idea as `services/platform/monitoring/grafana-restore`;
`templates/configmap.yaml` documents each difference.

## What it does

1. **Never touches a PVC that exists.** Only the missing ones are restored; a running
   cluster is a no-op. (Velero itself also skips PVCs that exist.)
2. **Waits for Velero's first sync of the bucket to finish** (BackupStorageLocation
   `Available` + `lastSyncedTime`), instead of a fixed budget, so "no backup" is told
   from "not synced yet". If Velero never gets there it fails, it does not guess.
3. **Restores an explicit backup**: the newest `Completed` backup of the schedule
   that holds a snapshot for **every** PVC in `pvcs`. Not `scheduleName` ("latest
   successful"): on a fresh cluster the schedule's first backup can be of an empty
   namespace and would be the latest.
4. **Checks each restored PVC points at a `VolumeSnapshot`**, and fails otherwise
   (Velero can report `Completed` with a dangling PVC).
5. No backup that qualifies at all (a genuine first start) -> exits 0, the workload
   starts empty.

`enabled: false` skips the restore for a deliberate fresh start.

## Where to run it, so it cannot deadlock

As an **early sync wave of the workload's own app-of-apps**, with Velero already up
(the workload's domain `needs_backups`, or it is deployed after the whole platform).
It needs Velero and nothing else: not the workload, not SSO. It must NOT sit in a
gate domain other domains wait on (`backups-apps` is one): a problem restoring one
workload's data must hold back only that workload.

## Values

See `values.yaml`. `scheduleName` and `pvcs` are required.

## Take a backup right now

```bash
kubectl --context <ctx> exec -n velero deploy/velero -c velero -- \
  /velero backup create --from-schedule <schedule-name> --wait
```

## Restore drill (does not touch the live data)

Restores the latest snapshot into a throwaway namespace and lets you read it:

```bash
kubectl --context <ctx> create namespace drill
helm template restore-drill charts/velero-pvc-restore --namespace drill \
  --set scheduleName=<schedule-name> --set 'pvcs={<pvc1>,<pvc2>}' \
  --set sourceNamespace=<the namespace the backup was taken in> \
  | kubectl --context <ctx> apply -f -
kubectl --context <ctx> -n drill wait --for=condition=complete job \
  -l app.kubernetes.io/name=restore-drill --timeout=300s
```

then run the real workload's image on the restored PVC(s) and read them. **Before
deleting the drill namespace**, check the restored `VolumeSnapshotContent`s are
`Retain` (`kubectl get volumesnapshotcontent`): deleting one with a `Delete` policy
would delete the real snapshot the backup points at. Afterwards delete the
namespace, the cluster-scoped `VolumeSnapshotContent`, and the `Restore`, `Role` and
`RoleBinding` named `restore-drill` in the `velero` namespace.
