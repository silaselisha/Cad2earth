#!/usr/bin/env bash
# Run a script with a Python that has GDAL's osgeo bindings.
#   Windows: QGIS's bundled Python (C:/Program Files/QGIS */).
#   Linux/macOS: the system python3 if it can `import osgeo`
#     (apt install python3-gdal  |  brew install gdal && pip install gdal==$(gdal-config --version)).
# Usage: bash qgis-python.sh script.py args...
# Do NOT use `python -I` with QGIS: -I ignores PYTHONHOME and the interpreter cannot find its stdlib.
Q=$(ls -d "/c/Program Files/QGIS "* 2>/dev/null | sort -V | tail -1)
if [ -n "$Q" ]; then
  PYDIR=$(ls -d "$Q"/apps/Python3* | head -1)
  export PATH="$Q/bin:$Q/apps/gdal/bin:$PATH" PYTHONHOME="$PYDIR" PYTHONPATH="$PYDIR/Lib/site-packages" \
         GDAL_DATA="$Q/apps/gdal/share/gdal" PROJ_DATA="$Q/share/proj"
  exec "$Q/bin/python.exe" -s -P "$@"
fi
for PY in python3 python; do
  if command -v "$PY" >/dev/null && "$PY" -c 'from osgeo import ogr' 2>/dev/null; then
    exec "$PY" "$@"
  fi
done
echo "No Python with GDAL found. Install QGIS (Windows), 'apt install python3-gdal' (Debian/Ubuntu)" \
     "or 'brew install gdal' + 'pip install gdal' (macOS)." >&2
exit 1
