# authentik-restore

Restores authentik's Postgres volume from the latest Velero CSI snapshot on a fresh
cluster, **before** authentik's own StatefulSet creates an empty one. A thin wrapper
around `charts/velero-pvc-restore`, which holds the logic and its documentation
(what it checks, why it cannot deadlock, the restore drill): read that README.

## What is and is not backed up

| What | Where it lives | On a cluster `down` + `up` |
|---|---|---|
| Groups, applications, providers, OIDC clients, flows, passkey/login config, GitHub source | Terraform (`14-sso/managed`, applied by the `authentik-managed` Workspace) | recreated from code |
| `AUTHENTIK_SECRET_KEY`, DB password, bootstrap token | OpenBao `kv/apps/authentik/eso-generated` (OpenBao's own hourly raft snapshot) | restored with OpenBao |
| **Users, group membership, passkeys, GitHub links, sessions, anything changed by hand in the UI** | authentik's Postgres volume **only** | **this chart restores it** |

The volume is snapshotted every 4 hours and kept 60 days (`authentik-data` schedule
in `services/platform/velero/chart/values-scaleway.yaml`, in the Velero bucket). A
snapshot is crash-consistent: Postgres replays its write-ahead log when it opens the
restored volume, like after a power cut. Up to 4 hours of changes can be lost (a
passkey added in the last 4 hours before a `down`).

**Why 60 days, and why only native Velero settings.** The number of versions kept is
`TTL / period` (360 here, against 336 for 14 days hourly), and what matters is that
the *latest* snapshot survives a cluster that stays down for a long time: a backup
past its TTL is deleted as soon as a Velero comes up, possibly before the restore Job
reads it, and Velero has no "keep at least the last one". So the TTL itself is long,
and nothing manages the lifecycle by hand. Not more than 60 days: the Velero bucket
moves objects to GLACIER after 90 days (`03-storage/scaleway`, lifecycle rule
`velero-retention`), where a backup cannot be restored directly; a per-bucket
`cold_storage_enabled = false` there lifts that cap.

The restored database needs the **same** `SECRET_KEY` and DB password it was
created with: they come from OpenBao, whose snapshot is also hourly.

## How it runs

It is the first wave (`wave: "0"`) of the `sso-apps` domain
(`10-cluster/platform-apps/values-sso.yaml` in the infra repo), which `needs_backups`:
Velero and its bucket sync are up before it runs. It lives in `sso-apps`, **not** in
`backups-apps` next to `grafana-restore`/`cert-restore`: `backups-apps` is a gate
other domains wait on, and a problem restoring authentik must hold back only
authentik. `backups-apps` never depends on `sso-apps`, so the dependency is one-way.
