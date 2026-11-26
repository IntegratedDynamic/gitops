"""Who reaches what, measured with real clients: personal devices reach the CI
runners being debugged, nothing reaches back from a CI runner."""

import json

import pytest

import lib

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def runners(ci_runner):
    return ci_runner(), ci_runner()


def wait_for_peer(device, ip):
    lib.wait_for(lambda: ip in device.tailscale("status").stdout, f"{device.name} to see {ip}", timeout=60)


def check_policy(cluster, expectations):
    """`headscale policy check` on the deployed policy plus `expectations` as its
    `tests` / `sshTests`, against the live users and nodes. They are not kept in
    the policy file: with no runner connected, headscale would fail them."""
    policy = cluster.exec("headscale", "headscale-0", "/busybox/cat", "/etc/headscale/policy.hujson",
                          container="sts").stdout.rstrip()
    assert policy.endswith("}")
    blocks = "".join(f'  "{name}": {json.dumps(block)},\n' for name, block in expectations.items())
    cluster.exec("headscale", "headscale-0", "/busybox/sh", "-c", "cat > /run/sts/policy.hujson",
                 container="sts", input=policy[:-1] + blocks + "}\n")
    return cluster.exec("headscale", "headscale-0", "headscale", "policy", "check", "--file",
                        "/run/sts/policy.hujson", container="sts", check=False)


def test_policy_meets_its_expectations(cluster, member, runners):
    result = check_policy(cluster, json.loads((lib.TESTS / "policy-tests.json").read_text()))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("expectations", [
    {"tests": [{"src": "tag:ci-debug", "accept": ["alice@:22"]}]},
    {"sshTests": [{"src": "alice@", "dst": ["tag:ci-debug"], "accept": ["root"]}]},
], ids=["tests", "sshTests"])
def test_policy_expectations_are_really_evaluated(cluster, member, runners, expectations):
    result = check_policy(cluster, expectations)
    assert result.returncode != 0 and "test" in result.stderr.lower(), result.stdout + result.stderr


def test_member_opens_an_ssh_session_on_a_runner(member, runners):
    runner = runners[0]
    wait_for_peer(member, runner.ip())
    # By its MagicDNS short name, with the remote exit code coming back.
    result = member.ssh(f"runner@{runner.name}", "id -un; exit 7")
    assert result.stdout.strip() == "runner", result.stderr
    assert result.returncode == 7


def test_root_is_refused(member, runners):
    result = member.ssh(f"root@{runners[0].name}", "true")
    assert result.returncode != 0
    assert "does not permit" in result.stderr


def test_member_reaches_a_runner(member, runners):
    ip = runners[0].ip()
    wait_for_peer(member, ip)
    assert member.reaches(ip)


@pytest.mark.parametrize("source,destination", [("runner", "member"), ("runner", "runner")])
def test_a_runner_reaches_nobody(member, runners, source, destination):
    target = member if destination == "member" else runners[1]
    ip = target.ip()
    if destination == "member":
        # Something must be listening, or "unreachable" would prove nothing.
        member.sh("apk add -q --no-cache openssh-server && ssh-keygen -A >/dev/null && /usr/sbin/sshd")
        assert member.sh("sleep 1; nc -w 3 127.0.0.1 22 </dev/null", check=False).stdout.startswith("SSH-")
    assert not runners[0].reaches(ip)


def test_nobody_can_tag_their_own_device(cluster, device):
    pod = device("sneaky")
    key = cluster.preauth_key(user="mallory")
    result = pod.up(key, "--advertise-tags=tag:ci-debug", check=False)
    node = cluster.node(pod.name)
    assert result.returncode != 0 or not (node or {}).get("tags"), node
