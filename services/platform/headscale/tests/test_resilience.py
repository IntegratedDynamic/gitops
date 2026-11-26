"""Restarts, outages and bad inputs."""

import os
import time

import pytest

import lib

pytestmark = pytest.mark.e2e

# How long a control connection is watched. Longer than the gateway's default
# request timeout; raise it to hunt for slower ones.
SOAK = int(os.environ.get("HEADSCALE_TEST_SOAK", "75"))


def mint(toolbox, issuer):
    # headscale-sts refuses tokens issued before it started.
    time.sleep(2)
    return toolbox.curl("/sts/authkey", "-X", "POST", "-H", f"Authorization: Bearer {issuer.token()}")


def sts_up(toolbox):
    return lib.wait_for(lambda: toolbox.curl("/sts/healthz")[0] == 200, "headscale-sts")


def test_control_connections_stay_open(cluster, member):
    """A client holds one request open to receive network updates; headscale logs
    it when it ends. None may end while nothing happens."""

    def ended():
        return cluster.logs("headscale").count('"path":"/ts2021"')

    time.sleep(5)
    before = ended()
    time.sleep(SOAK)
    assert ended() == before
    assert cluster.node(member.name)["online"] is True


def test_nodes_and_sessions_survive_a_restart(cluster, member, ci_runner, toolbox, issuer):
    runner = ci_runner()
    before = {n["given_name"] for n in cluster.headscale_json("nodes", "list")}
    cluster.restart_headscale()
    assert before <= {n["given_name"] for n in cluster.headscale_json("nodes", "list")}
    lib.wait_for(lambda: member.ssh(f"runner@{runner.name}", "true").returncode == 0, "SSH after the restart")
    sts_up(toolbox)
    status, body = mint(toolbox, issuer)
    assert status == 200, body


def test_sts_recovers_from_its_own_restart(cluster, toolbox, issuer):
    def restarts():
        statuses = cluster.get("-n", "headscale", "pod", "headscale-0")["status"]["containerStatuses"]
        return {c["name"]: c["restartCount"] for c in statuses}

    before = restarts()
    cluster.exec("headscale", "headscale-0", "/busybox/kill", "1", container="sts")
    lib.wait_for(lambda: restarts()["sts"] > before["sts"], "the container to restart")
    sts_up(toolbox)
    status, body = mint(toolbox, issuer)
    assert status == 200, body
    assert restarts()["headscale"] == before["headscale"]


def test_a_binary_with_the_wrong_checksum_never_runs(cluster, toolbox):
    wrong = "0" * 64
    try:
        cluster.deploy_headscale(sts__sha256__amd64=wrong, sts__sha256__arm64=wrong)
        lib.wait_for(lambda: "checksum verification failed" in cluster.logs("sts"), "the refusal")
        processes = cluster.exec("headscale", "headscale-0", "/busybox/ps", "-o", "args", container="sts").stdout
        assert "headscale-sts -config" not in processes
        assert toolbox.curl("/sts/healthz")[0] == 503
        # ... and headscale itself is unaffected.
        assert toolbox.curl("/health")[0] == 200
    finally:
        cluster.deploy_headscale()
    sts_up(toolbox)


def test_headscale_does_not_start_without_its_identity_provider(cluster):
    """Deliberate: it restarts until authentik answers instead of running without
    SSO logins until the next restart."""
    try:
        issuer = cluster.chart_sets["oidc.issuer"]
        cluster.deploy_headscale(wait=False, oidc__issuer=f"{issuer}-missing")

        def failing():
            logs = cluster.kubectl("-n", "headscale", "logs", "headscale-0", "-c", "headscale", check=False)
            return "oidc" in logs.stdout.lower() and "404" in logs.stdout

        lib.wait_for(failing, "headscale to give up on the provider", timeout=180)
        pod = cluster.get("-n", "headscale", "pod", "headscale-0")
        ready = {c["name"]: c["ready"] for c in pod["status"]["containerStatuses"]}
        assert ready["headscale"] is False
    finally:
        cluster.deploy_headscale(wait=False)
        # A StatefulSet does not replace a pod that never became ready by itself.
        cluster.kubectl("-n", "headscale", "delete", "pod", "headscale-0", "--wait=true")
        cluster.wait_headscale()
