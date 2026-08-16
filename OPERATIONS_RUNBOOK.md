# Operations Runbook — Pulse of the Pacific

How to keep the site healthy with ~2 minutes of attention per week, and exactly what to
do when something breaks. Written for whoever is on support — no prior context assumed
beyond having deployed per `DEPLOYMENT_GUIDE.md`.

---

## 1. The routine (weekly, ~2 minutes)

1. Open **`https://YOUR-SITE/admin.html`**.
2. Read the banner:
   - **Green — "All systems normal"**: you're done.
   - **Amber — "Degraded but serving"** or **"Pipeline has not run yet"**: read §3.
   - **Red — "CRITICAL: data/oni.json could not be loaded"**: read §4.1 (site-down class).
3. Optional glance: the **Recent pipeline runs** dot strip — a lone amber/red dot after
   greens is a transient NOAA hiccup that self-heals on the next run; a *streak* means §3.

That's the whole routine. The system is designed so that no failure mode blanks the
public site: every refresh keeps last-good data on any error.

## 2. Reading the dashboard

**Source cards** (one per NOAA feed):

| Badge | Meaning | Urgency |
|---|---|---|
| `OK` | Last run fetched, validated, and published this series | none |
| `FAIL` | Last run could not refresh it — **site still serves last-good data** | investigate within days |
| `STALE` | Last *success* is older than 1.5× its expected cadence | investigate within days |
| `UNKNOWN` | Pipeline has never reported (fresh deploy) | run the workflow once |

Each card shows: last success (relative time), expected cadence, record count, latest
value, fetch duration, and — on failure — the exact error string from the pipeline.

**Data integrity** (computed live in your browser on the served `oni.json`):
record volume ≥ 800 · time axis strictly increasing · all values within ±6 °C ·
every labelled event spans ≥ 5 seasons · latest season within ~2.5 months.
Any red here means the *served data* is suspect → §4.2.

**Recent pipeline runs**: last 30 runs; green = 5/5 sources, amber = partial, red = 0/5.

## 3. Playbooks — degraded states

### 3.1 One or more sources `FAIL` with `HTTPError: 403/404/5xx`
NOAA endpoints occasionally move, rate-limit, or have outages.
1. Open the failing card's source URL (each card links it) in your browser.
   - **Page loads fine** → transient block/outage. Do nothing; the Mon/Thu schedule
     retries automatically. Clear after two consecutive failed *scheduled* runs → treat
     as moved (next step).
   - **404 / redirected** → NOAA moved the file. Find the new path from
     <https://www.cpc.ncep.noaa.gov/data/indices/>, then edit the `URLS` dict at the top
     of `scripts/update_data.py`, commit, push, and trigger a manual run (§5).
2. If the file exists but the run fails with a `ValueError` mentioning records/range:
   NOAA changed the *format*. See §4.3.

### 3.2 `STALE` without `FAIL`
The workflow itself isn't running.
1. GitHub repo → **Actions** tab. If runs are missing entirely: GitHub disables cron on
   repos with ~60 days of no activity — press **Run workflow** once and it re-arms; any
   commit also re-arms it.
2. If runs exist but the *commit step* errors with permissions: repo **Settings →
   Actions → General → Workflow permissions → Read and write** (it was reset).

### 3.3 Banner: "Pipeline has not run yet"
Fresh deploy. **Actions → Refresh ENSO data → Run workflow**. Green run + a data commit
(or "No data changes") + this banner turning green on reload = fully live.

## 4. Playbooks — serious states

### 4.1 Red banner / public site blank
The deploy itself is broken (data or assets not serving).
1. `curl -I https://YOUR-SITE/data/oni.json` — expect `200`.
2. `404` → the host's **build output directory** is no longer `public` (someone changed
   project settings). Restore it (DEPLOYMENT_GUIDE Part 4.3) and redeploy.
3. `200` but site broken → check the browser console; if CSP violations appear, someone
   edited HTML to add inline scripts — revert, or move the code into `assets/*.js`
   (inline scripts are forbidden by design; see DEVELOPER_GUIDE §security).

### 4.2 Integrity check red (bad served data)
The last data commit is suspect. Roll it back:
```bash
git log --oneline -- public/data        # find the bad "data: scheduled ENSO refresh" commit
git revert <that-commit-sha>
git push
```
The host redeploys the previous good data in ~1 minute. Then diagnose at leisure: run
`python3 scripts/update_data.py` locally and inspect what NOAA is currently serving.

### 4.3 NOAA changed a file format (`ValueError` from validation)
This is the designed failure mode — validation refused to publish garbage.
1. Download the raw file (URL in the card), eyeball the new layout.
2. Adjust the matching `parse_*` function in `scripts/update_data.py`.
3. **Add a test** reproducing the new format in `tests/test_parsers.py` (the suite gates
   every future run — this is how the format break never recurs silently).
4. `python3 tests/test_parsers.py` locally → green → commit, push, manual run.

## 5. Manual operations

| Task | How |
|---|---|
| Force a data refresh now | GitHub → Actions → *Refresh ENSO data* → Run workflow |
| Run the backend locally | `python3 scripts/update_data.py` (writes into `public/data/`) |
| Run the test suite | `python3 tests/test_parsers.py` |
| Rebuild the offline single-file demo | `python3 scripts/build_standalone.py` → `dist/` |
| Roll back bad data | `git revert` the data commit (§4.2) |
| Change the schedule | Edit the two `cron:` lines in `.github/workflows/update-data.yml` (UTC) |

## 6. Alerting (recommended, 1 minute)

GitHub emails you when a workflow **errors** by default (profile → Settings →
Notifications → Actions). Note: by design the refresh exits 0 even when sources fail
(failures are telemetry, not build errors) — so the email fires for *infrastructure*
breakage (tests red, permissions, git push), while *source* problems surface on the
dashboard. That split is intentional: infrastructure pages you; data degradation waits
for your weekly glance, because the site self-protects with last-good data.

## 7. What this system will never do

- It never serves partially-parsed or out-of-range data (validation gates block the write).
- A failed run never erases good data (writes are per-series and gated).
- The public site never depends on the pipeline being up (embedded baseline + last-good).
- The admin page never exposes anything operable — it is read-only telemetry.
