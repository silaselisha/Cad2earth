"""Write examples/sample.dxf: a small made-up estate in WGS 84 / UTM 36S (EPSG:32736), metres.

It exercises what dxf2kmz.py handles: a farm boundary drawn as 3 open pieces with ~15 m gaps
(--join-layers), closed field outlines (polygons) with labels inside (polygon names),
contours that must stay lines, a river, a road, and a sheet-frame rectangle that should be dropped.
No GEODATA is embedded, so convert it with --epsg 32736.

    bash scripts/qgis-python.sh examples/make_sample.py examples/sample.dxf
"""
import math, sys
from osgeo import ogr, gdal

ogr.UseExceptions()
out = sys.argv[1] if len(sys.argv) > 1 else 'sample.dxf'
E0, N0 = 752000.0, 9955000.0   # near Kericho, Kenya (~35.27 E, 0.41 S)

ds = ogr.GetDriverByName('DXF').CreateDataSource(out)
lyr = ds.CreateLayer('entities')
lyr.CreateField(ogr.FieldDefn('Layer', ogr.OFTString))


def add(layer, wkt, style=None):
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetField('Layer', layer)
    f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
    if style:
        f.SetStyleString(style)
    lyr.CreateFeature(f)


def line(pts):
    return 'LINESTRING (%s)' % ', '.join('%.2f %.2f' % (E0 + x, N0 + y) for x, y in pts)


def ring(pts):
    pts = list(pts) + [pts[0]]
    return line(pts)


def label(layer, x, y, text, colour='#ffffff'):
    add(layer, 'POINT (%.2f %.2f)' % (E0 + x, N0 + y), 'LABEL(f:"Arial",t:"%s",s:25g,c:%s)' % (text, colour))


# farm boundary: a hexagon in three open pieces whose ends miss by ~15 m
hexagon = [(0, 0), (3200, -400), (4300, 1300), (3600, 3200), (900, 3500), (-500, 1700)]
add('FARM BOUNDARY', line([hexagon[0], hexagon[1], hexagon[2]]), 'PEN(c:#ff0000)')
add('FARM BOUNDARY', line([(4300 + 10, 1300 + 12), hexagon[3], hexagon[4]]), 'PEN(c:#ff0000)')
add('FARM BOUNDARY', line([(900 - 12, 3500 + 9), hexagon[5], (0 - 8, 0 + 13)]), 'PEN(c:#ff0000)')

# fields: 4 x 3 blocks of ~60 ha, each with its name inside
n = 0
for r in range(3):
    for c in range(4):
        n += 1
        x0, y0 = 500 + c * 820, 500 + r * 820
        add('FIELDS', ring([(x0, y0), (x0 + 760, y0), (x0 + 760, y0 + 760), (x0, y0 + 760)]), 'PEN(c:#00ff00)')
        label('FIELDS', x0 + 300, y0 + 360, 'F%02d' % n)

# river along the west side, road along the south
add('RIVER', line([(-700 + 150 * math.sin(i * 0.9), -600 + i * 330)
                   for i in range(16)]), 'PEN(c:#0000ff)')
add('ROADS', line([(-800, -250), (1200, -350), (2600, -520), (4800, -700)]), 'PEN(c:#ff8000)')

# contours: closed loops that must stay lines (and be hidden by default)
for k, rad in enumerate((400, 650, 900)):
    add('CONTOURS', ring([(2200 + rad * math.cos(t / 24 * 2 * math.pi), 1600 + 0.7 * rad * math.sin(t / 24 * 2 * math.pi))
                          for t in range(24)]), 'PEN(c:#a0522d)')
    label('CONTOURS', 2200, 1600 - 0.7 * rad, '%d' % (1950 + 10 * k), '#a0522d')

# pump house and the drawing's sheet frame (frame should be dropped)
add('PUMP HOUSE', ring([(-560, 1500), (-520, 1500), (-520, 1530), (-560, 1530)]), 'PEN(c:#ff00ff)')
label('PUMP HOUSE', -540, 1560, 'Pump house')
add('0', ring([(-1500, -1200), (5200, -1200), (5200, 4300), (-1500, 4300)]))
ds = None
print('wrote', out)
