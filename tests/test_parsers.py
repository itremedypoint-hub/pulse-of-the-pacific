#!/usr/bin/env python3
"""
Parser + validation tests for the data pipeline. Run: python3 tests/test_parsers.py
CI runs this BEFORE the refresh step; a red test blocks the data commit.
Stdlib only — no installs needed anywhere.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import update_data as U

PASS = FAIL = 0
def ok(name, cond):
    global PASS, FAIL
    if cond: PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")

# ---------------------------------------------------------------- seasonal
oni_txt = """SEAS YR TOTAL ANOM
DJF 1950 24.72 -1.53
JFM 1950 25.17 -1.34
NDJ 2025 26.50 0.80
DJF 2026 26.60 0.90
garbage line that should be ignored
XXX 2026 1 2
"""
r = U.parse_seasonal(oni_txt, anom_col=3)
ok("seasonal: parses 4 valid rows", len(r) == 4)
ok("seasonal: latest value", r[-1]["v"] == 0.9 and r[-1]["s"] == "DJF" and r[-1]["y"] == 2026)
ok("seasonal: season whitelist blocks XXX", all(x["s"] in U.SEASONS for x in r))

roni_txt = "SEAS YR ANOM\nDJF 1950 -1.20\nDJF 2026 0.70\n"
r2 = U.parse_seasonal(roni_txt, anom_col=2)
ok("seasonal: RONI 3-col layout", len(r2) == 2 and r2[-1]["v"] == 0.70)

# ------------------------------------------------------------------- wksst
# THE REGRESSION THAT MATTERS: real Fortran fixed-width glues SST to a
# negative anomaly ('23.4-0.5'); whitespace-splitting drops such lines.
glued = (" Weekly SST and anomalies\n"
         " Week          NINO1+2      NINO3       NINO34       NINO4\n"
         " 03JAN1990     23.4-0.5     25.1-0.3     26.2-0.4     28.1 0.1\n"
         " 10JAN1990     23.6-0.7     25.0-0.5     26.0-0.6     28.0-0.1\n"
         " 17JUN2026     24.0 1.2     26.0 1.5     27.0 1.7     29.0 0.9\n")
w = U.parse_wksst(glued)
ok("wksst: keeps ALL negative-anomaly weeks (glued format)", len(w) == 3)
ok("wksst: first N3.4 anomaly = -0.4", abs(w[0]["v"] - (-0.4)) < 1e-9)
ok("wksst: second N3.4 anomaly = -0.6", abs(w[1]["v"] - (-0.6)) < 1e-9)
ok("wksst: positive week parses too", abs(w[2]["v"] - 1.7) < 1e-9)
ok("wksst: chronological order", w[0]["t"] < w[1]["t"] < w[2]["t"])
junk = " 99ZZZ2020 nonsense\n 03JAN1990 only 1.0 two 2.0\n"
ok("wksst: junk lines ignored", U.parse_wksst(junk) == [])
insane = " 03JAN1990     23.4-0.5     25.1-0.3     55.0 9.9     28.1 0.1\n"
ok("wksst: physically impossible SST rejected", U.parse_wksst(insane) == [])

# --------------------------------------------------------------------- soi
soi_txt = (" YEAR JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC\n"
           " 1951 999.9 1.5 0.9 -0.1 -0.5 -1.0 -1.2 -0.8 -0.6 -0.9 -1.1 -1.0\n"
           " 2026 -0.7 -0.9 -1.0 -0.8 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9\n"
           # a second (standardized) table repeating 2026 — later table must win
           " 2026 -0.6 -0.8 -0.9 -0.7 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9 -999.9\n")
s = U.parse_soi(soi_txt)
jan26 = [x for x in s if x["t"] == round(2026 + 0.5/12, 4)]
ok("soi: dedupes repeated tables (later wins)", len(jan26) == 1 and jan26[0]["v"] == -0.6)
ok("soi: 999.9 header-ish value rejected", all(abs(x["v"]) <= 8 for x in s))
ok("soi: -999.9 missing flags dropped", all(x["v"] > -999 for x in s))

# -------------------------------------------------------------------- heat
heat_txt = (" 1979  1  0.12  0.08  0.15\n"
            " 1979  2  0.10  0.05 -9.99\n"     # missing flag style A
            " 1980  1  0.10  0.05 -99.9\n"     # missing flag style B
            " 2026  5  1.20  1.05  1.35\n")
h = U.parse_heat(heat_txt)
ok("heat: keeps valid rows", len(h) == 2)
ok("heat: -9.99 missing flag rejected", all(abs(x["v"]) <= 8 for x in h))
ok("heat: uses 180W-100W column", abs(h[-1]["v"] - 1.35) < 1e-9)

# ---------------------------------------------------------------- classify
recs = [{"v": x} for x in [0.6]*5 + [0.4] + [-0.6]*4 + [0.0]]
U.classify(recs)
cls = "".join(r["c"] for r in recs)
ok("classify: 5-season warm run => El Nino", cls[:5] == "EEEEE")
ok("classify: 4-season cool run => NOT an event", cls[6:10] == "NNNN")

# --------------------------------------------------------- validation gates
try:
    U.validate_series([{"t": 1, "v": 0}], min_len=5); ok("validate: short series rejected", False)
except ValueError:
    ok("validate: short series rejected", True)
try:
    U.validate_series([{"t": 1, "v": 0}, {"t": 1, "v": 0.1}] * 3, min_len=2)
    ok("validate: duplicate times rejected", False)
except ValueError:
    ok("validate: duplicate times rejected", True)
try:
    U.validate_series([{"t": i, "v": 0} for i in range(10)] + [{"t": 99, "v": 42}], min_len=2)
    ok("validate: insane value rejected", False)
except ValueError:
    ok("validate: insane value rejected", True)
okseries = [{"t": 2000 + i/12, "v": ((-1) ** i) * 1.5} for i in range(24)]
ok("validate: healthy series passes", U.validate_series(okseries, min_len=10) is okseries)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
