#!/bin/sh
# Builds dist/unrot_<version>_all.deb from the source tree.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PKG="$ROOT/packaging"
APP_ID=io.github.unrot.Unrot
VERSION=$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import unrot; print(unrot.VERSION)")
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# mktemp creates 0700; the package root becomes "/" on install, so it must be 0755.
chmod 755 "$STAGE"

install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/share/unrot/unrot" \
    "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/metainfo" "$STAGE/usr/share/doc/unrot" "$STAGE/usr/share/man/man1"

sed "s/@VERSION@/$VERSION/" "$PKG/control" > "$STAGE/DEBIAN/control"
install -m 755 "$PKG/postinst" "$PKG/prerm" "$STAGE/DEBIAN/"
install -m 755 "$PKG/unrot.launcher" "$STAGE/usr/bin/unrot"
install -m 644 "$ROOT"/unrot/*.py "$STAGE/usr/share/unrot/unrot/"
install -m 644 "$PKG/$APP_ID.desktop" "$STAGE/usr/share/applications/"
install -m 644 "$PKG/$APP_ID.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$PKG/$APP_ID.metainfo.xml" "$STAGE/usr/share/metainfo/"
install -m 644 "$PKG/copyright" "$STAGE/usr/share/doc/unrot/"
gzip -9n -c "$PKG/changelog" > "$STAGE/usr/share/doc/unrot/changelog.gz"
gzip -9n -c "$PKG/unrot.1" > "$STAGE/usr/share/man/man1/unrot.1.gz"
chmod 644 "$STAGE/usr/share/doc/unrot/changelog.gz" "$STAGE/usr/share/man/man1/unrot.1.gz"

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/unrot_${VERSION}_all.deb"
# xz, not the zstd default: older dpkg (e.g. Debian 12) cannot read zstd.
dpkg-deb -Zxz --root-owner-group --build "$STAGE" "$OUT"
