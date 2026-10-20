#!/usr/bin/env bash
# Download the latest portable LibreDWG (Windows x64, ~12 MB, GPL) into an EMPTY directory.
# Usage: bash get-libredwg.sh <dest-dir>      -> <dest-dir>/dwg2dxf.exe, dwglayers.exe, dwgread.exe
set -e
DEST=${1:?dest dir}
mkdir -p "$DEST"; cd "$DEST"
[ -x dwg2dxf.exe ] && { echo "already present: $DEST/dwg2dxf.exe"; exit 0; }
URL=$(curl -sL "https://api.github.com/repos/LibreDWG/libredwg/releases?per_page=1" \
      | grep -o 'https://[^"]*-win64\.zip' | head -1)
[ -n "$URL" ] || { echo "could not find a win64 release asset" >&2; exit 1; }
echo "downloading $URL"
curl -sLO "$URL"
unzip -q -o "$(basename "$URL")"
ls dwg2dxf.exe dwglayers.exe dwgread.exe
