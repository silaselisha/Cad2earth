#!/usr/bin/env bash
# Get LibreDWG's dwg2dxf and print the path to use.
#   Windows (Git Bash): download the latest portable build (~12 MB, GPL) into an EMPTY directory.
#   Linux/macOS: use the package manager's dwg2dxf if it is on PATH, else say how to install it.
# Usage: DWG2DXF=$(bash get-libredwg.sh <dest-dir>)
set -e
DEST=${1:?dest dir}
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    mkdir -p "$DEST"; cd "$DEST"
    if [ ! -x dwg2dxf.exe ]; then
      URL=$(curl -sL "https://api.github.com/repos/LibreDWG/libredwg/releases?per_page=1" \
            | grep -o 'https://[^"]*-win64\.zip' | head -1)
      [ -n "$URL" ] || { echo "could not find a win64 release asset" >&2; exit 1; }
      echo "downloading $URL" >&2
      curl -sLO "$URL"
      unzip -q -o "$(basename "$URL")"
    fi
    echo "$(pwd)/dwg2dxf.exe" ;;
  *)
    if command -v dwg2dxf >/dev/null; then command -v dwg2dxf; exit 0; fi
    echo "dwg2dxf not found. Install LibreDWG:" >&2
    echo "  Debian/Ubuntu: sudo apt install libredwg-tools" >&2
    echo "  macOS:         brew install libredwg" >&2
    echo "  other:         build from https://github.com/LibreDWG/libredwg/releases" >&2
    exit 1 ;;
esac
