"""DXF -> KML -> KMZ for Google Earth, reprojected to WGS 84.

Run with QGIS's bundled Python (see qgis-python.sh), e.g.
  bash qgis-python.sh dxf2kmz.py drawing.dxf "Drawing.kmz" [--epsg 32736] [--kml]

CAD layers become KML folders (grouped by theme), closed polylines become polygons,
hatches become filled areas, block inserts become symbol points, texts become labels.
Prints a JSON report (counts per layer, what was skipped and why, WGS 84 bbox, vertices).
"""
import argparse, colorsys, collections, json, re, sys, zipfile, zlib
from xml.sax.saxutils import escape
from osgeo import ogr, osr, gdal

ogr.DontUseExceptions()
gdal.PushErrorHandler('CPLQuietErrorHandler')
gdal.SetConfigOption('DXF_FEATURE_LIMIT_PER_BLOCK', '-1')
gdal.SetConfigOption('DXF_INLINE_BLOCKS', 'FALSE')

ap = argparse.ArgumentParser()
ap.add_argument('dxf')
ap.add_argument('kmz')
ap.add_argument('--epsg', type=int, help='source CRS; default: read from the DXF GEODATA object')
ap.add_argument('--kml', action='store_true', help='also write the plain .kml next to the .kmz')
ap.add_argument('--name', help='document name (default: KMZ file name)')
ap.add_argument('--line-layers', default=r'(?i)contour|elev|pipe|main ?line|grp|road|stream|drain|canal|cable|track|river ?line',
                help='regex: layers whose closed polylines stay lines (never polygons)')
ap.add_argument('--hidden-layers', default=r'(?i)^(0|elevation|contours?|spot ?heights?)$',
                help='regex: layers exported but switched off by default')
ap.add_argument('--skip-layers', default=r'(?i)^defpoints$', help='regex: layers left out entirely')
ap.add_argument('--join-layers', default='',
                help='regex: layers whose open segments should be snapped into ONE closed polygon')
ap.add_argument('--snap', type=float, default=40.0, help='max end gap (m) when joining --join-layers')
ap.add_argument('--simplify', type=float, default=0.5, help='simplify tolerance in metres (0 = off)')
ap.add_argument('--simplify-hidden', type=float, default=2.0, help='tolerance for hidden layers (contours)')
ap.add_argument('--far', type=float, default=100000.0,
                help='drop entities further than this (m) from the drawing centre (details drawn at the origin)')
args = ap.parse_args()

# ---- CRS ---------------------------------------------------------------------------------
def geodata_epsg(path):
    txt = open(path, encoding='utf-8', errors='replace').read()
    ids = sorted(set(re.findall(r'ProjectedCoordinateSystem id="([^"]+)"', txt)))
    for cid in ids:
        m = re.match(r'(?i)^UTM84-(\d{1,2})([NS])$', cid)  # Autodesk/MapGuide code for WGS 84 / UTM
        if m:
            return (32600 if m.group(2).upper() == 'N' else 32700) + int(m.group(1)), cid
        m = re.match(r'(?i)^ARC1960[._-]?UTM-?(\d{1,2})S$', cid)
        if m:
            return 21000 + int(m.group(1)), cid
    return None, ids

epsg, why = (args.epsg, 'given on the command line') if args.epsg else geodata_epsg(args.dxf)
if not epsg:
    sys.exit('No usable GEODATA CRS in the drawing (found: %s). Pass --epsg.' % (why or 'none'))

src = osr.SpatialReference(); src.ImportFromEPSG(epsg)
dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
for s in (src, dst):
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
tx = osr.CoordinateTransformation(src, dst)
if not src.IsProjected():
    sys.exit('EPSG:%d is not a projected CRS; this script expects metres.' % epsg)

LINE_RE, HIDE_RE, SKIP_RE = re.compile(args.line_layers), re.compile(args.hidden_layers), re.compile(args.skip_layers)
JOIN_RE = re.compile(args.join_layers) if args.join_layers else None

CATEGORIES = [
    ('Boundaries & zones', r'(?i)border|boundar|aoi|zone|area|block|field|plot|farm|estate|nursery|parcel'),
    ('Water', r'(?i)river|stream|drain|water|reservoir|dam|canal|lake|flood|swamp'),
    ('Terrain', r'(?i)contour|elev|spot|level|height'),
    ('Infrastructure', r'(?i)road|pipe|grp|main|valve|pump|outlet|intake|irr|building|factory|camp|room|hydraulic|gader|track'),
]
KEYWORD_COLOURS = [  # RGB hex by layer keyword, used when the CAD colour is black/white
    (r'(?i)river|stream|drain|water|reservoir|flood|canal|lake', '3399ff'),
    (r'(?i)road|track', 'ff3333'),
    (r'(?i)contour|elev', 'a0522d'),
    (r'(?i)aoi|project border|farm boundar|estate', 'ffcc00'),
]


def category(layer):
    for name, rx in CATEGORIES:
        if re.search(rx, layer):
            return name
    return 'Other'


def layer_colour(f, layer):
    for rx, c in KEYWORD_COLOURS:
        if re.search(rx, layer):
            return c
    m = re.search(r'c:#([0-9a-fA-F]{6})', f.GetStyleString() or '')
    c = m.group(1).lower() if m else None
    if c in (None, '000000', 'ffffff'):
        r, g, b = colorsys.hsv_to_rgb((zlib.crc32(layer.encode()) % 360) / 360, 0.75, 0.95)
        c = '%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))
    return c


def kcol(rgb, alpha):  # KML colours are aabbggrr
    return '%02x%s%s%s' % (alpha, rgb[4:6], rgb[2:4], rgb[0:2])


def clean_text(t):
    if not t:
        return ''
    t = re.sub(r'\\[A-Za-z][^;\\{}]*;', '', t).replace('\\P', ' ').replace('{', '').replace('}', '')
    return re.sub(r'\s+', ' ', t).strip()


def flat_lines(g):
    g = g.GetLinearGeometry() if g.HasCurveGeometry() else g
    t = ogr.GT_Flatten(g.GetGeometryType())
    if t == ogr.wkbLineString:
        return [g.Clone()]
    if t == ogr.wkbPolygon:
        return [ogr.ForceToLineString(g.GetGeometryRef(i)) for i in range(g.GetGeometryCount())]
    out = []
    for i in range(g.GetGeometryCount()):
        out += flat_lines(g.GetGeometryRef(i))
    return out


# ---- read --------------------------------------------------------------------------------
feats = collections.defaultdict(list)   # layer -> [dict(kind, geom (source CRS), name, color, attrs)]
skipped = collections.Counter()
notes = []
ds = ogr.Open(args.dxf)
if ds is None:
    sys.exit('GDAL cannot open %s' % args.dxf)
rows = []
for f in ds.GetLayerByName('entities'):
    g = f.GetGeometryRef()
    rows.append((f, g.Clone() if g else None))
pts = sorted(((g.GetEnvelope()[0] + g.GetEnvelope()[1]) / 2, (g.GetEnvelope()[2] + g.GetEnvelope()[3]) / 2)
             for f, g in rows if g and not g.IsEmpty() and not f.GetField('PaperSpace'))
cx, cy = pts[len(pts) // 2][0], sorted(p[1] for p in pts)[len(pts) // 2]

for f, g in rows:
    layer = f.GetField('Layer') or '0'
    sub = (f.GetField('SubClasses') or '').split(':')[-1]
    if f.GetField('PaperSpace'):
        skipped['paper space (title block, legend, logo)'] += 1; continue
    if SKIP_RE.search(layer):
        skipped['skipped layer %s' % layer] += 1; continue
    if g is None or g.IsEmpty():
        skipped['empty geometry: %s on %s' % (sub or 'entity', layer)] += 1; continue
    x0, x1, y0, y1 = g.GetEnvelope()
    if max(abs(x0 - cx), abs(x1 - cx), abs(y0 - cy), abs(y1 - cy)) > args.far:
        skipped['far from the map (detail drawn elsewhere): %s on %s' % (sub, layer)] += 1; continue
    if 'Dimension' in sub or 'Leader' in sub:
        skipped['dimension/leader annotation'] += 1; continue
    color = layer_colour(f, layer)
    attrs = {'Layer': layer, 'Entity': sub.replace('AcDb', ''), 'Handle': f.GetField('EntityHandle')}
    block = f.GetField('BlockName')
    if block:
        attrs['Block'] = block
        anon = block.startswith(('*', 'symbolLayer', 'i__')) or '$' in block
        feats[layer].append(dict(kind='symbol', geom=g.Clone(), name=layer if anon else block.rstrip('_'),
                                 color=color, attrs=attrs))
        continue
    text = clean_text(f.GetField('Text'))
    gt = ogr.GT_Flatten(g.GetGeometryType())
    if gt == ogr.wkbPoint:
        if not text or text in ('SOLID', 'ANSI31'):
            skipped['point without text on %s' % layer] += 1; continue
        feats[layer].append(dict(kind='label', geom=g.Clone(), name=text, color=color, attrs=attrs))
        continue
    if 'Hatch' in sub or 'Trace' in sub or 'Solid' in sub:
        attrs['Fill'] = text or 'SOLID'
        polys = [g] if gt == ogr.wkbPolygon else [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
        for p in polys:
            if p is not None and ogr.GT_Flatten(p.GetGeometryType()) == ogr.wkbPolygon:
                feats[layer].append(dict(kind='fill', geom=p.Clone(), name=None, color=color, attrs=attrs))
        continue
    for ln in flat_lines(g):
        ln.FlattenTo2D()
        n = ln.GetPointCount()
        closed = n >= 4 and ln.GetPoint_2D(0) == ln.GetPoint_2D(n - 1)
        if closed and not LINE_RE.search(layer):
            ring = ogr.Geometry(ogr.wkbLinearRing)
            for i in range(n):
                ring.AddPoint_2D(*ln.GetPoint_2D(i))
            poly = ogr.Geometry(ogr.wkbPolygon); poly.AddGeometry(ring)
            feats[layer].append(dict(kind='polygon', geom=poly, name=None, color=color, attrs=attrs))
        elif n >= 2:
            feats[layer].append(dict(kind='line', geom=ln, name=None, color=color, attrs=dict(attrs, Closed=str(closed))))

# ---- clean-up ------------------------------------------------------------------------------
allenv = [d['geom'].GetEnvelope() for lst in feats.values() for d in lst]
ext_area = (max(e[1] for e in allenv) - min(e[0] for e in allenv)) * (max(e[3] for e in allenv) - min(e[2] for e in allenv))
for layer, lst in feats.items():
    seen, keep = set(), []
    for d in lst:
        g = d['geom']
        # sheet frame: a plain rectangle around most of the map
        if d['kind'] == 'polygon' and g.GetGeometryRef(0).GetPointCount() == 5:
            x0, x1, y0, y1 = g.GetEnvelope()
            if (x1 - x0) * (y1 - y0) > 0.5 * ext_area and abs(g.GetArea() - (x1 - x0) * (y1 - y0)) < 1:
                skipped['drawing sheet frame (rectangle around the map) on %s' % layer] += 1; continue
        key = (d['kind'], d['name'], re.sub(r'(\d+\.\d)\d*', r'\1', g.ExportToWkt()))
        if key in seen:
            skipped['exact duplicate drawn twice on %s' % layer] += 1; continue
        seen.add(key); keep.append(d)
    # closed outline that is exactly its own hatch boundary: keep only the fill
    fills = [d['geom'].GetEnvelope() for d in keep if d['kind'] == 'fill']
    lst[:] = [d for d in keep if not (d['kind'] == 'polygon' and any(
        all(abs(a - b) < 1.0 for a, b in zip(d['geom'].GetEnvelope(), e)) for e in fills))]
    if len(lst) < len(keep):
        skipped['outline duplicated by its own hatch (fill kept) on %s' % layer] += len(keep) - len(lst)
    # open segments that together form one ring
    if JOIN_RE and JOIN_RE.search(layer):
        opens = [d for d in lst if d['kind'] == 'line' and d['geom'].Length() > args.snap]
        coll = ogr.Geometry(ogr.wkbGeometryCollection)
        for d in opens:
            coll.AddGeometry(d['geom'])
        poly = ogr.BuildPolygonFromEdges(coll, 0, 0, args.snap) if opens else None
        if poly is not None and poly.GetGeometryRef(0) is not None:
            poly.CloseRings()  # the builder snaps the last gap but may leave the ring unclosed
            total = sum(d['geom'].Length() for d in opens)
            if poly.GetArea() > 1e4 and abs(poly.GetGeometryRef(0).Length() - total) < args.snap * len(opens):
                lst[:] = [d for d in lst if d['kind'] != 'line']
                lst.append(dict(kind='polygon', geom=poly, name=layer, color=opens[0]['color'],
                                attrs={'Layer': layer, 'Entity': 'joined from %d open polylines' % len(opens)}))
                notes.append('%s: %d open polylines joined into one polygon (%.0f ha, gaps up to %.0f m snapped)'
                             % (layer, len(opens), poly.GetArea() / 1e4, args.snap))
                continue
        notes.append('%s: could not be joined into one ring; left as lines' % layer)

# polygon names from a single label of the same layer (or a *name* layer) inside it
labels = [(d['geom'], d['name'], l) for l, lst in feats.items() for d in lst
          if d['kind'] == 'label' and not HIDE_RE.search(l)]
for layer, lst in feats.items():
    for i, d in enumerate(lst, 1):
        g = d['geom']
        if d['kind'] in ('polygon', 'fill'):
            if not d['name']:
                inside = [n for p, n, l in labels if (l == layer or re.search(r'(?i)name', l))
                          and len(n) > 1 and g.Contains(p)]
                if len(inside) == 1:
                    d['name'] = inside[0]
            d['attrs']['Area (ha)'] = '%.2f' % (g.GetArea() / 1e4)
        elif d['kind'] == 'line':
            d['attrs']['Length (m)'] = '%.0f' % g.Length()
        d['name'] = d['name'] or '%s %d' % (layer, i)

# ---- geometry out ---------------------------------------------------------------------------
repaired = collections.Counter()


def prepare(d, layer):
    """Simplify in metres, repair invalid polygons, reproject."""
    g = d['geom'].Clone()
    tol = args.simplify_hidden if HIDE_RE.search(layer) else args.simplify
    if tol and d['kind'] in ('polygon', 'fill', 'line'):
        g = g.SimplifyPreserveTopology(tol)
    if d['kind'] in ('polygon', 'fill') and not g.IsValid():
        repaired[layer] += 1
        v = g.MakeValid()
        if v is not None:  # keep the largest polygon; repair slivers are a few m2
            parts = [v] if ogr.GT_Flatten(v.GetGeometryType()) == ogr.wkbPolygon else \
                [v.GetGeometryRef(i) for i in range(v.GetGeometryCount())]
            parts = [q for q in parts if ogr.GT_Flatten(q.GetGeometryType()) == ogr.wkbPolygon]
            if parts:
                g = max(parts, key=lambda q: q.GetArea()).Clone()
    g.AssignSpatialReference(src)
    g.Transform(tx)
    return g


def coords(g):
    return ' '.join('%.7f,%.7f' % (g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount()))


def geom_kml(g):
    t = ogr.GT_Flatten(g.GetGeometryType())
    if t == ogr.wkbPoint:
        return '<Point><coordinates>%.7f,%.7f</coordinates></Point>' % (g.GetX(), g.GetY())
    if t == ogr.wkbLineString:
        return '<LineString><tessellate>1</tessellate><coordinates>%s</coordinates></LineString>' % coords(g) \
            if g.GetPointCount() >= 2 else ''
    if t == ogr.wkbPolygon:
        rings = [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
        if not rings or rings[0].GetPointCount() < 4:
            return ''
        s = '<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>%s</coordinates></LinearRing></outerBoundaryIs>' % coords(rings[0])
        for r in rings[1:]:
            if r.GetPointCount() >= 4:
                s += '<innerBoundaryIs><LinearRing><coordinates>%s</coordinates></LinearRing></innerBoundaryIs>' % coords(r)
        return s + '</Polygon>'
    parts = [p for p in (geom_kml(g.GetGeometryRef(i)) for i in range(g.GetGeometryCount())) if p]
    return '' if not parts else parts[0] if len(parts) == 1 else '<MultiGeometry>%s</MultiGeometry>' % ''.join(parts)


styles = {}


def style_id(kind, color, hidden):
    key = (kind, color, hidden)
    if key not in styles:
        if kind in ('polygon', 'fill'):
            body = '<LineStyle><color>%s</color><width>2</width></LineStyle><PolyStyle><color>%s</color></PolyStyle>' % (
                kcol(color, 0xff), kcol(color, 0x59 if kind == 'fill' else 0x26))
        elif kind == 'line':
            body = '<LineStyle><color>%s</color><width>%s</width></LineStyle>' % (kcol(color, 0xff), '1' if hidden else '2.5')
        elif kind == 'symbol':
            body = ('<IconStyle><color>%s</color><scale>0.7</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>'
                    '<LabelStyle><scale>0</scale></LabelStyle>') % kcol(color, 0xff)
        else:
            body = '<IconStyle><scale>0</scale></IconStyle><LabelStyle><color>%s</color><scale>%s</scale></LabelStyle>' % (
                kcol(color, 0xff), '0.6' if hidden else '0.9')
        styles[key] = ('s%d' % len(styles), body)
    return styles[key][0]


KIND_LABEL = {'polygon': 'Polygons', 'fill': 'Filled areas', 'line': 'Lines', 'symbol': 'Symbols', 'label': 'Labels'}
counts, cat_folders = {}, collections.defaultdict(list)
lons, lats, vertices = [], [], 0
for layer in sorted(feats, key=str.lower):
    if not feats[layer]:
        continue
    hidden = bool(HIDE_RE.search(layer))
    by_kind = collections.defaultdict(list)
    for d in feats[layer]:
        g = prepare(d, layer)
        gk = geom_kml(g)
        if not gk:
            skipped['degenerate after reprojection on %s' % layer] += 1; continue
        x0, x1, y0, y1 = g.GetEnvelope(); lons += [x0, x1]; lats += [y0, y1]
        vertices += gk.count(',')
        ext = ''.join('<Data name="%s"><value>%s</value></Data>' % (escape(k), escape(str(v)))
                      for k, v in d['attrs'].items() if v is not None)
        # KML schema order: name, visibility, styleUrl, ExtendedData, geometry
        by_kind[d['kind']].append('<Placemark><name>%s</name>%s<styleUrl>#%s</styleUrl><ExtendedData>%s</ExtendedData>%s</Placemark>' % (
            escape(d['name']), '<visibility>0</visibility>' if hidden else '', style_id(d['kind'], d['color'], hidden), ext, gk))
    counts[layer] = {KIND_LABEL[k]: len(v) for k, v in by_kind.items()}
    vis = '0' if hidden else '1'
    kinds = [k for k in KIND_LABEL if k in by_kind]
    inner = ''.join(by_kind[kinds[0]]) if len(kinds) == 1 else ''.join(
        '<Folder><name>%s (%d)</name><visibility>%s</visibility>%s</Folder>' % (KIND_LABEL[k], len(by_kind[k]), vis, ''.join(by_kind[k]))
        for k in kinds)
    cat_folders[category(layer)].append('<Folder><name>%s</name><visibility>%s</visibility>%s</Folder>' % (escape(layer), vis, inner))

name = args.name or re.sub(r'\.kmz$', '', args.kmz.replace('\\', '/').split('/')[-1], flags=re.I)
order = [c for c, _ in CATEGORIES] + ['Other']
body = ''.join('<Folder><name>%s</name><open>1</open>%s</Folder>' % (escape(c),''.join(cat_folders[c])) for c in order if cat_folders[c])
lookat = ('<LookAt><longitude>%.5f</longitude><latitude>%.5f</latitude><altitude>0</altitude><range>%d</range>'
          '<tilt>0</tilt><heading>0</heading><altitudeMode>clampToGround</altitudeMode></LookAt>') % (
    (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2, max(2000, int((max(lats) - min(lats)) * 111000 * 1.6)))
kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
       '<name>%s</name><open>1</open><description>%s</description>%s%s%s</Document></kml>') % (
    escape(name), escape('Converted from CAD. Source CRS EPSG:%d (%s).' % (epsg, why)), lookat,
    ''.join('<Style id="%s">%s</Style>' % v for v in styles.values()), body)
with zipfile.ZipFile(args.kmz, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('doc.kml', kml)   # a KMZ is just a zip whose main file is doc.kml
if args.kml:
    open(re.sub(r'\.kmz$', '', args.kmz, flags=re.I) + '.kml', 'w', encoding='utf-8').write(kml)

report = {'source_crs': 'EPSG:%d (%s)' % (epsg, why), 'counts': counts, 'skipped': dict(skipped), 'notes': notes,
          'repaired_polygons': dict(repaired), 'bbox_wgs84': [round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5)],
          'placemarks': sum(sum(c.values()) for c in counts.values()), 'vertices': vertices}
if vertices > 250000 or report['placemarks'] > 10000:
    report['WARNING'] = 'over Google Earth map-features import limits (250k vertices / 10k features): raise --simplify or split layers'
print(json.dumps(report, indent=1))
