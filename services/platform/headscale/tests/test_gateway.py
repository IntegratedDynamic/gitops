"""The public entry point: Envoy Gateway in front of headscale."""

import pytest

import lib

pytestmark = pytest.mark.e2e

UPGRADE = ("-X", "POST", "--http1.1", "-H", "Connection: Upgrade", "-H", "Upgrade: tailscale-control-protocol")


def test_headscale_answers(toolbox):
    status, body = toolbox.curl("/health")
    assert status == 200 and "pass" in body


def test_sts_answers_under_its_prefix(toolbox):
    assert toolbox.curl("/sts/healthz") == (200, "ok\n")


@pytest.mark.parametrize("path,expected", [
    ("/api/v1/node", 401),  # the API is reachable, and needs a key
    ("/metrics", 404),
    ("/debug/", 404),
])
def test_administration_is_not_exposed(toolbox, path, expected):
    assert toolbox.curl(path)[0] == expected


def test_control_protocol_upgrade_needs_the_backend_traffic_policy(cluster, toolbox):
    """Without it Envoy answers 403 and no client can connect."""

    def upgrade_status():
        return toolbox.curl("/ts2021", *UPGRADE)[0]

    assert upgrade_status() != 403
    manifest = lib.helm_template(lib.GATEWAY_CHART, "headscale-gateway")
    cluster.kubectl("-n", "headscale", "delete", "backendtrafficpolicy", "headscale")
    try:
        lib.wait_for(lambda: upgrade_status() == 403, "Envoy to refuse the upgrade")
    finally:
        cluster.apply(manifest)
    lib.wait_for(lambda: upgrade_status() != 403, "the upgrade to be allowed again")


def test_data_volume_has_the_name_and_label_backups_select(cluster):
    restore = lib.load_yaml(lib.HEADSCALE / "restore/values.yaml")["restore"]
    selector = f"{restore['selectorLabel']['key']}={restore['selectorLabel']['value']}"
    claims = cluster.get("-n", "headscale", "pvc", "-l", selector)["items"]
    assert [c["metadata"]["name"] for c in claims] == restore["pvcs"]
