---
name: dwg-to-kmz
description: Convert an AutoCAD drawing (DWG or DXF) into a KMZ that opens in Google Earth. Use when the user wants a .dwg/.dxf as KML or KMZ, wants CAD boundaries, estate/field/farm/zone plans or survey drawings shown in Google Earth or on a map, or says "convert to kmz", "dwg to kml", "dxf to kmz". Covers DWG→DXF with LibreDWG, finding the coordinate system, reprojecting to WGS 84, KML styling and folders, zipping to KMZ, and checking it fits Google Earth's import limits.
---

# DWG → DXF → KML → KMZ

The pipeline, all free and open source:

1. **DWG → DXF** with LibreDWG `dwg2dxf`. DWG is a closed format and this is the hard step.
2. **DXF → KML** with GDAL (bundled with QGIS) plus `scripts/dxf2kmz.py`. The script reprojects, builds polygons, styles the result and groups it into folders.
3. **KML → KMZ**: a KMZ is just a zip whose main file is `doc.kml`. The script writes it directly; pass `--kml` to also keep the plain `.kml`.

Scripts live next to this file in `scripts/`. Below, `$SK` means this skill's folder, for example `~/.claude/skills/dwg-to-kmz`, and `$W` means a scratch working folder.

## 0. Rules

- **Never modify the original drawing.** Copy it into `$W` and work on the copy. Paths with spaces break CLI tools, so name the copy something simple like `in.dwg`.
- Put downloaded tools in their own empty folder. Run Python that reads them or the drawing from a different folder.
- If the user only has a DXF, skip step 2.

## 1. Tools

- **GDAL with Python.** Always run Python through `bash $SK/scripts/qgis-python.sh script.py …`, which picks the right interpreter:
  - Windows: QGIS provides GDAL, PROJ and a Python that has `osgeo`. Check with `ls "/c/Program Files" | grep -i qgis`.
  - Linux/macOS: any `python3` that can `import osgeo` (`apt install python3-gdal` / `brew install gdal`).
  - Do **not** add `-I`: it ignores `PYTHONHOME`, and the interpreter dies with "No module named 'encodings'".
- **LibreDWG**: `DWG2DXF=$(bash $SK/scripts/get-libredwg.sh $W/libredwg)`. It prints the path of `dwg2dxf`:
  - Windows: downloads the portable 12 MB zip from GitHub, no install.
  - Linux/macOS: finds the packaged one (`apt install libredwg-tools` / `brew install libredwg`). Ask the user before installing it.
- QGIS's own "Import DWG/DXF" and GDAL's `CAD` driver only read old DWG versions (R2000 and earlier). On newer files they silently produce an **empty** result.
  - Check the version with `head -c 6 file.dwg`. AC1032 = 2018, AC1027 = 2013, AC1024 = 2010, AC1015 = 2000.
  - Anything newer than AC1015 goes through LibreDWG.
- **Fallback:** ODA File Converter is free but not open source, and is about a 70 MB install. Ask the user before installing it. Use it only if LibreDWG drops important entities (see step 4).

## 2. DWG → DXF

```bash
"$(dirname "$DWG2DXF")"/dwglayers* $W/in.dwg            # layer names: a first idea of what the drawing is
"$DWG2DXF" -y -o $W/in.dxf $W/in.dwg                     # "Unstable Class object" warnings are normal
```

## 3. Work out the coordinate system before converting

```bash
bash $SK/scripts/qgis-python.sh $SK/scripts/inspect_dxf.py $W/in.dxf
```

It prints the units (`$INSUNITS`; 6 = metres), the extents, any **embedded CRS**, and a count of each geometry type per layer with that layer's extent.

- **Embedded GEODATA wins.** Civil 3D drawings carry an Autodesk/MapGuide code such as `UTM84-36S`, which is WGS 84 / UTM 36S = EPSG:32736. `dxf2kmz.py` reads `UTM84-nnX` and `ARC1960…UTM-nnS` codes automatically. Any other code: pass `--epsg`.
- **No GEODATA:** reason from the extents. In UTM, eastings run about 160,000–840,000 m. Northings run up to about 10,000,000 m in the south (a northing of 9.55 million means about 4°S); in the north the northing is the distance from the equator.
  - East Africa: zone 36 covers about 30–36°E (western Kenya, Uganda, Kigoma, Mwanza). Zone 37 covers about 36–42°E (central and eastern Kenya, Dar es Salaam, Iringa).
  - Old Kenyan and Tanzanian surveys often use **Arc 1960**: EPSG:21036 / 21037 for zones 36S / 37S, or 21096 / 21097 for 36N / 37N.
  - Arc 1960 vs WGS 84 is a shift of about 200–300 m. If unsure, convert with both and compare against imagery (step 6).
  - Values in degrees (x around 30–40, y around −5 to 5): the drawing is already lon/lat. This script expects metres, so convert with plain `ogr2ogr` instead.
- If units are feet or mm, or the extents are tiny numbers around 0, the drawing is probably **not georeferenced**. Tell the user. It needs control points; don't guess.
- From the per-layer extents, look for features **far from the rest**: detail drawings placed at the origin, title blocks, and a large sheet-frame rectangle. The script drops entities more than `--far` metres (default 100 km) from the centre, and drops plain rectangles covering most of the map.

## 4. DXF → KML → KMZ

```bash
bash $SK/scripts/qgis-python.sh $SK/scripts/dxf2kmz.py $W/in.dxf "$W/Out Name.kmz" \
     [--epsg 32736] [--kml] \
     [--join-layers '^(AOI - PROJECT BORDER|Farm boundary.*)$'] \
     [--line-layers '<regex>'] [--hidden-layers '<regex>'] [--skip-layers '<regex>']
```

What it does:

| CAD entity | KML output |
|---|---|
| closed polyline / circle | **Polygon**, outlined in the layer colour with a light fill. Exception: layers matching `--line-layers` (contours, pipes, roads, streams…), where closed shapes stay lines |
| open polyline / line / arc | LineString (clamped to ground; Z dropped) |
| hatch / solid | filled Polygon (stronger fill) |
| block insert | point symbol named after the block (valves, pumps, outlets…) |
| TEXT / MTEXT | label-only placemark. A polygon containing exactly one label from its own layer, or from a "*name*" layer, takes that label as its name |
| paper space, Defpoints, dimensions, leaders | skipped and reported |

- Folders: theme (Boundaries & zones / Water / Terrain / Infrastructure / Other) → CAD layer → kind (Polygons, Lines, Labels…).
- Each placemark carries Layer, CAD handle, Block, and Area (ha) or Length (m).
- Contours, spot heights and layer `0` are **switched off by default** (`--hidden-layers`).
- Clean-up: exact duplicates and outlines that are just a hatch's border are removed, and so is the sheet frame. Invalid polygons are repaired, keeping the largest part.
- `--join-layers`: boundaries are often drawn as several open pieces whose ends miss by 5–30 m. This snaps them into one polygon within `--snap` (default 40 m) and reports the area. Use it only for layers you've confirmed are one ring, by looking at the endpoints.
- Geometry is simplified by 0.5 m (2 m on hidden layers) in metres before reprojecting. The difference is invisible, and it keeps the file under Google Earth's limits.

The script prints a JSON report. Keep it for the answer to the user: source CRS and why, counts per layer, skipped items and why, WGS 84 bbox, vertex count.

**Check what LibreDWG lost.** An entity can come out of `dwg2dxf` with no geometry; that happened to one 341 KB river polyline, which came back with 0 vertices. GDAL then errors with "Too many vertices found in LWPOLYLINE" and drops it. To find these, compare entity handles in the DXF against what OGR reads, or run `dwgread -O JSON` and look for entities with empty `points`/`vertexids`. Report them by layer and handle. Offer ODA File Converter if they matter.

## 5. Google Earth import limits

Google Earth (web) **"Import as map features"** has these limits:
- about 250,000 vertices per import;
- about 10,000 features per import (20,000 per project);
- lines and polygons over 10,000 vertices get simplified;
- more than 100 geometry errors aborts the whole import.

The report prints `vertices` and adds a `WARNING` when over. Usual culprits:
- **Contours.** Raise `--simplify-hidden`, or put them in a second KMZ using `--skip-layers` / a contour-only run.
- **An engineering detail drawn as a block** (a pump-house plan of 290k vertices). Block inserts are exported as points, so that one is already harmless; exploded linework is not.

Other import routes have no such limits:
- Google Earth **Pro**: use **File → Open**, not File → Import. Import is for shapefiles and other GIS formats.
- Earth web: **"Import as a data layer"**.

## 6. Verify before handing over

1. **Valid KML.** Check the XML parses and count placemarks:
   ```bash
   python -c "import zipfile,xml.dom.minidom as m,sys; d=m.parseString(zipfile.ZipFile(sys.argv[1]).read('doc.kml')); print(len(d.getElementsByTagName('Placemark')))" Out.kmz
   ```
   GDAL reading it back is a second check: `ogrinfo -q Out.kmz` via QGIS's `bin`.
2. **Right place.** The report's `bbox_wgs84` must fall where the user's site is. Kenyan sugar belt: about 34–35.5°E, 0.5°S–1°N. Kigoma: about 30–31°E, 3.5–5°S.
3. **Right alignment.** Overlay on satellite imagery: boundaries should follow field edges, river layers the real channels, roads the real roads.
   - Quick way: export some layers to GeoJSON and open a Leaflet page over Esri World Imagery (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`).
   - Serve it over `http://127.0.0.1`; the browser pane won't run scripts in a `file://` page.
   - An offset of about 200–300 m means the wrong datum (Arc 1960 vs WGS 84). Being kilometres out means the wrong zone or hemisphere.
4. Save the KMZ **next to the original** (same base name) unless told otherwise. Hand it over as a downloadable file (SendUserFile, display "attach").

## 7. Report to the user

- The CRS and the evidence for it (embedded GEODATA / units / extents / imagery check).
- Features per layer (polygons / lines / symbols / labels).
- What was joined, deduplicated or skipped, and why.
- What could not be converted, with layer and handle.
- If they hit an import error: the vertex count and which import route to use.

## Pitfalls seen in practice

- `re.sub(..., r'\1…')` inside a heredoc-written Python string can turn into `\x01`, producing invalid XML. Use a lambda replacement.
- `ogr.BuildPolygonFromEdges` snaps gaps but can return an **unclosed** ring. Call `CloseRings()`.
- Short 5–7 m stubs at a corner make the edge builder fail. Ignore segments shorter than the snap distance.
- KML schema order inside a Placemark is `name, visibility, …, styleUrl, ExtendedData, geometry`. Strict importers reject `visibility` before `name`.
- `MakeValid` can return a polygon plus a 2-point sliver, which comes out as a MultiGeometry. Keep the largest polygon.
- GDAL's DXF reader caps blocks at 10,000 features unless `DXF_FEATURE_LIMIT_PER_BLOCK=-1`.
