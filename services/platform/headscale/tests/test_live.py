"""Smoke checks of a deployed headscale, to run after a deployment:

    HEADSCALE_LIVE_URL=https://headscale.staging.scalepack.fr pytest -m live

With HEADSCALE_LIVE_CONTEXT=<kube context> it also looks at the cluster (read
only)."""

import json
import os
import re
import urllib.error
import urllib.request

import pytest

import lib

URL = os.environ.get("HEADSCALE_LIVE_URL", "").rstrip("/")
CONTEXT = os.environ.get("HEADSCALE_LIVE_CONTEXT")

pytestmark = [pytest.mark.live, pytest.mark.skipif(not URL, reason="HEADSCALE_LIVE_URL is not set")]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(path, method="GET", follow=True):
    """(status, headers, body). The certificate must be publicly trusted."""
    opener = urllib.request.build_opener(*([] if follow else [_NoRedirect]))
    request = urllib.request.Request(URL + path, method=method, headers={"User-Agent": "headscale-smoke-test"})
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, response.headers, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode()


def test_server_is_healthy_behind_a_trusted_certificate():
    status, _, body = fetch("/health")
    assert status == 200 and "pass" in body


def test_clients_can_discover_the_server_key():
    status, _, body = fetch("/key?v=109")
    assert status == 200 and json.loads(body)["publicKey"].startswith("mkey:")


def test_sts_is_up_and_needs_a_token():
    assert fetch("/sts/healthz")[0] == 200
    assert fetch("/sts/authkey", method="POST")[0] == 401


@pytest.mark.parametrize("path,expected", [("/api/v1/node", 401), ("/metrics", 404), ("/debug/", 404)])
def test_administration_is_not_exposed(path, expected):
    assert fetch(path)[0] == expected


def test_login_goes_to_the_identity_provider():
    status, headers, _ = fetch("/register/hskey-authreq-smoketest0000000000000000", follow=False)
    # An unknown registration ID is refused outright by some versions; a known
    # one redirects. Either way the provider's discovery must be reachable.
    issuer = f"https://sso.{URL.split('.', 1)[1]}/application/o/headscale/"
    with urllib.request.urlopen(issuer + ".well-known/openid-configuration", timeout=20) as response:
        discovery = json.load(response)
    assert discovery["issuer"] == issuer
    assert "S256" in discovery["code_challenge_methods_supported"]
    if status in (302, 303, 307):
        assert headers["Location"].startswith(discovery["authorization_endpoint"])


def kubectl(*args):
    return json.loads(lib.run("kubectl", "--context", CONTEXT, *args, "-o", "json").stdout)


@pytest.mark.skipif(not CONTEXT, reason="HEADSCALE_LIVE_CONTEXT is not set")
def test_pod_is_ready():
    statuses = kubectl("-n", "headscale", "get", "pod", "headscale-0")["status"]["containerStatuses"]
    assert {c["name"]: c["ready"] for c in statuses} == {"headscale": True, "sts": True}


@pytest.mark.skipif(not CONTEXT, reason="HEADSCALE_LIVE_CONTEXT is not set")
def test_a_usable_backup_of_the_data_volume_exists():
    backups = kubectl("-n", "velero", "get", "backups.velero.io",
                      "-l", "velero.io/schedule-name=velero-headscale-data")["items"]
    done = [b for b in backups if b.get("status", {}).get("phase") == "Completed"]
    assert done, f"no completed backup among {len(backups)}"
    latest = max(done, key=lambda b: b["status"]["startTimestamp"])
    assert latest["status"].get("csiVolumeSnapshotsCompleted", 0) >= 1, latest["status"]
