# dwg-to-kmz

A [Claude Code](https://claude.com/claude-code) skill that converts AutoCAD drawings (DWG or DXF) into a KMZ that opens in Google Earth. It reprojects to WGS 84, turns closed outlines into polygons, keeps CAD layers as folders, and checks the result against Google Earth's import limits.

The pipeline uses only free, open-source tools:

```
DWG ──LibreDWG dwg2dxf──▶ DXF ──GDAL + scripts/dxf2kmz.py──▶ KML ──zip──▶ KMZ
```

## Install

Clone the repo straight into your Claude Code skills folder:

```bash
git clone https://github.com/silaselisha/dwg-to-kmz.git ~/.claude/skills/dwg-to-kmz
```

Start a new Claude Code session and ask, for example, *"convert Desktop/ESTATE BOUNDARIES.dwg to kmz"*. The skill loads on its own.

## Requirements (Windows)

- **[QGIS](https://qgis.org)**: supplies GDAL, PROJ and a Python with `osgeo`. `scripts/qgis-python.sh` finds it under `C:\Program Files\QGIS *`.
- **[LibreDWG](https://github.com/LibreDWG/libredwg)**: the portable Windows build (~12 MB). `scripts/get-libredwg.sh <dir>` downloads it.
- Git Bash (for the `.sh` helpers).

## Using the scripts without Claude

```bash
bash scripts/get-libredwg.sh tools/libredwg
tools/libredwg/dwg2dxf.exe -y -o in.dxf in.dwg
bash scripts/qgis-python.sh scripts/inspect_dxf.py in.dxf          # units, extents, embedded CRS, layers
bash scripts/qgis-python.sh scripts/dxf2kmz.py in.dxf "Out.kmz" --kml \
     [--epsg 32736] [--join-layers '^(Farm boundary.*)$']
```

`dxf2kmz.py` prints a JSON report. It covers:
- the source CRS and where it came from;
- feature counts per layer;
- what was skipped or joined, and why;
- the WGS 84 bounding box;
- the vertex count, with a warning above Google Earth's 250k-vertex / 10k-feature limits for "Import as map features".

See [SKILL.md](SKILL.md) for the full procedure:
- working out the coordinate system (embedded Civil 3D GEODATA, UTM zones, Arc 1960 vs WGS 84);
- checking the result against satellite imagery;
- pitfalls met in practice.

## License

MIT
