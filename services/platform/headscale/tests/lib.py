"""Helpers shared by the tests: repo files, helm rendering, the kind cluster,
tailnet devices and the stand-in token issuer."""

import json
import os
import pathlib
import shlex
import string
import subprocess
import time
import uuid

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
HEADSCALE = TESTS.parent
REPO = HEADSCALE.parents[2]
CHART = HEADSCALE / "chart"
GATEWAY_CHART = HEADSCALE / "gateway"
POLICY = CHART / "files" / "policy.hujson"

# Same version as tailscale/github-action's default, which CI runners join with.
TAILSCALE_VERSION = os.environ.get("TAILSCALE_VERSION", "1.94.2")


def load_yaml(path):
    return yaml.safe_load(pathlib.Path(path).read_text())


def values():
    return load_yaml(CHART / "values.yaml")


def public_host(suffix=""):
    v = values()
    return f"{v['hostPrefix']}{suffix}.{v['domain']}"


def headscale_image():
    image = values()["image"]
    return f"{image['repository']}:{image['tag']}-debug"


def envoy_gateway_version():
    """The version the platform runs: an upgrade there is tested here."""
    chart = load_yaml(REPO / "services/platform/gateway/chart/Chart.yaml")
    return next(d["version"] for d in chart["dependencies"] if d["name"] == "gateway-helm")


def run(*cmd, input=None, check=True, timeout=600):
    result = subprocess.run(
        [str(c) for c in cmd], input=input, capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"{shlex.join(map(str, cmd))}\nexit {result.returncode}\n{result.stdout}\n{result.stderr}"
        )
    return result


def helm_template(chart, release="headscale", sets=None):
    cmd = ["helm", "template", release, chart, "--namespace", "headscale"]
    for key, value in (sets or {}).items():
        cmd += ["--set", f"{key}={value}"]
    return run(*cmd).stdout


def render(chart, release="headscale", sets=None):
    """{(kind, name): object} of a rendered chart."""
    docs = yaml.safe_load_all(helm_template(chart, release, sets))
    return {(d["kind"], d["metadata"]["name"]): d for d in docs if d}


def wait_for(condition, what, timeout=120, interval=2):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = condition()
            if last:
                return last
        except AssertionError as error:
            last = error
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}; last: {last}")


class Cluster:
    """Every call names the kubeconfig and the context: the tests never touch
    the caller's own kubectl configuration."""

    def __init__(self, name, kubeconfig):
        self.name = name
        self.kubeconfig = str(kubeconfig)
        self.context = f"kind-{name}"
        self.gateway_ip = None
        self.chart_sets = {}

    def kubectl(self, *args, **kwargs):
        return run(
            "kubectl", "--kubeconfig", self.kubeconfig, "--context", self.context, *args, **kwargs
        )

    def apply(self, manifest, **substitutions):
        if substitutions:
            manifest = string.Template(manifest).substitute(substitutions)
        self.kubectl("apply", "-f", "-", input=manifest)

    def get(self, *args):
        return json.loads(self.kubectl("get", *args, "-o", "json").stdout)

    def exec(self, namespace, pod, *command, container=None, **kwargs):
        args = ["-n", namespace, "exec", pod]
        if container:
            args += ["-c", container]
        if kwargs.get("input") is not None:
            args.insert(3, "-i")
        return self.kubectl(*args, "--", *command, **kwargs)

    # -- headscale ---------------------------------------------------------

    def deploy_headscale(self, wait=True, **overrides):
        """(Re)deploys the chart with the test settings plus `overrides`
        (helm --set keys, dots written as `__`)."""
        sets = dict(self.chart_sets)
        sets.update({k.replace("__", "."): v for k, v in overrides.items()})
        self.apply(helm_template(CHART, sets=sets))
        if wait:
            self.wait_headscale()

    def wait_headscale(self):
        self.kubectl(
            "-n", "headscale", "rollout", "status", "statefulset/headscale", "--timeout=240s"
        )

    def restart_headscale(self):
        self.kubectl("-n", "headscale", "delete", "pod", "headscale-0", "--wait=true")
        self.wait_headscale()

    def headscale(self, *args, **kwargs):
        return self.exec("headscale", "headscale-0", "headscale", *args, container="headscale", **kwargs)

    def headscale_json(self, *args):
        return json.loads(self.headscale(*args, "-o", "json").stdout) or []

    def logs(self, container, **kwargs):
        return self.kubectl("-n", "headscale", "logs", "headscale-0", "-c", container, **kwargs).stdout

    def node(self, name):
        return next((n for n in self.headscale_json("nodes", "list") if n["given_name"] == name), None)

    def user_id(self, name):
        for user in self.headscale_json("users", "list"):
            if user["name"] == name:
                return user["id"]
        self.headscale("users", "create", name)
        return self.user_id(name)

    def preauth_key(self, user=None, tags=None):
        args = ["preauthkeys", "create", "--expiration", "15m"]
        if user:
            args += ["--user", str(self.user_id(user))]
        if tags:
            args += ["--tags", ",".join(tags), "--ephemeral"]
        return self.headscale(*args).stdout.strip()


class Device:
    """A tailscale pod."""

    def __init__(self, cluster, name):
        self.cluster = cluster
        self.name = name
        self.server = f"https://{public_host()}"

    def sh(self, script, **kwargs):
        return self.cluster.exec("testing", self.name, "sh", "-c", script, **kwargs)

    def tailscale(self, *args, **kwargs):
        return self.cluster.exec("testing", self.name, "tailscale", *args, **kwargs)

    def up(self, key, *args, **kwargs):
        return self.tailscale(
            "up", f"--login-server={self.server}", f"--authkey={key}",
            f"--hostname={self.name}", "--timeout=60s", *args, **kwargs,
        )

    def ip(self):
        return self.tailscale("ip", "-4").stdout.strip()

    def ssh(self, target, command, **kwargs):
        """`tailscale ssh`: returns the remote exit code, never raises."""
        return self.tailscale(
            "ssh", target, command, check=False, timeout=kwargs.pop("timeout", 60), **kwargs
        )

    def reaches(self, ip, port=22):
        """A real TCP connection through the tailnet. Not `tailscale ping`,
        which bypasses the access policy. An SSH server speaks first."""
        probe = self.sh(f"(sleep 4) | timeout 8 tailscale nc {ip} {port}", check=False)
        return probe.stdout.startswith("SSH-")

    def curl(self, path_or_url, *args):
        """(status code, body) of an HTTPS request from inside the cluster."""
        url = path_or_url if "://" in path_or_url else self.server + path_or_url
        out = self.cluster.exec(
            "testing", self.name, "curl", "-sS", "--cacert", "/ca/ca.crt", "--max-time", "20",
            "-w", "\n%{http_code}", *args, url,
        ).stdout
        body, _, code = out.rpartition("\n")
        return int(code), body


class Issuer:
    """Signs tokens shaped like GitHub Actions' OIDC ones."""

    URL = "http://issuer.testing.svc.cluster.local:8000"

    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def configmap(self):
        import jwt

        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid="test", use="sig", alg="RS256")
        discovery = {
            "issuer": self.URL,
            "jwks_uri": f"{self.URL}/jwks",
            "authorization_endpoint": f"{self.URL}/authorize",
            "token_endpoint": f"{self.URL}/token",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        return yaml.safe_dump({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "issuer", "namespace": "testing"},
            "data": {"jwks": json.dumps({"keys": [jwk]}), "openid-configuration": json.dumps(discovery)},
        })

    def token(self, key=None, **claims):
        import jwt

        github = values()["sts"]["github"]
        now = int(time.time())
        payload = {
            "iss": self.URL,
            "aud": f"https://{public_host()}/sts",
            "sub": f"repo:{github['repository']}:pull_request",
            "repository": github["repository"],
            "repository_id": github["repositoryID"],
            "jti": str(uuid.uuid4()),
            "iat": now,
            "nbf": now - 5,
            "exp": now + 300,
        }
        payload.update(claims)
        return jwt.encode(payload, key or self.key, algorithm="RS256", headers={"kid": "test"})
