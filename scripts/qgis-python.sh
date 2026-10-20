#!/usr/bin/env bash
# Run a script with QGIS's bundled Python + GDAL (has osgeo.ogr, PROJ data, DXF and KML drivers).
# Usage: bash qgis-python.sh script.py args...
# Do NOT use `python -I` here: -I ignores PYTHONHOME and the interpreter cannot find its stdlib.
Q=$(ls -d "/c/Program Files/QGIS "* 2>/dev/null | sort -V | tail -1)
[ -n "$Q" ] || { echo "QGIS not found under C:/Program Files (install QGIS, or use OSGeo4W)" >&2; exit 1; }
PYDIR=$(ls -d "$Q"/apps/Python3* | head -1)
export PATH="$Q/bin:$Q/apps/gdal/bin:$PATH" PYTHONHOME="$PYDIR" PYTHONPATH="$PYDIR/Lib/site-packages" \
       GDAL_DATA="$Q/apps/gdal/share/gdal" PROJ_DATA="$Q/share/proj"
exec "$Q/bin/python.exe" -s -P "$@"
