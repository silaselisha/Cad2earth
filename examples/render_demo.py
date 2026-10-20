"""Render docs/demo.png: the DXF as CAD sees it (left) and the KMZ on satellite imagery (right).

    bash scripts/qgis-python.sh examples/render_demo.py examples/sample.dxf examples/sample.kmz docs/demo.png
Imagery: Esri World Imagery (attribution drawn on the image).
"""
import io, math, re, sys, urllib.request, zipfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from PIL import Image
from osgeo import ogr, gdal

ogr.DontUseExceptions(); gdal.PushErrorHandler('CPLQuietErrorHandler')
gdal.SetConfigOption('DXF_INLINE_BLOCKS', 'FALSE')
dxf, kmz, out = sys.argv[1:4]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 6.2), dpi=110)
fig.patch.set_facecolor('#111418')

# ---- left: raw DXF, CAD style ----------------------------------------------------------------
a1.set_facecolor('#1e2227')
ds = ogr.Open(dxf)
for f in ds.GetLayerByName('entities'):
    g = f.GetGeometryRef()
    m = re.search(r'c:#([0-9a-fA-F]{6})', f.GetStyleString() or '')
    col = '#' + m.group(1) if m and m.group(1).lower() not in ('000000',) else '#dddddd'
    if g.GetGeometryName() == 'POINT':
        a1.text(g.GetX(), g.GetY(), f.GetField('Text') or '', color=col, fontsize=7, ha='center', va='center')
        continue
    for i in range(max(1, g.GetGeometryCount())):
        p = g if g.GetGeometryCount() == 0 else g.GetGeometryRef(i)
        xs = [p.GetX(k) for k in range(p.GetPointCount())]
        ys = [p.GetY(k) for k in range(p.GetPointCount())]
        a1.plot(xs, ys, color=col, lw=0.9)
a1.set_aspect('equal'); a1.tick_params(colors='#8a9099', labelsize=7); a1.ticklabel_format(useOffset=False, style='plain')
for s in a1.spines.values():
    s.set_color('#3a3f46')
a1.set_title('sample.dxf  (CAD, UTM metres)', color='#e8eaed', fontsize=11)

# ---- right: KMZ on imagery (Web Mercator) ----------------------------------------------------
kml = zipfile.ZipFile(kmz).read('doc.kml').decode()


def merc(lon, lat):
    x = math.radians(lon) * 6378137
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137
    return x, y


placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', kml, re.S)
styles = dict(re.findall(r'<Style id="(s\d+)">(.*?)</Style>', kml, re.S))
lons, lats = [], []
items = []
for pm in placemarks:
    hidden = '<visibility>0</visibility>' in pm
    name = re.search(r'<name>(.*?)</name>', pm).group(1)
    st = styles.get(re.search(r'#(s\d+)', pm).group(1), '')
    lc = re.search(r'<LineStyle><color>(\w{8})', st)
    col = '#%s%s%s' % (lc.group(1)[6:8], lc.group(1)[4:6], lc.group(1)[2:4]) if lc else '#ffffff'
    for kind, c in re.findall(r'<(LineString|LinearRing|Point)>.*?<coordinates>([^<]*)</coordinates>', pm, re.S):
        pts = [tuple(map(float, t.split(',')[:2])) for t in c.split()]
        lons += [p[0] for p in pts]; lats += [p[1] for p in pts]
        items.append((kind, [merc(*p) for p in pts], col, name, hidden, 'outerBoundaryIs' in pm))

z = 14
def tile(lon, lat):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

pad = 0.006
tx0, ty0 = tile(min(lons) - pad, max(lats) + pad)
tx1, ty1 = tile(max(lons) + pad, min(lats) - pad)
mosaic = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        url = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%d/%d/%d' % (z, ty, tx)
        req = urllib.request.Request(url, headers={'User-Agent': 'Cad2earth demo renderer'})
        mosaic.paste(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert('RGB'),
                     ((tx - tx0) * 256, (ty - ty0) * 256))

def tile_merc(tx, ty):
    n = 2 ** z
    lon = tx / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    return merc(lon, lat)

(x0, y1), (x1, y0) = tile_merc(tx0, ty0), tile_merc(tx1 + 1, ty1 + 1)
a2.imshow(mosaic, extent=(x0, x1, y0, y1), zorder=0)
for kind, pts, col, name, hidden, is_poly in items:
    if hidden:
        continue
    if kind == 'Point':
        a2.text(pts[0][0], pts[0][1], name, color='white', fontsize=7, ha='center', va='center', zorder=4,
                fontweight='bold')
    elif kind == 'LinearRing':
        a2.add_patch(MplPolygon(pts, closed=True, facecolor=col + '30', edgecolor=col, lw=1.6, zorder=2))
    else:
        a2.plot([p[0] for p in pts], [p[1] for p in pts], color=col, lw=2, zorder=3)
mx0, my0 = merc(min(lons) - pad / 2, min(lats) - pad / 2)
mx1, my1 = merc(max(lons) + pad / 2, max(lats) + pad / 2)
a2.set_xlim(mx0, mx1); a2.set_ylim(my0, my1); a2.set_aspect('equal'); a2.axis('off')
a2.set_title('sample.kmz  (Google Earth, WGS 84)', color='#e8eaed', fontsize=11)
a2.text(0.99, 0.01, 'Imagery: Esri, Maxar, Earthstar Geographics', transform=a2.transAxes, ha='right', va='bottom',
        color='white', fontsize=6, alpha=0.8)
fig.text(0.5, 0.02, 'Cad2earth:  boundary pieces snapped into one polygon, fields named from their labels, '
         'sheet frame dropped, contours hidden by default', ha='center', color='#9aa0a6', fontsize=9)
plt.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(out, facecolor=fig.get_facecolor())
print('wrote', out)
