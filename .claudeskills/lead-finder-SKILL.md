---
name: lead-finder
description: "Find wholesale leads automatically — no address needed. Pulls free public distress data (Dallas 311 code-compliance complaints, unregistered rentals), ranks every address in a ZIP, then runs /property-recon on the top leads and adds them to the pipeline. Use when the user says 'find deals', 'find leads', 'find houses', 'run the pipeline', or gives a ZIP code instead of an address."
---

# Lead Finder Skill

The top of the funnel. Every other skill starts from an address; this one
produces the addresses.

```
find_leads.py (free data) → shortlist → /property-recon (top N) → pipeline.md → /deal-stacker
```

---

## SUPPORTED MARKETS

| Market | Data | Scripts |
|--------|------|---------|
| Dallas County, TX (all ZIPs 75xxx in the county) | DCAD appraisal data + County delinquent tax roll (free bulk files) | `pipeline/build_dallas_db.py`, `pipeline/find_leads.py` |
| City of Dallas (extra signal) | Dallas 311 code complaints, daily | built into `find_leads.py` |

For any other market, say so plainly and offer to add one. See
`docs/wholesale-lead-research.md` for the source list and what to add next.

> The older Dallas "Code Violations" dataset (`x9pz-kdq9`) stopped
> updating in July 2018. Do not use it.

---

## INPUTS

| Input | Required | Default |
|-------|----------|---------|
| ZIP code(s) | Yes | Ask. If deals exist, suggest ZIPs already in `deals/market-profiles/` |
| Max appraised value | No | $450,000 |
| How many to recon | No | 5 |

---

## PROCESS

### Step 0 — Make sure the database is fresh

If `data/dallas.sqlite` is missing or its `meta.built` date is more than
7 days old, rebuild it (downloads ~450 MB, about 2 minutes):

```bash
python3 pipeline/build_dallas_db.py
```

### Step 1 — Pull and score leads

```bash
python3 pipeline/find_leads.py <zip> [<zip> ...] --top 25 --max-value 450000
```

Writes `deals/leads/{zip}-{date}.md` (shortlist) and `.csv` (every house
with a signal, including owner name and mailing address for direct mail).

Only single-family homes (DCAD code A11), government owners removed.
Scoring (0–100, signals stack):

| Signal | Points |
|--------|--------|
| Taxes delinquent 1 / 2 / 3+ years | +20 / +28 / +35 |
| Tax suit filed (county is suing — sheriff's sale possible) | +15 |
| Bankruptcy on tax account | +5 |
| On a tax payment plan | −10 |
| Estate / inherited owner ("EST OF", "(INHERIT)") | +25 |
| Absentee (no homestead + mailing address elsewhere) | +15 |
| …and out of state | +10 |
| Owned 20+ / 10+ years (equity proxy) | +10 / +5 |
| Condition poor / fair (DCAD rating) | +15 / +8 |
| 311 code complaints 1 / 2 / 3–4 / 5+ | +5 / +10 / +15 / +20 |
| 311 complaint in last 60 days / case still open | +5 / +5 |
| Unregistered rental (311) | +10 |
| Company-owned (LLC, Inc, LP…) | −15 |

### Step 2 — Recon the top leads

Read the shortlist. Skip any address already in `deals/` with recon less
than 30 days old. For the top N remaining, run `/property-recon` and save
to `deals/{address-slug}/recon.md` per `_system/deal-memory.md`.

Drop a lead (note why in the summary) if recon shows:
- Not a single-family house (apartments, business, church, vacant land the user doesn't want)
- Owner is a government entity, housing authority, or large institutional landlord
- Listed with an agent at or above market value

### Step 3 — Update the pipeline

Append every lead that survives recon to `deals/pipeline.md` (Active Deals
table, Status = `Lead — not contacted`, Notes = lead score + top reason).
Append only — never rewrite existing rows.

### Step 4 — Report

```
LEAD FINDER — Dallas 75241 — 2026-11-07
────────────────────────────────────────
Scanned     4,540 complaints → 2,824 addresses
Shortlisted 15
Recon'd     5
Added       3 to pipeline (2 dropped: 1 apartment, 1 city-owned)

  #  Address                 Lead  Motivation  Why
  1  6112 Singing Hills Dr   95    82          7 complaints, landlord, absentee, 2 yrs tax delinquent
  ...

Next: /deal-stacker to rank, or /conversation-coach for the first call.
```

---

## CONSTRAINTS

- These are distress signals, not confirmed motivated sellers. Say so.
- Never invent recon data to fill a gap. If a lookup needs Chrome or a key
  that isn't available, mark it "not checked" and give the URL.
- Public complaint data names addresses, not people. Don't speculate about
  occupants in reports.
- Respect the city's API: one script run per ZIP per day is plenty.
