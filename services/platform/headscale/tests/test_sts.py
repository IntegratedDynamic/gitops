"""headscale-sts: a CI job trades its OIDC token for a preauth key. Tokens come
from a stand-in issuer here, so that refusals can be provoked;
test_github_token.py covers GitHub's real ones."""

import time

import pytest

import lib

pytestmark = pytest.mark.e2e


def ask(toolbox, token=None):
    headers = ["-H", f"Authorization: Bearer {token}"] if token else []
    return toolbox.curl("/sts/authkey", "-X", "POST", *headers)


def test_a_job_token_gives_a_single_use_ephemeral_tagged_node(cluster, device, toolbox, issuer):
    status, key = ask(toolbox, issuer.token())
    assert status == 200, key

    job = device("job")
    job.up(key, "--ssh")
    node = cluster.node(job.name)
    assert node["tags"] == ["tag:ci-debug"]
    assert node["pre_auth_key"]["ephemeral"] is True
    assert not node["pre_auth_key"].get("reusable")

    second = device("second")
    reuse = second.up(key, check=False)
    assert reuse.returncode != 0 and "already used" in reuse.stdout + reuse.stderr

    # What the CI action's post step does: the node then disappears.
    job.tailscale("logout")
    lib.wait_for(lambda: cluster.node(job.name) is None, "the ephemeral node to be removed", timeout=60)


def test_a_token_works_once(toolbox, issuer):
    token = issuer.token()
    assert ask(toolbox, token)[0] == 200
    assert ask(toolbox, token) == (401, "token rejected\n")


@pytest.mark.parametrize("claims,status", [
    pytest.param({"repository": "someone/infrastructure", "repository_id": "1"}, 403, id="other-repository"),
    pytest.param({"repository_id": "999"}, 403, id="same-name-other-repository-id"),
    pytest.param({"aud": "https://github.com/IntegratedDynamic"}, 401, id="other-audience"),
    pytest.param({"iss": "https://elsewhere.example.org"}, 401, id="other-issuer"),
    pytest.param({"exp": -60}, 401, id="expired"),
])
def test_refused_tokens(toolbox, issuer, claims, status):
    if claims.get("exp", 0) < 0:
        claims = {**claims, "exp": int(time.time()) + claims["exp"]}
    assert ask(toolbox, issuer.token(**claims))[0] == status


def test_a_forged_signature_is_refused(toolbox, issuer):
    forged = issuer.token(key=lib.Issuer().key)
    assert ask(toolbox, forged)[0] == 401


@pytest.mark.parametrize("token", [None, "not-a-token"])
def test_no_valid_token_no_key(toolbox, token):
    assert ask(toolbox, token)[0] == 401


def test_api_key_is_private(cluster):
    mode = cluster.exec("headscale", "headscale-0", "/busybox/stat", "-c", "%a", "/run/sts/apikey",
                        container="sts").stdout.strip()
    assert mode == "600"
    assert "hskey-api-" not in cluster.logs("sts")
