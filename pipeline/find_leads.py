#!/usr/bin/env python3
"""
Lead Finder — Dallas, TX

Finds properties that may be good wholesale leads by pulling the City of
Dallas 311 Service Requests feed (free, public, updated daily) and ranking
addresses by code-compliance distress signals.

Signals used:
  - Repeated code-compliance complaints ("Code Concern - CCS")
  - Recent complaints (last 60 / 180 days)
  - Complaints still open
  - "Single Family Rental Needs Registration" requests (an unregistered
    rental: the owner is a landlord, often absentee or tired)

Output (written to deals/leads/):
  {zip}-{date}.csv   every scored address, best first
  {zip}-{date}.md    top leads table, ready for /property-recon

Usage:
  python3 pipeline/find_leads.py 75241
  python3 pipeline/find_leads.py 75241 75216 --months 12 --top 25

No API key needed. If SOCRATA_APP_TOKEN is set, it is sent to raise rate
limits.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_URL = "https://www.dallasopendata.com/resource/d7e7-envw.json"
CODE_CONCERN = "Code Concern - CCS"
RENTAL_REG = "Single Family Rental Needs Registration - CCS"
SIGNAL_TYPES = (CODE_CONCERN, RENTAL_REG)

# An address with this many complaints is almost always an apartment
# complex, business, or corridor address, not a house.
MULTI_UNIT_THRESHOLD = 25
UNIT_MARKER = re.compile(r"\b(APT|UNIT|STE|SUITE|BLDG)\b|#")

REPO_ROOT = Path(__file__).resolve().parent.parent
LEADS_DIR = REPO_ROOT / "deals" / "leads"


def fetch_requests(zip_code: str, since: datetime) -> list[dict]:
    """Pull every signal-type 311 request for one ZIP since a date."""
    types = ", ".join(f"'{t}'" for t in SIGNAL_TYPES)
    where = (
        f"service_request_type in ({types}) "
        f"AND created_date >= '{since.strftime('%Y-%m-%dT%H:%M:%S')}' "
        f"AND address like '%{zip_code}'"
    )
    rows, offset, page = [], 0, 50000
    headers = {"Accept": "application/json"}
    token = os.getenv("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token

    while True:
        params = {
            "$select": "address, service_request_type, status, created_date",
            "$where": where,
            "$order": "created_date DESC",
            "$limit": page,
            "$offset": offset,
        }
        url = f"{DATASET_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = json.load(resp)
        if isinstance(batch, dict) and batch.get("error"):
            raise RuntimeError(f"Dallas Open Data error: {batch.get('message')}")
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def clean_address(raw: str, zip_code: str) -> str:
    """'3130 STAG RD, DALLAS, TX, 75241' -> '3130 STAG RD'"""
    addr = raw.upper().strip()
    addr = re.sub(rf",?\s*DALLAS,?\s*TX,?\s*{zip_code}$", "", addr)
    return re.sub(r"\s+", " ", addr).strip(" ,")


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value[:19]).replace(tzinfo=timezone.utc)


def score_address(info: dict, now: datetime) -> tuple[int, list[str]]:
    """Return (score 0-100, reasons) for one address."""
    score, reasons = 0, []
    n = info["code_concerns"]

    if n >= 10:
        score += 45
    elif n >= 5:
        score += 40
    elif n >= 3:
        score += 30
    elif n >= 2:
        score += 20
    elif n == 1:
        score += 5
    if n:
        reasons.append(f"{n} code complaints")

    if info["last_complaint"]:
        age = (now - info["last_complaint"]).days
        if age <= 60:
            score += 20
            reasons.append(f"latest {age}d ago")
        elif age <= 180:
            score += 10
            reasons.append(f"latest {age}d ago")

    if info["open"]:
        score += 15
        reasons.append(f"{info['open']} still open")

    if info["rental_registration"]:
        score += 20
        reasons.append("unregistered rental (landlord)")

    if info["likely_multi_unit"]:
        score -= 30
        reasons.append("likely apartment/commercial")

    return max(0, min(100, score)), reasons


def build_leads(rows: list[dict], zip_code: str, now: datetime) -> list[dict]:
    by_addr = defaultdict(lambda: {
        "code_concerns": 0, "rental_registration": 0, "open": 0,
        "first_complaint": None, "last_complaint": None,
    })

    for r in rows:
        if not r.get("address"):
            continue
        addr = clean_address(r["address"], zip_code)
        info = by_addr[addr]
        created = parse_date(r["created_date"])
        if r["service_request_type"] == CODE_CONCERN:
            info["code_concerns"] += 1
        else:
            info["rental_registration"] += 1
        if (r.get("status") or "").lower() != "closed":
            info["open"] += 1
        if not info["last_complaint"] or created > info["last_complaint"]:
            info["last_complaint"] = created
        if not info["first_complaint"] or created < info["first_complaint"]:
            info["first_complaint"] = created

    leads = []
    for addr, info in by_addr.items():
        info["likely_multi_unit"] = (
            info["code_concerns"] >= MULTI_UNIT_THRESHOLD
            or bool(UNIT_MARKER.search(addr))
        )
        score, reasons = score_address(info, now)
        leads.append({
            "address": addr,
            "zip": zip_code,
            "score": score,
            "code_complaints": info["code_concerns"],
            "open_requests": info["open"],
            "rental_registration_flag": "yes" if info["rental_registration"] else "",
            "likely_multi_unit": "yes" if info["likely_multi_unit"] else "",
            "first_complaint": info["first_complaint"].date().isoformat(),
            "last_complaint": info["last_complaint"].date().isoformat(),
            "why": "; ".join(reasons),
        })

    leads.sort(key=lambda x: (-x["score"], -x["code_complaints"], x["address"]))
    return leads


def write_outputs(leads: list[dict], zip_code: str, months: int, top: int,
                  min_score: int, today: str) -> tuple[Path, Path]:
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = LEADS_DIR / f"{zip_code}-{today}.csv"
    md_path = LEADS_DIR / f"{zip_code}-{today}.md"

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(leads[0].keys()) if leads else ["address"])
        writer.writeheader()
        writer.writerows(leads)

    shortlist = [l for l in leads if l["score"] >= min_score and not l["likely_multi_unit"]][:top]
    lines = [
        f"# Lead List — Dallas, TX {zip_code}",
        "",
        f"Generated {today} from Dallas 311 Service Requests "
        f"(last {months} months). {len(leads)} addresses scored; "
        f"{len(shortlist)} shortlisted (score >= {min_score}, apartments/commercial removed).",
        "",
        "These are **distress signals, not confirmed deals**. Run "
        "`/property-recon` on each to check owner, equity, and tax status.",
        "",
        "| # | Address | Score | Complaints | Open | Rental | Last | Why |",
        "|---|---------|-------|-----------|------|--------|------|-----|",
    ]
    for i, l in enumerate(shortlist, 1):
        lines.append(
            f"| {i} | {l['address']}, Dallas, TX {zip_code} | {l['score']} | "
            f"{l['code_complaints']} | {l['open_requests']} | "
            f"{l['rental_registration_flag'] or '-'} | {l['last_complaint']} | {l['why']} |"
        )
    lines += ["", f"Full list: `{csv_path.name}`", ""]
    md_path.write_text("\n".join(lines))
    return csv_path, md_path


def main() -> int:
    p = argparse.ArgumentParser(description="Find Dallas wholesale leads from code-compliance data.")
    p.add_argument("zips", nargs="+", help="Dallas ZIP code(s), e.g. 75241")
    p.add_argument("--months", type=int, default=12, help="Look-back window (default 12)")
    p.add_argument("--top", type=int, default=25, help="Shortlist size (default 25)")
    p.add_argument("--min-score", type=int, default=40, help="Shortlist cutoff (default 40)")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=30 * args.months)
    today = now.date().isoformat()

    for z in args.zips:
        if not re.fullmatch(r"75\d{3}", z):
            print(f"Skipping {z}: not a Dallas-area ZIP (75xxx).", file=sys.stderr)
            continue
        rows = fetch_requests(z, since)
        leads = build_leads(rows, z, now)
        csv_path, md_path = write_outputs(leads, z, args.months, args.top, args.min_score, today)
        shortlisted = sum(1 for l in leads if l["score"] >= args.min_score and not l["likely_multi_unit"])
        print(f"{z}: {len(rows)} requests -> {len(leads)} addresses, "
              f"{min(shortlisted, args.top)} shortlisted")
        print(f"  {md_path.relative_to(REPO_ROOT)}")
        print(f"  {csv_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
