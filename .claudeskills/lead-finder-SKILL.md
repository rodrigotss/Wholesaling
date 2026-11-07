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

| Market | Data source | Script |
|--------|-------------|--------|
| Dallas, TX (ZIPs 75xxx inside city limits) | Dallas 311 Service Requests, dataset `d7e7-envw`, updated daily | `pipeline/find_leads.py` |

For any other market, say so plainly and offer to add one. Many cities
publish code violations through Socrata (see the table in
`property-recon-SKILL.md`, Layer 5).

> The older Dallas "Code Violations" dataset (`x9pz-kdq9`) stopped
> updating in July 2018. Do not use it for lead finding.

---

## INPUTS

| Input | Required | Default |
|-------|----------|---------|
| ZIP code(s) | Yes | Ask. If deals exist, suggest ZIPs already in `deals/market-profiles/` |
| Look-back months | No | 12 |
| How many to recon | No | 5 (each recon costs Firecrawl credits) |

---

## PROCESS

### Step 1 — Pull and score leads

```bash
python3 pipeline/find_leads.py <zip> [<zip> ...] --months 12 --top 25
```

Writes `deals/leads/{zip}-{date}.md` (shortlist) and `.csv` (every address).

Scoring (0–100):

| Signal | Points |
|--------|--------|
| Code complaints in window: 1 / 2 / 3–4 / 5–9 / 10+ | 5 / 20 / 30 / 40 / 45 |
| Latest complaint ≤ 60 days / ≤ 180 days | +20 / +10 |
| Any request still open | +15 |
| "Single Family Rental Needs Registration" request (landlord) | +20 |
| Likely apartment/commercial (25+ complaints or unit marker) | −30, removed from shortlist |

The shortlist cutoff is 40. Big commercial corridors (e.g. Simpson Stuart
Rd, Camp Wisdom Rd) can still slip through with 10–24 complaints — Step 2
catches them.

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
