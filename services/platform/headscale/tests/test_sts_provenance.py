"""The pinned headscale-sts binaries are what the pinned source builds.

headscale-sts is a third-party service holding a headscale admin key, run from
release binaries: this ties those binaries to a commit one can read. It compiles
the code, it never runs it."""

import hashlib
import os
import shutil

import pytest

import lib


@pytest.mark.skipif(not shutil.which("go"), reason="needs go")
def test_release_binaries_are_reproducible_from_the_pinned_commit(tmp_path):
    sts = lib.values()["sts"]
    source = tmp_path / "headscale-sts"
    repository = sts["releasesURL"].removesuffix("/releases/download")
    lib.run("git", "clone", "--quiet", f"{repository}.git", source)
    lib.run("git", "-C", source, "-c", "advice.detachedHead=false", "checkout", "--quiet", sts["version"])
    head = lib.run("git", "-C", source, "rev-parse", "HEAD").stdout.strip()
    assert head == sts["commit"], f"the tag {sts['version']} moved"

    # Exactly the upstream release workflow: both architectures into dist/ in
    # this order (the second build sees an untracked file, which is stamped in).
    (source / "dist").mkdir()
    for arch in ("amd64", "arm64"):
        binary = source / "dist" / f"headscale-sts-{sts['version']}-linux-{arch}"
        os.environ.update(GOTOOLCHAIN=sts["goVersion"], CGO_ENABLED="0", GOOS="linux", GOARCH=arch)
        try:
            lib.run("go", "-C", source, "build", "-trimpath", "-ldflags",
                    f"-s -w -X main.version={sts['version']}", "-o", binary, ".")
        finally:
            for name in ("GOTOOLCHAIN", "CGO_ENABLED", "GOOS", "GOARCH"):
                os.environ.pop(name, None)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == sts["sha256"][arch], arch
