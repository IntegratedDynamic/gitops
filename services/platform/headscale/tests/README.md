# headscale tests

```bash
mise run test-headscale                                    # everything but `live`
PYTEST_ADDOPTS='-m "not e2e and not live"' mise run test-headscale   # seconds, no cluster
PYTEST_ADDOPTS='-m e2e -k sts' mise run test-headscale     # one area on kind
```

CI: [`.github/workflows/headscale.yml`](../../../../.github/workflows/headscale.yml),
on every pull request and push to `main` that touches headscale, the backup
schedule, the restore chart or the Envoy Gateway version.

| File | Cluster | What it holds true |
| --- | --- | --- |
| `test_static.py` | no | charts lint and render, headscale accepts its configuration, public names agree, backups and restore select the data volume, only the public ports are routed |
| `test_sts_provenance.py` | no | the pinned headscale-sts binaries are what the pinned commit builds (needs `go`) |
| `test_gateway.py` | kind | reachable through Envoy Gateway, the upgrade policy is needed, administration is not exposed |
| `test_access_policy.py` | kind | with real clients: members reach CI runners (SSH, never as root), runners reach nobody, nobody tags themselves; [`policy-tests.json`](policy-tests.json) through `headscale policy check` |
| `test_sts.py` | kind | job token to single-use, ephemeral, tagged node; every way it must be refused |
| `test_github_token.py` | kind, Actions only | the same with a token GitHub really issued |
| `test_oidc_login.py` | kind | a person's login: public client, PKCE, unverified e-mail |
| `test_resilience.py` | kind | long-lived connections, restarts, wrong checksum, identity provider down |
| `test_live.py` | deployed | smoke checks after a deployment (`HEADSCALE_LIVE_URL`, optional `HEADSCALE_LIVE_CONTEXT`) |

The CI side (`.github/actions/debug-tailscale`) and the names the two repos must
agree on (authentik client, application paths) are tested in the infrastructure
repo (`tests/`).

## What the kind cluster replaces

Same charts and Envoy Gateway version as the platform. Stand-ins: a test CA
instead of Let's Encrypt, `headscale mockoidc` instead of authentik, a local
signer instead of GitHub's token issuer. **Not covered**: authentik itself, the
Velero backup and restore, public DNS and certificates (`test_live.py` looks at
the last ones on a deployed cluster).

`HEADSCALE_TEST_KEEP=1` leaves the cluster up for inspection;
`HEADSCALE_TEST_SOAK=<seconds>` watches the control connections longer.
