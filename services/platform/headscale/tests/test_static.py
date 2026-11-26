"""Checks that need no cluster: what the charts render, and the names that must
agree between files. A mismatch there fails silently on a real cluster (a restore
that restores nothing, a route no client can use)."""

import re

import pytest

import lib

HEADSCALE_VELERO_VALUES = lib.REPO / "services/platform/velero/chart/values-scaleway.yaml"


@pytest.fixture(scope="module")
def rendered():
    return lib.render(lib.CHART)


@pytest.fixture(scope="module")
def gateway():
    return lib.render(lib.GATEWAY_CHART, "headscale-gateway")


def containers(objects):
    pod = objects[("StatefulSet", "headscale")]["spec"]["template"]["spec"]
    return {c["name"]: c for c in pod["containers"]}


def config(objects, key="config.yaml"):
    import yaml

    return yaml.safe_load(objects[("ConfigMap", "headscale-config")]["data"][key])


@pytest.mark.parametrize("chart", ["chart", "gateway"])
def test_chart_lints(chart):
    lib.run("helm", "lint", lib.HEADSCALE / chart)


def test_restore_chart_renders(tmp_path):
    import shutil

    # `dependency build` writes next to the chart: work on a copy.
    shutil.copytree(lib.REPO / "charts/velero-pvc-restore", tmp_path / "charts/velero-pvc-restore")
    restore = tmp_path / "services/platform/headscale/restore"
    shutil.copytree(lib.HEADSCALE / "restore", restore)
    lib.run("helm", "dependency", "build", restore)
    lib.run("helm", "template", "headscale-restore", restore, "--namespace", "headscale")


def test_configuration_is_valid_with_sso(rendered, tmp_path):
    """headscale's own validation of the deployed configuration, OIDC included.
    Only the identity provider is made optional: configtest contacts it, and
    there is none here (test_oidc_login.py logs in through one)."""
    data = dict(rendered[("ConfigMap", "headscale-config")]["data"])
    required = "only_start_if_oidc_is_available: true"
    assert required in data["config.yaml"]
    data["config.yaml"] = data["config.yaml"].replace(required, "only_start_if_oidc_is_available: false")
    data["config.yaml"] = re.sub(r"(?m)^(\s*issuer:).*$", r"\1 http://127.0.0.1:1/oidc", data["config.yaml"])
    for name in ("config.yaml", "policy.hujson"):
        (tmp_path / name).write_text(data[name])
    tmp_path.chmod(0o755)
    lib.run(
        "docker", "run", "--rm", "--tmpfs", "/var/lib/headscale", "--tmpfs", "/var/run/headscale",
        "-v", f"{tmp_path}:/etc/headscale:ro", "--entrypoint", "/ko-app/headscale",
        lib.headscale_image(), "configtest",
    )


@pytest.mark.parametrize("suffix", ["", "-pr-12"])
def test_every_public_name_agrees(suffix):
    chart = lib.render(lib.CHART, sets={"hostSuffix": suffix})
    route = lib.render(lib.GATEWAY_CHART, "headscale-gateway", sets={"hostSuffix": suffix})
    host = lib.public_host(suffix)

    assert route[("HTTPRoute", "headscale")]["spec"]["hostnames"] == [host]
    server = config(chart)
    assert server["server_url"] == f"https://{host}"
    assert server["oidc"]["issuer"].startswith(f"https://sso{suffix}.")
    assert config(chart, "sts.yaml")["trusts"][0]["audience"] == f"https://{host}/sts"
    # headscale refuses a MagicDNS zone that contains its own URL.
    assert not host.endswith(server["dns"]["base_domain"])


def test_long_lived_connections_are_not_cut(gateway):
    rules = gateway[("HTTPRoute", "headscale")]["spec"]["rules"]
    root = next(r for r in rules if r["matches"][0]["path"]["value"] == "/")
    assert root["timeouts"]["request"] == "0s"


def test_only_the_public_ports_are_routed(rendered, gateway):
    routed = {b["port"] for r in gateway[("HTTPRoute", "headscale")]["spec"]["rules"] for b in r["backendRefs"]}
    ports = {p["name"]: p["port"] for p in rendered[("Service", "headscale")]["spec"]["ports"]}
    assert routed == {ports["http"], ports["sts"]}
    assert ports["metrics"] not in routed
    assert config(rendered)["grpc_listen_addr"].startswith("127.0.0.1:")


def test_backup_and_restore_select_the_data_volume(rendered):
    schedules = lib.load_yaml(HEADSCALE_VELERO_VALUES)["velero"]["schedules"]
    restore = lib.load_yaml(lib.HEADSCALE / "restore/values.yaml")["restore"]
    statefulset = rendered[("StatefulSet", "headscale")]
    labels = statefulset["spec"]["selector"]["matchLabels"]
    claims = [
        f"{t['metadata']['name']}-{statefulset['metadata']['name']}-0"
        for t in statefulset["spec"]["volumeClaimTemplates"]
    ]

    name = restore["scheduleName"].removeprefix("velero-")
    assert restore["scheduleName"] == f"velero-{name}" and name in schedules
    template = schedules[name]["template"]
    selector = {restore["selectorLabel"]["key"]: restore["selectorLabel"]["value"]}
    assert restore["enabled"] is True
    assert restore["pvcs"] == claims
    assert template["includedNamespaces"] == [statefulset["metadata"]["namespace"]]
    assert template["labelSelector"]["matchLabels"] == selector
    assert selector.items() <= labels.items()


def test_ci_tags_exist_in_the_policy():
    owners = re.search(r'"tagOwners"\s*:\s*\{(.*?)\}', lib.POLICY.read_text(), re.S).group(1)
    for tag in lib.values()["sts"]["tags"]:
        assert f'"{tag}"' in owners


def test_ci_keys_are_limited_to_this_organisation(rendered):
    trust = config(rendered, "sts.yaml")["trusts"][0]
    assert trust["issuer"] == "https://token.actions.githubusercontent.com"
    for rule in trust["rules"]:
        assert rule["match"]["repository"].startswith("IntegratedDynamic/")
        assert rule["match"]["repository_id"].isdigit()
        assert rule["key"] == {"ephemeral": True, "reusable": False, "expiry": "5m"}


def test_sts_is_pinned(rendered):
    sts = lib.values()["sts"]
    assert re.fullmatch(r"[0-9a-f]{40}", sts["commit"])
    for arch in ("amd64", "arm64"):
        assert re.fullmatch(r"[0-9a-f]{64}", sts["sha256"][arch])
    mounts = {m["name"] for m in containers(rendered)["sts"]["volumeMounts"]}
    assert "data" not in mounts, "headscale-sts must not see the data volume"


def test_both_containers_run_the_same_headscale(rendered):
    c = containers(rendered)
    assert c["sts"]["image"] == c["headscale"]["image"] + "-debug"


def test_sts_can_be_removed_entirely():
    chart = lib.render(lib.CHART, sets={"sts.enabled": "false"})
    route = lib.render(lib.GATEWAY_CHART, "headscale-gateway", sets={"sts.enabled": "false"})
    assert list(containers(chart)) == ["headscale"]
    assert "sts.sh" not in chart[("ConfigMap", "headscale-config")]["data"]
    assert [p["name"] for p in chart[("Service", "headscale")]["spec"]["ports"]] == ["http", "metrics"]
    assert len(route[("HTTPRoute", "headscale")]["spec"]["rules"]) == 1
