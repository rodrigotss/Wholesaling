#!/usr/bin/env python3
"""
Lead Finder — Dallas County, TX

Ranks every single-family house in a ZIP by stacked motivated-seller
signals from free public data:

  Source                         Signals
  ─────────────────────────────  ───────────────────────────────────────
  Dallas County tax roll (TRW)   years delinquent, amount owed, tax suit
                                 pending, bankruptcy, payment plan
  DCAD appraisal data            estate / inherited owner, absentee owner,
                                 out-of-state owner, years owned (equity
                                 proxy), condition rating, value, beds/baths
  City of Dallas 311 feed        code complaints, open cases, unregistered
                                 rental (city of Dallas ZIPs only)

Run pipeline/build_dallas_db.py first (weekly) to build data/dallas.sqlite.
Without it, this falls back to 311-only mode.

Output (deals/leads/, gitignored):
  {zip}-{date}.csv   every scored house, best first, with owner + mailing
                     address for direct mail
  {zip}-{date}.md    shortlist, ready for /property-recon

Usage:
  python3 pipeline/find_leads.py 75241
  python3 pipeline/find_leads.py 75241 75216 75217 --top 30 --max-value 350000
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "dallas.sqlite"
LEADS_DIR = REPO_ROOT / "deals" / "leads"

DATASET_URL = "https://www.dallasopendata.com/resource/d7e7-envw.json"
CODE_CONCERN = "Code Concern - CCS"
RENTAL_REG = "Single Family Rental Needs Registration - CCS"
MULTI_UNIT_THRESHOLD = 25
UNIT_MARKER = re.compile(r"\b(APT|UNIT|STE|SUITE|BLDG)\b|#")
POOR_CONDITION = {"POOR", "VERY POOR", "UNDESIRABLE"}


# ── City of Dallas 311 ──────────────────────────────────────────────────

def fetch_311(zip_code: str, since: datetime) -> list[dict]:
    types = f"'{CODE_CONCERN}', '{RENTAL_REG}'"
    where = (f"service_request_type in ({types}) "
             f"AND created_date >= '{since.strftime('%Y-%m-%dT%H:%M:%S')}' "
             f"AND address like '%{zip_code}'")
    headers = {"Accept": "application/json"}
    if os.getenv("SOCRATA_APP_TOKEN"):
        headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
    rows, offset, page = [], 0, 50000
    while True:
        params = {"$select": "address, service_request_type, status, created_date",
                  "$where": where, "$limit": page, "$offset": offset}
        req = urllib.request.Request(f"{DATASET_URL}?{urllib.parse.urlencode(params)}", headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = json.load(resp)
        if isinstance(batch, dict) and batch.get("error"):
            raise RuntimeError(batch.get("message"))
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def addr_key(addr: str) -> str:
    return re.sub(r"\s+", " ", addr.upper()).strip(" ,")


def clean_311_address(raw: str, zip_code: str) -> str:
    return addr_key(re.sub(rf",?\s*DALLAS,?\s*TX,?\s*{zip_code}$", "", raw.upper().strip()))


def summarize_311(rows: list[dict], zip_code: str) -> dict:
    by_addr = defaultdict(lambda: {"complaints": 0, "rental_reg": 0, "open": 0, "last": None})
    for r in rows:
        if not r.get("address"):
            continue
        info = by_addr[clean_311_address(r["address"], zip_code)]
        created = datetime.fromisoformat(r["created_date"][:19]).replace(tzinfo=timezone.utc)
        if r["service_request_type"] == CODE_CONCERN:
            info["complaints"] += 1
        else:
            info["rental_reg"] += 1
        if (r.get("status") or "").lower() != "closed":
            info["open"] += 1
        if not info["last"] or created > info["last"]:
            info["last"] = created
    return by_addr


# ── Scoring ─────────────────────────────────────────────────────────────

def score(p: dict, c311: dict | None, now: datetime) -> tuple[int, list[str]]:
    s, why = 0, []

    # Tax distress
    yrs = p.get("years_delinquent") or 0
    if yrs:
        s += 35 if yrs >= 3 else 28 if yrs == 2 else 20
        why.append(f"taxes {yrs}yr delinquent (${p['amount_due']:,.0f})")
        if p.get("tax_suit"):
            s += 15
            why.append("tax suit filed")
        if p.get("bankruptcy"):
            s += 5
            why.append("bankruptcy")
        if p.get("payment_plan"):
            s -= 10
            why.append("on payment plan")

    # Owner situation
    if p.get("estate_owner") or p.get("inherited"):
        s += 25
        why.append("estate/inherited")
    if p.get("absentee"):
        s += 15
        why.append("absentee owner")
        if p.get("out_of_state"):
            s += 10
            why.append(f"out of state ({p['mail_state']})")
    yo = p.get("years_owned")
    if yo and yo >= 20:
        s += 10
        why.append(f"owned {yo:.0f}yrs")
    elif yo and yo >= 10:
        s += 5
        why.append(f"owned {yo:.0f}yrs")

    # Property distress
    cond = (p.get("condition") or "").upper()
    if cond in POOR_CONDITION:
        s += 15
        why.append(f"condition {cond.lower()}")
    elif cond == "FAIR":
        s += 8
        why.append("condition fair")

    if c311:
        n = c311["complaints"]
        if n:
            s += 20 if n >= 5 else 15 if n >= 3 else 10 if n == 2 else 5
            why.append(f"{n} code complaints")
            if c311["last"] and (now - c311["last"]).days <= 60:
                s += 5
            if c311["open"]:
                s += 5
                why.append("open code case")
        if c311["rental_reg"]:
            s += 10
            why.append("unregistered rental")

    if p.get("corporate_owner"):
        s -= 15
        why.append("company-owned")

    return max(0, min(100, s)), why


# ── Lead building ───────────────────────────────────────────────────────

def leads_from_db(zip_code: str, c311: dict, max_value: float, now: datetime) -> list[dict]:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT p.*, t.years_delinquent, t.amount_due, t.tax_suit, t.bankruptcy,
               t.payment_plan, t.deferral
        FROM parcels p LEFT JOIN tax_delinquent t USING (account)
        WHERE p.zip = ? AND p.sptd_code = 'A11' AND p.government_owner = 0
    """, (zip_code,)).fetchall()

    leads = []
    for r in rows:
        p = dict(r)
        if max_value and (p["market_value"] or 0) > max_value:
            continue
        p["absentee"] = int(not p["homestead"] and p["mail_differs"])
        info = c311.get(addr_key(p["address"]))
        sc, why = score(p, info, now)
        if not why or sc == 0:
            continue
        leads.append({
            "score": sc,
            "address": p["address"] + (f" {p['unit']}" if p["unit"] else ""),
            "city": p["city"].split(" (")[0].title(),
            "zip": zip_code,
            "why": "; ".join(why),
            "owner": p["owner"],
            "mail_address": p["mail_address"],
            "mail_city": p["mail_city"],
            "mail_state": p["mail_state"],
            "mail_zip": p["mail_zip"],
            "market_value": int(p["market_value"] or 0),
            "beds": p["beds"], "baths": p["baths"], "sqft": p["living_sqft"],
            "year_built": p["year_built"], "condition": p["condition"],
            "years_owned": p["years_owned"],
            "tax_years_delinquent": p["years_delinquent"] or 0,
            "tax_amount_due": p["amount_due"] or 0,
            "tax_suit": "yes" if p["tax_suit"] else "",
            "code_complaints": info["complaints"] if info else 0,
            "absentee": "yes" if p["absentee"] else "",
            "estate": "yes" if (p["estate_owner"] or p["inherited"]) else "",
            "dcad_account": p["account"],
            "dcad_url": f"https://www.dallascad.org/AcctDetail.aspx?ID={p['account']}",
        })
    leads.sort(key=lambda x: (-x["score"], -x["tax_amount_due"], x["address"]))
    return leads


def leads_from_311(zip_code: str, c311: dict, now: datetime) -> list[dict]:
    leads = []
    for addr, info in c311.items():
        if info["complaints"] >= MULTI_UNIT_THRESHOLD or UNIT_MARKER.search(addr):
            continue
        sc, why = score({}, info, now)
        leads.append({"score": sc * 2, "address": addr, "city": "Dallas", "zip": zip_code,
                      "why": "; ".join(why), "code_complaints": info["complaints"]})
    leads.sort(key=lambda x: (-x["score"], x["address"]))
    return leads


def write_outputs(leads, zip_code, mode, top, min_score, today, notes):
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = LEADS_DIR / f"{zip_code}-{today}.csv"
    md_path = LEADS_DIR / f"{zip_code}-{today}.md"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(leads[0].keys()) if leads else ["address"])
        w.writeheader()
        w.writerows(leads)

    shortlist = [l for l in leads if l["score"] >= min_score][:top]
    lines = [
        f"# Lead List — {zip_code} — {today}", "",
        f"Mode: **{mode}**. {len(leads):,} houses with at least one signal; "
        f"{len(shortlist)} shortlisted (score ≥ {min_score}).", "",
        *[f"> {n}" for n in notes], "" if notes else None,
        "Distress signals, not confirmed deals. Run `/property-recon` on the "
        "shortlist to check listing status, mortgage/equity and comps.", "",
        "| # | Score | Address | Owner | Value | Bd/Ba | Why |",
        "|---|-------|---------|-------|-------|-------|-----|",
    ]
    for i, l in enumerate(shortlist, 1):
        value = f"${l['market_value']:,}" if l.get("market_value") else "-"
        bdba = f"{l.get('beds') or '?'}/{l.get('baths') or '?'}" if mode != "311 only" else "-"
        lines.append(f"| {i} | {l['score']} | {l['address']}, {l['city']} {zip_code} | "
                     f"{l.get('owner', '-')} | {value} | {bdba} | {l['why']} |")
    lines += ["", f"Full list with mailing addresses: `{csv_path.name}`", ""]
    md_path.write_text("\n".join(x for x in lines if x is not None))
    return csv_path, md_path, len(shortlist)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank wholesale leads in Dallas County ZIPs.")
    ap.add_argument("zips", nargs="+")
    ap.add_argument("--months", type=int, default=12, help="311 look-back window (default 12)")
    ap.add_argument("--top", type=int, default=25, help="Shortlist size (default 25)")
    ap.add_argument("--min-score", type=int, default=40, help="Shortlist cutoff (default 40)")
    ap.add_argument("--max-value", type=float, default=450000,
                    help="Skip houses appraised above this (default 450000; 0 = no cap)")
    ap.add_argument("--no-311", action="store_true", help="Skip the City of Dallas 311 feed")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    have_db = DB_PATH.exists()
    if not have_db:
        print("No data/dallas.sqlite — run pipeline/build_dallas_db.py for tax, owner and "
              "estate signals. Falling back to 311 only.", file=sys.stderr)

    for z in args.zips:
        if not re.fullmatch(r"75\d{3}", z):
            print(f"Skipping {z}: not a Dallas-area ZIP.", file=sys.stderr)
            continue
        notes, c311 = [], {}
        if not args.no_311:
            try:
                c311 = summarize_311(fetch_311(z, now - timedelta(days=30 * args.months)), z)
            except Exception as e:  # noqa: BLE001
                notes.append(f"311 feed unavailable ({e}); code-complaint signals skipped.")
        if not c311 and not args.no_311 and not notes:
            notes.append("No City of Dallas 311 records for this ZIP (outside city limits?); "
                         "code-complaint signals skipped.")

        if have_db:
            leads, mode = leads_from_db(z, c311, args.max_value, now), "tax + appraisal + 311"
        else:
            leads, mode = leads_from_311(z, c311, now), "311 only"
        csv_path, md_path, n = write_outputs(leads, z, mode, args.top, args.min_score, today, notes)
        print(f"{z}: {len(leads):,} houses with signals, {n} shortlisted  →  {md_path.relative_to(REPO_ROOT)}")
        for note in notes:
            print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
