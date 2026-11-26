"""A person logging a device in through the identity provider (a mock one in
place of authentik): public client, PKCE, unverified e-mail."""

import re
import threading
from urllib.parse import parse_qs, urlparse

import pytest

import lib

pytestmark = pytest.mark.e2e


def test_interactive_login_registers_a_personal_node(cluster, device):
    laptop = device("laptop")
    login = {}

    def up():
        login["result"] = laptop.tailscale(
            "up", f"--login-server={laptop.server}", f"--hostname={laptop.name}", "--timeout=120s",
            check=False, timeout=150,
        )

    thread = threading.Thread(target=up)
    thread.start()

    def auth_url():
        status = laptop.tailscale("status", "--json", check=False).stdout
        found = re.search(r'"AuthURL":\s*"(https://[^"]+)"', status)
        return found.group(1) if found else None

    url = lib.wait_for(auth_url, "the login URL", timeout=60)

    # The browser: follows the redirects to the provider and back.
    browser = ("-L", "-c", "/tmp/cookies", "-b", "/tmp/cookies")
    status, page = laptop.curl(url, *browser, "-D", "/tmp/headers")
    assert status == 200, page
    redirect = re.search(r"(?im)^location:\s*(\S*/oidc/authorize\S*)", laptop.sh("cat /tmp/headers").stdout)
    assert redirect, "no redirect to the identity provider"
    query = parse_qs(urlparse(redirect.group(1)).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [f"{laptop.server}/oidc/callback"]

    # headscale may ask the person to confirm the device before registering it.
    form = re.search(r'<form[^>]*action="([^"]+)"', page)
    if form:
        fields = re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page)
        data = [arg for name, value in fields for arg in ("--data-urlencode", f"{name}={value}")]
        status, page = laptop.curl(form.group(1), *browser, *data)
        assert status == 200, page

    thread.join(timeout=150)
    assert login["result"].returncode == 0, login["result"].stderr
    node = cluster.node(laptop.name)
    assert node["user"]["email"] == "carol@example.com"
    assert not node.get("tags")
