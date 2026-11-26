"""The same exchange with a token GitHub really issued, in the job running this
test: real discovery, real keys, real claim formats. Only inside GitHub Actions,
with `permissions: id-token: write` (never on pull requests from forks)."""

import json
import os
import time
import urllib.parse
import urllib.request

import pytest

import lib

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), reason="no GitHub OIDC token outside Actions"
    ),
]


def github_token(audience):
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(audience, safe="")
    request = urllib.request.Request(
        url, headers={"Authorization": f"bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["value"]


@pytest.fixture
def trusting_github(cluster, toolbox):
    """headscale-sts configured as deployed, except that the trusted repository
    is the one running this job."""
    values = lib.values()["sts"]["github"]
    try:
        cluster.deploy_headscale(
            sts__github__issuer=values["issuer"],
            sts__github__repository=os.environ["GITHUB_REPOSITORY"],
            # --set would turn the ID into a number; the chart quotes it.
            sts__github__repositoryID=os.environ["GITHUB_REPOSITORY_ID"],
        )
        lib.wait_for(lambda: toolbox.curl("/sts/healthz")[0] == 200, "headscale-sts")
        time.sleep(5)
        yield
    finally:
        cluster.deploy_headscale()


def test_a_real_github_token_joins_the_network(cluster, device, toolbox, trusting_github):
    token = github_token(f"https://{lib.public_host()}/sts")
    status, key = toolbox.curl("/sts/authkey", "-X", "POST", "-H", f"Authorization: Bearer {token}")
    assert status == 200, key
    job = device("github")
    job.up(key, "--ssh")
    assert cluster.node(job.name)["tags"] == ["tag:ci-debug"]
