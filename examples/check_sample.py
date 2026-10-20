"""Assert that examples/sample.kmz is what dxf2kmz.py should produce from examples/sample.dxf (used by CI)."""
import re, sys, zipfile, xml.dom.minidom

kmz = sys.argv[1]
kml = zipfile.ZipFile(kmz).read('doc.kml').decode()
doc = xml.dom.minidom.parseString(kml)                      # well-formed XML
pms = doc.getElementsByTagName('Placemark')
names = [p.getElementsByTagName('name')[0].firstChild.data for p in pms]

assert len(pms) == 35, len(pms)
assert 'FARM BOUNDARY' in names, 'boundary pieces were not joined into one polygon'
assert all('F%02d' % i in names for i in range(1, 13)), 'fields not named from their labels'
assert not doc.getElementsByTagName('MultiGeometry'), 'unexpected MultiGeometry'
assert '<name>0' not in kml, 'sheet frame on layer 0 was not dropped'
contours = re.search(r'<Folder><name>CONTOURS</name><visibility>0</visibility>', kml)
assert contours, 'contours should be hidden by default'
lons = [float(c.split(',')[0]) for c in re.findall(r'(-?\d+\.\d+,-?\d+\.\d+)', kml)]
lats = [float(c.split(',')[1]) for c in re.findall(r'(-?\d+\.\d+,-?\d+\.\d+)', kml)]
assert 35.2 < min(lons) < max(lons) < 35.35 and -0.45 < min(lats) < max(lats) < -0.35, (min(lons), min(lats))
print('ok: %d placemarks, lon %.4f..%.4f, lat %.4f..%.4f' % (len(pms), min(lons), max(lons), min(lats), max(lats)))
