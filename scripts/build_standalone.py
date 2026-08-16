#!/usr/bin/env python3
"""
build_standalone.py — produce dist/el-nino-tracker-standalone.html:
one self-contained file (CSS + JS + ECharts + all data inlined) that opens
from disk with no server and no network. For sharing/demos/archival.
The deployable site in public/ remains the source of truth.

Run: python3 scripts/build_standalone.py
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PUB  = os.path.join(ROOT, "public")
DIST = os.path.join(ROOT, "dist")
os.makedirs(DIST, exist_ok=True)

def read(p):  return open(os.path.join(PUB, p), encoding="utf-8").read()

html = read("index.html")
css  = read("assets/style.css")
appj = read("assets/app.js")
ech  = read("vendor/echarts.min.js")

data = {}
for key, fname in [("oni","oni.json"),("events","events.json"),
                   ("impacts","impacts.json"),("roni_compare","roni_compare.json"),
                   ("manifest","manifest.json")]:
    data[key] = json.load(open(os.path.join(PUB, "data", fname)))
# Standalone has no pipeline: mark optional live series absent so nothing is fetched.
data["manifest"]["series"].update({"roni":False,"wksst":False,"soi":False,"heat":False})

embed = "window.__EMBEDDED__=" + json.dumps(data, separators=(",",":")) + ";"

# 1. inline the stylesheet
html = html.replace('<link rel="stylesheet" href="assets/style.css">',
                    "<style>\n"+css+"\n</style>")
# 2. drop the CSP meta (inline scripts below would violate it; file:// context anyway)
html = re.sub(r'<!-- Content-Security-Policy.*?/>\n', "", html, flags=re.S)
html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*/>\n', "", html)
# 3. replace the two deferred script tags with inlined equivalents (order preserved)
html = html.replace('<script defer src="vendor/echarts.min.js"></script>\n'
                    '<script defer src="assets/app.js"></script>',
                    "<script>\n"+embed+"\n</script>\n"
                    "<script>\n"+ech+"\n</script>\n"
                    "<script>\n"+appj+"\n</script>")
# 4. footer status link points at a page that doesn't exist standalone — neutralize
html = html.replace('<a href="admin.html" style="color:var(--live);text-decoration:none">System status</a>',
                    '<span class="tag">standalone build</span>')

out = os.path.join(DIST, "el-nino-tracker-standalone.html")
open(out, "w", encoding="utf-8").write(html)
print(f"wrote {out}  ({os.path.getsize(out):,} bytes)")
assert "assets/app.js" not in open(out).read(), "external ref leaked"
assert "__EMBEDDED__" in open(out).read()
print("standalone integrity checks passed")
