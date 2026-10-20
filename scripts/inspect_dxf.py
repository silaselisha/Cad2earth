"""Inspect a DXF before converting: units, extents, embedded CRS, and geometry per layer.
Run with QGIS Python: bash qgis-python.sh inspect_dxf.py drawing.dxf
"""
import collections, re, sys
from osgeo import ogr, gdal

ogr.DontUseExceptions(); gdal.PushErrorHandler('CPLQuietErrorHandler')
gdal.SetConfigOption('DXF_INLINE_BLOCKS', 'FALSE'); gdal.SetConfigOption('DXF_FEATURE_LIMIT_PER_BLOCK', '-1')
path = sys.argv[1]
txt = open(path, encoding='utf-8', errors='replace').read()
UNITS = {'0': 'unitless', '1': 'inches', '2': 'feet', '4': 'mm', '5': 'cm', '6': 'metres', '7': 'km'}


def header(var):
    m = re.search(r'\n\s*9\s*\n\$%s\s*\n(.*?)\n\s*9\s*\n' % var, txt, re.S)
    return re.findall(r'\n\s*(\d+)\s*\n\s*([^\n]*)', '\n' + m.group(1)) if m else None


ins = header('INSUNITS')
print('INSUNITS:', UNITS.get(ins[0][1].strip(), ins) if ins else 'not set')
print('EXTMIN:', header('EXTMIN'), '\nEXTMAX:', header('EXTMAX'))
print('Embedded CRS (GEODATA):', sorted(set(re.findall(r'ProjectedCoordinateSystem id="([^"]+)"', txt))) or 'none')

ds = ogr.Open(path)
c, bb = collections.Counter(), {}
for f in ds.GetLayerByName('entities'):
    g = f.GetGeometryRef()
    if f.GetField('PaperSpace') or g is None or g.IsEmpty():
        c[('(paper space or empty)', '')] += 1; continue
    layer = f.GetField('Layer'); gt = g.GetGeometryName()
    if gt == 'LINESTRING':
        gt += '/closed' if g.GetPoint_2D(0) == g.GetPoint_2D(g.GetPointCount() - 1) else '/open'
    if f.GetField('BlockName'):
        gt = 'INSERT ' + f.GetField('BlockName')
    c[(layer, gt)] += 1
    x0, x1, y0, y1 = g.GetEnvelope(); o = bb.get(layer, [x0, y0, x1, y1])
    bb[layer] = [min(o[0], x0), min(o[1], y0), max(o[2], x1), max(o[3], y1)]
print('\ncount  layer / geometry')
for (l, gt), n in sorted(c.items()):
    print('%5d  %s / %s' % (n, l, gt))
print('\nlayer extents (spot features far from the rest = details drawn at the origin, sheet frames)')
for l, b in sorted(bb.items()):
    print('  %-40s x %.0f..%.0f  y %.0f..%.0f' % (l, *b[:1], b[2], b[1], b[3]))
