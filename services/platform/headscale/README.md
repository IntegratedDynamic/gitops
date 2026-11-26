# headscale

Self-hosted control server for the platform's Tailscale network. The clients stay
the official `tailscale` ones; only the server they register with changes.

Not managed by Terraform: configuration and access policy are in this repo. The
one exception is the authentik OIDC client, declared with every other one in the
infrastructure repo (`14-sso/managed`).

| Chart | What | Deployed by (infrastructure repo) |
| --- | --- | --- |
| `restore/` | brings the data volume back from Velero on a fresh cluster | `headscale-apps`, wave 0 |
| `chart/` | StatefulSet, config, policy, Service, ServiceMonitor | `headscale-apps`, wave 1 |
| `gateway/` | `headscale.<domain>` route + the upgrade policy | `networking-resources-apps`, wave 1 |

- URL: `https://headscale.staging.scalepack.fr`
- Node names (MagicDNS): `<node>.ts.staging.scalepack.fr`
- Relays (DERP): Tailscale's public ones
- Policy: [`chart/files/policy.hujson`](chart/files/policy.hujson)

## Join a device

```bash
tailscale login --login-server https://headscale.staging.scalepack.fr
```

A browser opens on authentik; only members of the groups bound to the `headscale`
application get in. The Tailscale client keeps one profile per server, so the
previous tailnet stays one command away:

```bash
tailscale switch --list
tailscale switch <profile>
```

## Administer

The remote gRPC API is not exposed; the CLI runs in the pod.

```bash
hs() { kubectl --context <ctx> -n headscale exec statefulset/headscale -- headscale "$@"; }

hs nodes list
hs users list
# A tagged, single-use, short-lived key to register a non-interactive node:
hs preauthkeys create --tags tag:ci-debug --ephemeral --expiration 15m
```

A policy change is checked by the tests (below): state what it must allow and
refuse in [`tests/policy-tests.json`](tests/policy-tests.json).

## CI nodes

A GitHub Actions job gets its own preauth key, with no secret stored anywhere:
[headscale-sts](https://github.com/fredrikekre/headscale-sts), second container of
the pod, checks the job's GitHub OIDC token and mints a single-use, ephemeral,
`tag:ci-debug` key valid 5 minutes. Which jobs qualify: `sts.github` in
[`chart/values.yaml`](chart/values.yaml). In the infrastructure repo,
`.github/actions/debug-tailscale` is the consumer.

```bash
# inside a job with `permissions: id-token: write`
server=https://headscale.staging.scalepack.fr
token=$(curl -fsS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=$server/sts" | jq -r .value)
key=$(curl -fsS -X POST -H "Authorization: Bearer $token" "$server/sts/authkey")
tailscale up --login-server="$server" --authkey="$key"
```

It is a stopgap until headscale supports workload identity federation
([juanfont/headscale#3303](https://github.com/juanfont/headscale/issues/3303)).

**Trust.** A small third-party project (one author) that holds a headscale admin
API key, which it creates at each start and keeps in memory. The binary is
downloaded at start and runs only if its sha256 matches; a failed download
retries and does not affect headscale itself.

**Upgrading it.** Read the diff between the two tags, then update `sts.version`,
`commit`, `goVersion` (`go version -m <release binary>`) and `sha256` (the
release's `SHA256SUMS`). `tests/test_sts_provenance.py` fails unless those
binaries are what that source builds.

## Tests

`mise run test-headscale`, also run by CI: see [`tests/README.md`](tests/README.md).

## Availability and data

- **Down with the cluster.** While the cluster is down nobody can register, log in
  again or receive network changes. Tunnels already established between devices
  keep working until a client restarts.
- **Backups**: Velero snapshots the volume every 4 hours, kept 60 days (schedule
  `headscale-data`). A node registered after the last snapshot is unknown after a
  rebuild: log it in again.
- **A restart needs authentik**: with OIDC configured, headscale fails until the
  issuer answers. On a cold start the pod restarts until authentik and the
  `authentik-managed` Workspace are done.

Take a backup now (before an upgrade):

```bash
kubectl --context <ctx> exec -n velero deploy/velero -c velero -- \
  /velero backup create --from-schedule velero-headscale-data --wait
```

Restore drill: see [`charts/velero-pvc-restore`](../../../charts/velero-pvc-restore/README.md).

## Upgrading

One minor version at a time (headscale enforces it and cannot downgrade). Read the
upstream changelog, take a backup, bump `chart/values.yaml`'s `image.tag`.
