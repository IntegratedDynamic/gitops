#!/busybox/sh
# Fetches headscale-sts, gives it a headscale API key of its own, then runs it.
#
# It retries in place instead of exiting while it waits: a crash-looping
# container makes the whole pod unready, which would take headscale down with it.
set -eu
trap 'exit 0' TERM

case "$(uname -m)" in
  x86_64) arch=amd64 sha="$STS_SHA256_AMD64" ;;
  aarch64) arch=arm64 sha="$STS_SHA256_ARM64" ;;
  *) echo "headscale-sts: unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac
url="$STS_RELEASES_URL/$STS_VERSION/headscale-sts-$STS_VERSION-linux-$arch"
bin=/opt/sts/headscale-sts

# The checksum is what makes the download trustworthy: busybox wget does not
# validate TLS certificates. Nothing runs unless it matches.
verified() { [ -f "$bin" ] && echo "$sha  $bin" | sha256sum -c -s; }

until verified; do
  rm -f "$bin"
  wget -q -T 30 -O "$bin" "$url" || true
  verified && break
  echo "headscale-sts: download or checksum verification failed ($url), retrying" >&2
  sleep 10
done
chmod 0500 "$bin"

until headscale apikeys list >/dev/null 2>&1; do sleep 2; done

# A new key at every start, kept in memory only. Nothing else can read an older
# one (headscale stores a hash), so they are simply left to expire.
umask 077
headscale apikeys create --expiration "$STS_APIKEY_EXPIRATION" >/run/sts/apikey

exec "$bin" -config /etc/headscale-sts/sts.yaml
