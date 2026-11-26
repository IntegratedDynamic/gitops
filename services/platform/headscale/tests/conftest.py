"""One kind cluster per test session, deployed from the charts of this checkout.

HEADSCALE_TEST_KEEP=1 keeps the cluster afterwards (it is reused by the next run
only after being recreated: state from a previous session would skew results)."""

import datetime
import os
import shutil
import uuid

import pytest

import lib

CLUSTER_NAME = os.environ.get("HEADSCALE_TEST_CLUSTER", "headscale-e2e")


def certificates(host):
    """A throwaway CA and a server certificate for `host`."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def build(subject, issuer, public_key, signing_key, extensions):
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=2))
        )
        for extension, critical in extensions:
            builder = builder.add_extension(extension, critical=critical)
        return builder.sign(signing_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca = build("headscale-test-ca", "headscale-test-ca", ca_key.public_key(), ca_key, [
        (x509.BasicConstraints(ca=True, path_length=None), True),
        (x509.KeyUsage(False, False, False, False, False, True, True, False, False), True),
        (ca_ski, False),
    ])
    cert = build(host, "headscale-test-ca", key.public_key(), ca_key, [
        (x509.BasicConstraints(ca=False, path_length=None), True),
        (x509.SubjectAlternativeName([x509.DNSName(host)]), False),
        (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False),
        (x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), False),
    ])
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return ca, cert, key_pem


@pytest.fixture(scope="session")
def issuer():
    return lib.Issuer()


@pytest.fixture(scope="session")
def cluster(tmp_path_factory, issuer):
    for tool in ("docker", "kind", "kubectl", "helm"):
        if not shutil.which(tool):
            pytest.fail(f"{tool} is required for the e2e tests (or run with -m 'not e2e')")
    tmp = tmp_path_factory.mktemp("cluster")
    cluster = lib.Cluster(CLUSTER_NAME, tmp / "kubeconfig")
    delete = ("kind", "delete", "cluster", "--name", CLUSTER_NAME, "--kubeconfig", cluster.kubeconfig)
    lib.run(*delete)
    lib.run("kind", "create", "cluster", "--name", CLUSTER_NAME, "--kubeconfig", cluster.kubeconfig,
            "--wait", "120s")
    try:
        _provision(cluster, issuer, tmp)
        yield cluster
    finally:
        if os.environ.get("HEADSCALE_TEST_KEEP"):
            print(f"\nkept cluster {CLUSTER_NAME}, kubeconfig {cluster.kubeconfig}")
        else:
            lib.run(*delete)


def _provision(cluster, issuer, tmp):
    lib.run(
        "helm", "--kubeconfig", cluster.kubeconfig, "--kube-context", cluster.context,
        "install", "eg", "oci://docker.io/envoyproxy/gateway-helm",
        "--version", lib.envoy_gateway_version(),
        "--namespace", "envoy-gateway-system", "--create-namespace", "--wait", "--timeout", "5m",
    )
    for namespace in ("gateway", "headscale", "testing"):
        cluster.kubectl("create", "namespace", namespace)

    ca, cert, key = certificates(lib.public_host())
    for name, content in (("ca.crt", ca), ("tls.crt", cert), ("tls.key", key)):
        (tmp / name).write_text(content)
    cluster.kubectl("-n", "gateway", "create", "secret", "tls", "headscale-tls",
                    f"--cert={tmp / 'tls.crt'}", f"--key={tmp / 'tls.key'}")
    cluster.kubectl("-n", "testing", "create", "configmap", "test-ca", f"--from-file=ca.crt={tmp / 'ca.crt'}")
    cluster.apply((lib.TESTS / "manifests/gateway.yaml").read_text())

    cluster.apply(issuer.configmap())
    cluster.apply((lib.TESTS / "manifests/issuer.yaml").read_text())
    oidc = lib.values()["oidc"]
    cluster.apply(
        (lib.TESTS / "manifests/mockoidc.yaml").read_text(),
        HEADSCALE_IMAGE=lib.headscale_image(),
        OIDC_CLIENT_ID=oidc["clientID"],
        OIDC_CLIENT_SECRET=oidc["clientSecretPlaceholder"],
    )
    cluster.kubectl("-n", "testing", "wait", "--for=condition=Ready", "pod", "--all", "--timeout=180s")
    mock_ip = cluster.get("-n", "testing", "pod", "mockoidc")["status"]["podIP"]

    # The deployed configuration, with only the identity providers replaced.
    cluster.chart_sets = {
        "serviceMonitor.enabled": "false",  # no Prometheus operator here
        "oidc.issuer": f"http://{mock_ip}:10000/oidc",
        "sts.github.issuer": issuer.URL,
    }
    cluster.deploy_headscale(wait=False)
    cluster.apply(lib.helm_template(lib.GATEWAY_CHART, "headscale-gateway"))
    cluster.wait_headscale()

    def gateway_ip():
        services = cluster.get("-n", "envoy-gateway-system", "services")["items"]
        return next((s["spec"]["clusterIP"] for s in services if s["spec"]["type"] == "LoadBalancer"), None)

    cluster.gateway_ip = lib.wait_for(gateway_ip, "the gateway Service")
    lib.wait_for(lambda: _route_accepted(cluster), "the route and its upgrade policy")


def _route_accepted(cluster):
    route = cluster.get("-n", "headscale", "httproute", "headscale")
    policy = cluster.get("-n", "headscale", "backendtrafficpolicy", "headscale")
    conditions = [c for p in route.get("status", {}).get("parents", []) for c in p["conditions"]]
    conditions += [c for a in policy.get("status", {}).get("ancestors", []) for c in a["conditions"]]
    return bool(conditions) and all(c["status"] == "True" for c in conditions)


@pytest.fixture(scope="session")
def device(cluster):
    """Factory of tailscale pods, not joined yet."""

    def create(prefix="device"):
        name = f"{prefix}-{uuid.uuid4().hex[:6]}"
        cluster.apply(
            (lib.TESTS / "manifests/tailscale.yaml").read_text(),
            NAME=name, GATEWAY_IP=cluster.gateway_ip, HOSTNAME=lib.public_host(),
            TAILSCALE_VERSION=lib.TAILSCALE_VERSION,
        )
        cluster.kubectl("-n", "testing", "wait", "--for=condition=Ready", f"pod/{name}", "--timeout=180s")
        return lib.Device(cluster, name)

    return create


@pytest.fixture(scope="session")
def toolbox(device):
    """A pod used only to send HTTPS requests to the public URL."""
    return device("toolbox")


@pytest.fixture(scope="session")
def member(cluster, device):
    """A person's device."""
    pod = device("member")
    pod.up(cluster.preauth_key(user="alice"))
    return pod


@pytest.fixture(scope="session")
def ci_runner(cluster, device):
    """A CI runner's device, joined like the debug step does."""

    def create():
        pod = device("runner")
        pod.up(cluster.preauth_key(tags=["tag:ci-debug"]), "--ssh")
        return pod

    return create


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Attaches headscale's logs to a failed e2e test: the cluster is gone by
    the time anyone reads the CI output."""
    report = yield
    cluster = item.funcargs.get("cluster") if hasattr(item, "funcargs") else None
    if report.failed and cluster:
        for container in ("headscale", "sts"):
            logs = cluster.kubectl("-n", "headscale", "logs", "headscale-0", "-c", container,
                                   "--tail=60", check=False)
            report.sections.append((f"logs of {container}", logs.stdout + logs.stderr))
    return report
