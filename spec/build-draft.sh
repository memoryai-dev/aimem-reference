#!/usr/bin/env bash
# Build IETF formats from kramdown-rfc markdown source.
# Requires: kramdown-rfc (gem) + xml2rfc (pip).
#
# Output: draft-vu-aimem-bundle-NN.{xml,txt} ready for datatracker submit.
set -e
cd "$(dirname "$0")"
SRC="${1:-draft-vu-aimem-bundle-01.md}"
BASE="${SRC%.md}"
echo "==> kramdown-rfc → ${BASE}.xml"
kramdown-rfc "$SRC" > "${BASE}.xml" 2>/tmp/kramdown-rfc.err
[ -s /tmp/kramdown-rfc.err ] && cat /tmp/kramdown-rfc.err
echo "==> xml2rfc → ${BASE}.txt"
xml2rfc --text "${BASE}.xml" -o "${BASE}.txt"
echo "==> Output:"
ls -la "${BASE}".{xml,txt}
