#!/usr/bin/env python3
"""
update_data.py — the backend of "Pulse of the Pacific".

Run on a schedule by GitHub Actions (.github/workflows/update-data.yml), or by
hand: `python3 scripts/update_data.py`. It fetches the latest official ENSO
indices from NOAA, validates them, writes compact JSON into public/data/, and
records full operational telemetry into public/data/status.json — which the
admin dashboard (public/admin.html) renders.

SERIES (all free, no API keys)
  oni    ONI            monthly   3-month Nino-3.4 SST anomaly (defines ENSO phase)
  roni   Relative ONI   monthly   NOAA's operational index since Feb 2026
  wksst  Weekly N3.4    weekly    freshest surface pulse (Mondays)
  soi    SOI 3-mo       monthly   atmospheric side of the oscillation
  heat   Upper-300m T'  monthly   subsurface "fuel gauge" (180W-100W)

SECURITY / RESILIENCE MODEL
  * Fixed HTTPS allowlist of NOAA URLs — nothing user-supplied is ever fetched.
  * Response size hard cap (5 MB) and connect timeout; 2 retries w/ backoff.
  * Every parsed series passes VALIDATION GATES (min records, value ranges,
    duplicate/monotonic time checks) before it may overwrite last-good JSON.
  * Any failure keeps the previous file, is logged to status.json, and the
    process still exits 0 — a bad NOAA day can never blank the site.
  * Stdlib only: zero third-party Python dependencies to supply-chain-audit.
"""
import json, sys, os, re, time, datetime, traceback, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "..", "public", "data")
os.makedirs(OUT, exist_ok=True)

SEASONS = ["DJF","JFM","FMA","MAM","AMJ","MJJ","JJA","JAS","ASO","SON","OND","NDJ"]
MONTHS  = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
UA = {"User-Agent": "PulseOfThePacific/2.0 (scheduled data refresh)"}
MAX_BYTES = 5_000_000
TIMEOUT_S = 30
RETRIES   = 2          # additional attempts after the first
BACKOFF_S = (1, 4)

# The complete, fixed allowlist of what this backend will ever fetch.
URLS = {
    "oni":   "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "roni":  "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
    "wksst": "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for",
    "soi":   "https://www.cpc.ncep.noaa.gov/data/indices/soi.3m.txt",
    "heat":  "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt",
}
# Expected refresh cadence in days (admin page flags STALE past 1.5x this).
CADENCE_DAYS = {"oni":35, "roni":35, "wksst":9, "soi":35, "heat":40}

# ------------------------------------------------------------------ utilities
def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def fetch(url):
    """GET with timeout, size cap, and retry/backoff. Returns decoded text."""
    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                if getattr(r, "status", 200) != 200:
                    raise urllib.error.HTTPError(url, r.status, "non-200", r.headers, None)
                data = r.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError(f"response exceeds {MAX_BYTES} byte cap")
                return data.decode("utf-8", "replace")
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S)-1)])
    raise last_err

def load_json(name):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        try:
            with open(p) as f: return json.load(f)
        except Exception:
            return None
    return None

def write_json(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))

def classify(recs):
    """Official event rule: anomaly beyond +/-0.5 C for >=5 consecutive
    overlapping 3-month seasons => El Nino (E) / La Nina (L), else Neutral."""
    v = [r["v"] for r in recs]; out = ["N"]*len(v); n = len(v); i = 0
    while i < n:
        if v[i] >= 0.5:
            j = i
            while j < n and v[j] >= 0.5: j += 1
            if j - i >= 5:
                for k in range(i, j): out[k] = "E"
            i = j
        elif v[i] <= -0.5:
            j = i
            while j < n and v[j] <= -0.5: j += 1
            if j - i >= 5:
                for k in range(i, j): out[k] = "L"
            i = j
        else:
            i += 1
    for r, c in zip(recs, out): r["c"] = c
    return recs

# ------------------------------------------------------------------- parsers
def parse_seasonal(txt, anom_col):
    """CPC seasonal rows: SEAS YR [cols...]. Returns [{y,s,m,t,v}]."""
    recs = []
    for line in txt.strip().splitlines():
        p = line.split()
        if len(p) <= anom_col: continue
        seas = p[0]
        if seas not in SEASONS: continue
        try:
            yr = int(p[1]); anom = float(p[anom_col])
        except (ValueError, IndexError):
            continue
        si = SEASONS.index(seas)
        recs.append({"y":yr,"s":seas,"m":si+1,"t":round(yr+(si+0.5)/12,4),"v":anom})
    return recs

_WK_DATE = re.compile(r"^\s*(\d{2})([A-Z]{3})(\d{4})(.*)$")
_FLOAT   = re.compile(r"[-+]?\d+\.\d+")
def parse_wksst(txt):
    """Weekly Nino SST file (wksst9120.for). CRITICAL FORMAT NOTE: this is
    Fortran fixed-width; when an anomaly is negative there is NO SPACE between
    the SST and the anomaly (e.g. '23.4-0.5'). Whitespace-splitting silently
    drops those lines — which is every La Nina week. We therefore regex-extract
    the date, then pull all floats from the remainder:
      [N1+2, N1+2a, N3, N3a, N3.4, N3.4a, N4, N4a]  ->  N3.4 anomaly = index 5.
    Returns [{t,v}] for the last ~520 weeks."""
    out = []
    mon = {m:i for i,m in enumerate(MONTHS)}
    for line in txt.splitlines():
        m = _WK_DATE.match(line)
        if not m: continue
        day, mo3, yr, rest = int(m.group(1)), m.group(2).upper(), int(m.group(3)), m.group(4)
        if mo3 not in mon: continue
        nums = _FLOAT.findall(rest)
        if len(nums) < 8: continue
        try:
            sst34 = float(nums[4]); n34a = float(nums[5])
        except ValueError:
            continue
        # physical sanity: tropical Pacific SST 18..35 C; anomalies within +/-6
        if not (18.0 < sst34 < 35.0) or abs(n34a) > 6.0: continue
        try:
            doy = datetime.date(yr, mon[mo3]+1, day).timetuple().tm_yday
        except ValueError:
            continue
        out.append({"t": round(yr + doy/365.25, 4), "v": n34a})
    out.sort(key=lambda r: r["t"])
    return out[-520:]

def parse_soi(txt):
    """soi.3m.txt: YEAR JAN..DEC matrix, missing = -999.9. Some CPC files carry
    a second (standardized) table with the same shape — dedupe by time, keeping
    the LAST occurrence so the later table wins consistently."""
    by_t = {}
    for line in txt.splitlines():
        p = line.split()
        if len(p) != 13 or not p[0].lstrip("-").isdigit(): continue
        try: yr = int(p[0])
        except ValueError: continue
        if yr < 1950 or yr > 2100: continue
        for mi in range(12):
            try: val = float(p[mi+1])
            except ValueError: continue
            if val <= -999 or abs(val) > 8: continue
            by_t[round(yr+(mi+0.5)/12,4)] = val
    return [{"t":t,"v":v} for t,v in sorted(by_t.items())]

def parse_heat(txt):
    """heat_content_index.txt: YR MON <3 basin anomalies>; use 180W-100W (col 5).
    Missing flags vary (-9.99 / -99.9 / -999): physical upper-300m anomalies
    never exceed ~+/-5 C, so reject |v| > 8."""
    out = []
    for line in txt.splitlines():
        p = line.split()
        if len(p) < 5 or not p[0].isdigit(): continue
        try:
            yr = int(p[0]); mo = int(p[1]); val = float(p[4])
        except (ValueError, IndexError):
            continue
        if not (1 <= mo <= 12) or abs(val) > 8: continue
        out.append({"t": round(yr+(mo-0.5)/12,4), "v": val})
    out.sort(key=lambda r: r["t"])
    return out[-600:]

# ---------------------------------------------------------- validation gates
def validate_series(recs, min_len, vmax=6.0):
    """Gate every series before it may overwrite last-good data."""
    if len(recs) < min_len:
        raise ValueError(f"only {len(recs)} records (< {min_len} required)")
    ts = [r["t"] for r in recs]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError("time axis not strictly increasing (duplicates or disorder)")
    bad = [r for r in recs if abs(r["v"]) > vmax]
    if bad:
        raise ValueError(f"{len(bad)} values outside physical range +/-{vmax} (e.g. {bad[0]})")
    return recs

# ------------------------------------------------------------------ updaters
def _result(ok, **kw):
    d = {"ok": ok}; d.update(kw); return d

def refresh_seasonal(key, name, label, min_len, note):
    t0 = time.time()
    try:
        txt = fetch(URLS[key])
        recs = parse_seasonal(txt, anom_col=3)
        if len(recs) < min_len:                       # RONI layout: SEAS YR ANOM
            recs = parse_seasonal(txt, anom_col=2)
        recs = validate_series(sorted(recs, key=lambda r: r["t"]), min_len)
        recs = classify(recs)
        prev = load_json(name) or {}
        meta = prev.get("meta", {})
        meta.update({"index": label, "source_url": URLS[key], "threshold": 0.5,
                     "seasons": SEASONS, "updated": utcnow(), "note": note})
        write_json(name, {"meta": meta, "records": recs})
        last = recs[-1]
        return _result(True, records=len(recs), latest=f"{last['s']} {last['y']}",
                       value=last["v"], duration_ms=int((time.time()-t0)*1000))
    except Exception as e:
        return _result(False, error=f"{type(e).__name__}: {e}",
                       duration_ms=int((time.time()-t0)*1000))

def refresh_simple(key, name, parser, label, min_len, unit):
    t0 = time.time()
    try:
        recs = validate_series(parser(fetch(URLS[key])), min_len, vmax=8.0)
        write_json(name, {"meta": {"series": label, "source_url": URLS[key],
                                   "unit": unit, "updated": utcnow()},
                          "records": recs})
        last = recs[-1]
        return _result(True, records=len(recs), latest=f"t={last['t']}",
                       value=last["v"], duration_ms=int((time.time()-t0)*1000))
    except Exception as e:
        return _result(False, error=f"{type(e).__name__}: {e}",
                       duration_ms=int((time.time()-t0)*1000))

# --------------------------------------------------- manifest + status files
def update_manifest():
    series = {"oni": True, "events": True, "impacts": True, "roni_compare": True}
    for key, fname in [("roni","roni.json"),("wksst","wksst.json"),
                       ("soi","soi.json"),("heat","heat.json")]:
        series[key] = os.path.exists(os.path.join(OUT, fname))
    write_json("manifest.json",
               {"note": "Maintained by update_data.py; lists available series.",
                "updated": utcnow(), "series": series})
    return series

def update_status(results):
    """public/data/status.json — the admin dashboard's data source."""
    prev = load_json("status.json") or {}
    history = prev.get("history", [])
    fails = [k for k, r in results.items() if not r["ok"]]
    history.append({"ts": utcnow(), "ok": len(results)-len(fails), "fail": fails})
    history = history[-30:]
    sources = {}
    for k, r in results.items():
        entry = dict(r)
        entry["url"] = URLS[k]
        entry["cadence_days"] = CADENCE_DAYS[k]
        if r["ok"]:
            entry["updated"] = utcnow()
        else:
            # keep the last successful stamp so staleness is measurable
            old = (prev.get("sources") or {}).get(k, {})
            if "updated" in old: entry["updated"] = old["updated"]
        sources[k] = entry
    write_json("status.json", {
        "updated": utcnow(),
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "manual"),
        "sources": sources,
        "history": history,
        "note": "Operational telemetry written by scripts/update_data.py; rendered by admin.html.",
    })
    return fails

# ----------------------------------------------------------------------- main
def main():
    print(f"== Pulse of the Pacific data refresh @ {utcnow()} ==")
    results = {
        "oni":   refresh_seasonal("oni",  "oni.json",  "ONI",
                    800, "Live-refreshed from NOAA CPC oni.ascii.txt"),
        "roni":  refresh_seasonal("roni", "roni.json", "RONI",
                    700, "NOAA operational Relative ONI (since Feb 2026)"),
        "wksst": refresh_simple("wksst", "wksst.json", parse_wksst,
                    "Weekly Nino-3.4 SST anomaly", 100, "degC"),
        "soi":   refresh_simple("soi",   "soi.json",   parse_soi,
                    "Southern Oscillation Index (3-mo)", 300, "std"),
        "heat":  refresh_simple("heat",  "heat.json",  parse_heat,
                    "Equatorial Pacific upper-300m heat anomaly", 200, "degC"),
    }
    for k, r in results.items():
        mark = "ok " if r["ok"] else "FAIL"
        detail = (f"{r.get('records','?')} recs, latest {r.get('latest','?')} = {r.get('value','?')}"
                  if r["ok"] else r.get("error",""))
        print(f"  [{mark}] {k:5s} {detail}  ({r['duration_ms']} ms)")
    update_manifest()
    fails = update_status(results)
    print(f"Done. {len(results)-len(fails)}/{len(results)} refreshed."
          + ("" if not fails else f" Failed (kept last-good): {', '.join(fails)}"))
    sys.exit(0)      # never break the workflow; failures live in status.json

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
