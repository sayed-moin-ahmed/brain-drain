#!/bin/sh
# Installs dist/unrot_<version>_all.deb in clean containers and checks it:
# lintian, the test suite on that distro's Python, the installed app, and removal.
#
# The first run builds one image per distro with all dependencies (slow, needs network).
# Later runs reuse the images and run with no network at all (fast). Rebuild images with
#   REBUILD=1 ./packaging/check-distros.sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DISTROS=${DISTROS:-"ubuntu:24.04 ubuntu:26.04 ubuntu:26.10 debian:13"}
DEPS="python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gsettings-desktop-schemas xvfb xauth dbus lintian"
DEB=$(ls "$ROOT"/dist/unrot_*_all.deb | sort -V | tail -1)
LOGS=$(mktemp -d)

for distro in $DISTROS; do
    tag="unrot-check:$(echo "$distro" | tr ':' '-')"
    if [ "${REBUILD:-0}" = 1 ] || ! docker image inspect "$tag" >/dev/null 2>&1; then
        echo "building $tag (one time)..."
        printf 'FROM %s\nRUN apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 update -qq && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 install -y -qq --no-install-recommends %s >/dev/null\n' \
            "$distro" "$DEPS" | timeout 1800 docker build -q -t "$tag" - >/dev/null
    fi
done

check() {
    distro=$1
    tag="unrot-check:$(echo "$distro" | tr ':' '-')"
    timeout 300 docker run --rm --network none -v "$ROOT:/src:ro" -v "$DEB:/tmp/unrot.deb:ro" "$tag" sh -c '
        export DEBIAN_FRONTEND=noninteractive GTK_A11Y=none G_ENABLE_DIAGNOSTIC=1 PYTHONWARNINGS=default
        . /etc/os-release
        dpkg -i /tmp/unrot.deb >/tmp/i.log 2>&1 || { echo "$PRETTY_NAME: INSTALL FAILED"; tail -5 /tmp/i.log; exit 1; }
        lint=$(lintian --pedantic /tmp/unrot.deb 2>/dev/null | grep -E "^[EWP]:" | sed "s/^\(.\): unrot: \([^ ]*\).*/\1:\2/" | sort -u | tr "\n" " ")
        cp -r /src /tmp/s && cd /tmp/s
        dbus-run-session -- xvfb-run -a python3 -m unittest >/tmp/t.log 2>&1; t=$?
        ours=$(grep -cE "/tmp/s/(unrot|tests)/.*Warning" /tmp/t.log)
        cd / && UNROT_DATA_DIR=/tmp/d timeout 30 dbus-run-session -- xvfb-run -a /usr/bin/unrot --smoke >/tmp/s.log 2>&1; s=$?
        gtk=$(grep -cE "Adwaita-(WARNING|CRITICAL)|Gtk-(WARNING|CRITICAL)" /tmp/s.log /tmp/t.log | awk -F: "{n+=\$2} END {print n}")
        apt-get remove -y -qq unrot >/dev/null 2>&1; [ -e /usr/share/unrot ] && rm=left || rm=clean
        echo "$PRETTY_NAME | py $(python3 -V | cut -d" " -f2) | adw $(dpkg-query -W -f="\${Version}" gir1.2-adw-1)"
        echo "  install=ok tests=$(grep -E "^Ran" /tmp/t.log | cut -d" " -f2)/exit=$t our-warnings=$ours smoke=$s gtk-adw-warnings=$gtk remove=$rm"
        echo "  lintian: ${lint:-clean}"
        [ "$t" = 0 ] && [ "$s" = 0 ] && [ "$ours" = 0 ] && [ "$gtk" = 0 ] && [ "$rm" = clean ] || { tail -5 /tmp/t.log /tmp/s.log; exit 1; }
    '
}

echo "checking $(basename "$DEB") ($(sha256sum "$DEB" | cut -c1-12))"
fail=0
for distro in $DISTROS; do
    (check "$distro" >"$LOGS/$(echo "$distro" | tr ':' '-')" 2>&1; echo "exit=$?" >>"$LOGS/$(echo "$distro" | tr ':' '-')") &
done
wait
for f in "$LOGS"/*; do
    cat "$f"
    grep -q '^exit=0$' "$f" || fail=1
done
rm -rf "$LOGS"
[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
