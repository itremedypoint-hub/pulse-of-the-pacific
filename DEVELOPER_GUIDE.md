# Developer Guide & Handoff — Pulse of the Pacific

Everything a new developer needs to own this project: the architecture and why it's
shaped this way, a guided tour of every module, the security model, testing, and
checklists for the changes you're most likely to make.

---

## 1. Architecture

```
            NOAA CPC (public ASCII files, no CORS, no API keys)
                            │  HTTPS, allowlisted URLs only
                            ▼
   .github/workflows/update-data.yml            ← the schedule (Mon/Thu 16:10 UTC)
       1. tests/test_parsers.py                 ← red tests BLOCK the refresh
       2. scripts/update_data.py                ← THE BACKEND
            fetch (30s timeout, 5MB cap, 2 retries)
            → parse (format-tolerant parsers)
            → VALIDATION GATES (volume, monotonic time, physical range)
            → write public/data/*.json  +  status.json telemetry
       3. commit-if-changed  ──────────────► static host auto-redeploys
                                                    │
                                                    ▼
                    Browser fetches same-origin JSON only
        index.html + assets/app.js   ← the tracker (public)
        admin.html + assets/admin.js ← ops dashboard reading status.json
```

**Why zero servers?** Every classic attack surface — auth, sessions, injection into a
live datastore, unpatched server software — exists only if you run a server. This site
has no secrets, no user data, and no write path reachable from the internet; the only
process with write access runs inside GitHub's infrastructure on a schedule, reading from
a fixed allowlist. Robustness comes from the same shape: the site is fully functional
from its committed baseline even if the pipeline never runs again.

**Data-flow contract:** the browser *never* talks to NOAA (their endpoints have no CORS
headers anyway); the pipeline *never* touches HTML/JS. The interface between backend and
frontend is exactly the JSON files in `public/data/` — schemas in §5.3.

## 2. Repository map (what and why)

| Path | What it is | Why it exists |
|---|---|---|
| `public/index.html` | Tracker markup only | Zero inline scripts → strict CSP possible |
| `public/admin.html` | Ops dashboard markup | The "admin section" — read-only telemetry |
| `public/assets/app.js` | The whole tracker app | One file, seven labeled modules (§4) |
| `public/assets/admin.js` | Dashboard renderer | DOM-built, textContent-only (§6) |
| `public/assets/style.css` | Entire design system | CSS custom properties = the theme |
| `public/vendor/echarts.min.js` | Pinned ECharts 5.5.1 | Vendored: no CDN supply chain |
| `public/_headers` | CSP + security headers | Authoritative on Cloudflare/Netlify |
| `public/data/*.json` | The data interface | §5.3 schemas |
| `scripts/update_data.py` | The backend | §5 |
| `tests/test_parsers.py` | Gate for every refresh | Encodes each past format lesson |
| `scripts/build_standalone.py` | Single-file bundler | Offline demo without forking code |

## 3. Local development

```bash
cd public && python3 -m http.server 8000     # the site
python3 tests/test_parsers.py                # unit gate (stdlib only, instant)
python3 scripts/update_data.py               # real refresh (needs internet)
python3 scripts/build_standalone.py          # dist/ single-file build
node --check public/assets/app.js            # syntax sanity after edits
```
No build step, no framework, no package.json required to *run* anything — that is a
feature; keep it that way unless something forces otherwise.

## 4. Frontend tour (`assets/app.js`, in file order)

1. **Data layer** — `loadJSON` (with the `window.__EMBEDDED__` hook the standalone build
   uses), `bootData` (manifest-driven optional fetches → no 404 noise), `latestPulse`
   (freshest number: weekly if present, else ONI). `parseONIascii`/`tryLiveONI` exist for
   an optional CORS-proxy mode (`PROXY` const) — unused by default, kept deliberately.
2. **Living ocean** — `initOcean`: a coarse cell grid colored by `fieldColor` (warm core
   shifts east with positive ONI — that's Bjerknes, keep it), advected particles, pauses
   on `visibilitychange` and honors `prefers-reduced-motion`.
3. **Status instrument** — `renderStatus`. **INVARIANT: the phase pill derives from ONI
   only** (the official 3-month definition). The weekly value may populate the "freshest
   pulse" cell, relabeled via `#pulseLabel`, with its week date from `fracToDate`. Trend
   is ONI-vs-ONI, twelve seasons apart. Do not "simplify" any of that — it was a real bug.
4. **Timeline** — ECharts bar chart; per-bar diverging color via `visualMap`
   (**not** per-item `itemStyle`, which `large:true` ignores — another past bug). The
   RONI overlay draws real `data/roni.json` when present, else a dashed schematic, and
   `#roniNote` explains which one honestly.
5. **Impact map** — real Natural Earth 110m coastlines pre-projected into a single path
   (`LAND_PATH`, equirectangular, viewBox 1000×500). `lonlatToXY` is the projection —
   markers, the Niño-3.4 box, and the path all assume it; change nothing in isolation.
   Markers are keyboard buttons (`role`, `tabindex`, Enter/Space, `aria-pressed`).
6. **Forecast** — `computeForecast`: damped persistence `climo + (cur−climo)·r₁` with
   AR(1) variance growth `σ√(1−r₁^2k)`, ×1.45 across MAM (spring barrier). Probabilities
   via an erf-based normal CDF around ±0.5. **Honesty rules:** labels say "next month",
   the band is indicative, the disclaimer defers to official outlooks — never remove.
7. **Boot** — defensive `matchMedia`/`IntersectionObserver` checks (jsdom, old webviews),
   scroll reveals, clock.

## 5. Backend tour (`scripts/update_data.py`)

### 5.1 Design rules
Stdlib only · fixed URL allowlist · 30 s timeout, 5 MB cap, 2 retries with backoff ·
per-series validation gates · last-good preservation · always `exit 0` (failures are
telemetry in `status.json`, not build errors — see RUNBOOK §6 for the alerting split).

### 5.2 Parser contracts (each encodes a real NOAA quirk)
- `parse_seasonal` — `SEAS YR …` rows; season whitelist; ONI anomaly col 3, RONI col 2
  (auto-fallback).
- `parse_wksst` — **the big one**: `wksst9120.for` is Fortran fixed-width; a negative
  anomaly glues to its SST (`23.4-0.5`). Whitespace-splitting silently drops every such
  line — i.e. all La Niña weeks. So: regex the date, regex-findall floats, Niño-3.4
  anomaly = index 5, plus SST sanity (18–35 °C). The regression test locks this in.
- `parse_soi` — `YEAR JAN..DEC` matrix; `-999.9` missing; some files repeat a second
  (standardized) table → dedupe by time, later wins.
- `parse_heat` — `YR MON` + three basins; we use 180°W–100°W (col 5); missing flags vary
  (`-9.99`, `-99.9`, `-999`) → reject `|v| > 8` since real anomalies stay within ~±5.

### 5.3 Data schemas (the backend↔frontend interface)
```jsonc
// oni.json / roni.json
{ "meta": { "index","source_url","threshold":0.5,"seasons":[…],"updated","note" },
  "records": [ { "y":2026,"s":"DJF","m":1,"t":2026.0417,"v":0.9,"c":"E|L|N" }, … ] }

// wksst.json / soi.json / heat.json
{ "meta": { "series","source_url","unit","updated" },
  "records": [ { "t":2026.46,"v":1.7 }, … ] }

// manifest.json — which optional series exist (frontend fetches only these)
{ "updated","series": { "oni":true,"roni":false,"wksst":false,"soi":false,"heat":false, … } }

// status.json — telemetry rendered by admin.html
{ "updated","trigger",
  "sources": { "<key>": { "ok",bool, "records","latest","value","duration_ms",
                          "error"?, "updated"?, "cadence_days","url" } },
  "history": [ { "ts","ok":5,"fail":["heat"] }, … ]   // last 30 runs
}
```
`t` is a fractional year with the sample at the month/season **center** — both sides
assume this; never mix conventions.

### 5.4 Adding a new data series (checklist)
1. URL → `URLS` + cadence → `CADENCE_DAYS`. 2. Write `parse_<x>` returning `[{t,v}]`
sorted. 3. Register in `main()` via `refresh_simple`. 4. **Tests first-class:** add
format + edge cases to `tests/test_parsers.py`. 5. Frontend: manifest key in `bootData`,
then use `DATA.<x>`. 6. Admin: one line in `SOURCE_LABELS`. 7. Run suite + one manual
workflow run.

## 6. Security model (threat-informed)

| Threat | Mitigation |
|---|---|
| XSS via injected script | CSP `script-src 'self'`; **zero inline scripts site-wide** (the reason JS lives in `assets/`); admin renders exclusively via `createElement`/`textContent` |
| Clickjacking / embedding | `frame-ancestors 'none'` + `X-Frame-Options: DENY` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| CDN supply-chain | ECharts vendored & pinned; the only third-party requests are Google Fonts (listed in CSP; Appendix C of the deploy guide removes even that) |
| Data poisoning via NOAA | Pipeline validation gates: volume floors, strictly-increasing time, physical range ±6/±8 °C; failures keep last-good and surface in telemetry |
| CI compromise | Actions pinned to major versions; workflow permissions limited to `contents: write`; no secrets exist in the repo at all |
| "Admin" abuse | There is nothing to abuse — read-only telemetry. For privacy, gate `/admin.html` with Cloudflare Access (deploy guide) rather than ever building auth into the site |
| DoS | Static files on a global CDN; nothing to exhaust |

**The standing rule that keeps most of this true: never add an inline `<script>` to any
HTML file.** New code goes in `assets/*.js` or the CSP breaks (visibly, by design).

## 7. Testing (three layers)

1. **Unit** — `python3 tests/test_parsers.py` (23 checks; CI-gating) and
   `node --check` on both JS files.
2. **Browser integration** — Playwright: three viewports asserting zero horizontal
   overflow, correct ONI-derived phase, marker accessibility, admin degraded/healthy
   states, and the standalone file from `file://` (43 checks in the last full run).
3. **Failure drill** — run `scripts/update_data.py` with the network blocked: expect
   5× FAIL in telemetry, untouched data files, exit 0.

Manual pre-release sweep: keyboard-only pass (visible teal focus everywhere), a phone,
and DevTools → Console clean under CSP.

## 8. Performance & accessibility notes

~82 KB HTML+CSS+JS (app) + 1 MB vendored ECharts (cached immutable) + ~68 KB data.
Ocean canvas ~60 fps coarse-grid, pauses when hidden; honors reduced-motion (static
frame, no SVG pulse loops). A11y: skip-link, `aria-label`ed charts, keyboard map
markers with `aria-pressed`, `:focus-visible` rings, semantic landmarks.

## 9. Roadmap (in rough order of value)

1. **Live OISST anomaly raster** under the impact map (pipeline renders a PNG from
   NOAA OISST; map gains a real SST layer).
2. **Heat-content panel** — `heat.json` already flows; chart it as the "fuel gauge"
   that leads the surface by months.
3. **IRI/CPC plume embed** beside the in-house forecast for official probabilities.
4. WebGL wind-particle layer over the tropical Pacific (earth.nullschool-style).
5. Advisory text auto-scrape (the alert cell is editorial today — flagged in code).
