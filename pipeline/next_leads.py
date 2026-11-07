#!/usr/bin/env python3
"""
Pick the next N best leads that are NOT already on the monday board, and
write everything the daily run needs:

  out/monday_items.json   create_items payload for the Sol Acquisitions board
                          (column ids from pipeline/sol_board.json)
  out/skiptrace.csv       skip-trace upload file (heir/contact name when the
                          tax bill is mailed "care of" someone)
  out/summary.md          short human summary of what was picked

Usage:
  python3 pipeline/next_leads.py --exclude existing_addresses.txt --count 15 --out OUTDIR

existing_addresses.txt: one board item name per line (e.g.
"6460 Tumbling Creek Trl, Dallas TX 75241"). Matching is on street address
+ ZIP, case-insensitive.

Candidate ZIPs: --zips, else the 20 Dallas County ZIPs with the most
single-family homes 2+ years tax delinquent (from data/dallas.sqlite).
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import find_leads as fl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BOARD = json.loads((REPO / "pipeline" / "sol_board.json").read_text())
STATE_ABBR = {"TEXAS": "TX", "CALIFORNIA": "CA", "FLORIDA": "FL", "NEW JERSEY": "NJ",
              "GEORGIA": "GA", "LOUISIANA": "LA", "OKLAHOMA": "OK", "ILLINOIS": "IL",
              "NEW YORK": "NY", "ARIZONA": "AZ", "COLORADO": "CO", "NEVADA": "NV"}


def key(name: str) -> str:
    """'6460 Tumbling Creek Trl, Dallas TX 75241' -> '6460 TUMBLING CREEK TRL|75241'"""
    street = name.split(",")[0].strip().upper()
    street = re.sub(r"\s+", " ", street)
    z = re.search(r"\b(\d{5})\b\s*$", name.strip())
    return f"{street}|{z.group(1) if z else ''}"


def default_zips(n=20):
    db = sqlite3.connect(fl.DB_PATH)
    return [z for (z,) in db.execute("""
        SELECT p.zip FROM parcels p JOIN tax_delinquent t USING (account)
        WHERE p.sptd_code='A11' AND p.government_owner=0 AND t.years_delinquent>=2
          AND p.zip != '' GROUP BY p.zip ORDER BY count(*) DESC LIMIT ?""", (n,))]


def contact_from_mailing(mail: str):
    """Return (display_name, first, last) for a care-of / named mailing line, else None."""
    first_part = mail.split(",")[0].strip()
    m = re.match(r"^(%|C/O)\s*(.+)$", first_part, re.I)
    if m:  # "% LYDIA SALAZAR HERNANDEZ" — first-last order
        parts = m.group(2).split()
        return m.group(2).title(), " ".join(parts[:-1]).title(), parts[-1].title()
    if re.fullmatch(r"ET\s*AL|ET\s*UX|ETAL", first_part, re.I):
        return None
    if first_part and not re.search(r"\d|P\s*O\s*BOX", first_part, re.I):
        parts = first_part.split()  # "PALMER FRANK HARVEY" — DCAD last-first order
        if len(parts) >= 2:
            return " ".join(parts[1:]).title() + " " + parts[0].title(), " ".join(parts[1:]).title(), parts[0].title()
    return None


def owner_first_last(owner: str):
    n = re.sub(r"\b(LIFE ESTATE|ESTATE OF|EST OF|ESTATE|EST)\b.*$", "", owner).replace("&", "").split()
    return (" ".join(n[1:]).title(), n[0].title()) if n else ("", "")


def strip_contact(mail: str) -> str:
    if contact_from_mailing(mail) or re.match(r"^(ET\s*AL|ET\s*UX|ETAL),", mail, re.I):
        return ",".join(mail.split(",")[1:]).strip()
    return mail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", type=Path, help="File with board item names already on the board")
    ap.add_argument("--count", type=int, default=15)
    ap.add_argument("--zips", nargs="*")
    ap.add_argument("--min-score", type=int, default=60)
    ap.add_argument("--max-value", type=float, default=450000)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not fl.DB_PATH.exists():
        sys.exit("data/dallas.sqlite missing — run pipeline/build_dallas_db.py first")
    existing = set()
    if args.exclude and args.exclude.exists():
        existing = {key(l) for l in args.exclude.read_text().splitlines() if l.strip()}

    now = datetime.now(timezone.utc)
    zips = args.zips or default_zips()
    pool = []
    for z in zips:
        try:
            c311 = fl.summarize_311(fl.fetch_311(z, now - timedelta(days=365)), z)
        except Exception as e:  # noqa: BLE001
            print(f"  {z}: 311 unavailable ({e})", file=sys.stderr)
            c311 = {}
        for l in fl.leads_from_db(z, c311, args.max_value, now):
            if l["score"] >= args.min_score:
                pool.append(l)
    pool.sort(key=lambda x: (-x["score"], -x["tax_amount_due"], x["address"]))

    picked, seen = [], set()
    for l in pool:
        k = f"{l['address']}|{l['zip']}"
        if k in existing or k in seen:
            continue
        seen.add(k)
        picked.append(l)
        if len(picked) == args.count:
            break

    args.out.mkdir(parents=True, exist_ok=True)
    c, lab = BOARD["columns"], BOARD["labels"]
    items, st_rows, summary = [], [], []
    for l in picked:
        mail_full = ", ".join(x for x in [l["mail_address"], l["mail_city"], l["mail_state"], l["mail_zip"]] if x).title()
        contact = contact_from_mailing(l["mail_address"])
        seller = l["owner"].title() + (f" — {contact[0]} (heir/contact on tax bill)" if contact else "")
        name = f"{l['address'].title()}, {l['city']} TX {l['zip']}"
        notes = (f"Lead score {l['score']}/100 (ZIP {l['zip']}). {l['why']}. "
                 f"Taxes owed ${float(l['tax_amount_due']):,.0f}; DCAD value ${l['market_value']:,}; built {l['year_built']}. "
                 f"Mailing: {mail_full}. Source: Dallas County tax roll + DCAD + Dallas 311 ({now:%b %d %Y}). "
                 f"No phone yet - needs skip trace.")
        cv = {c["status"]: {"label": lab["status_new"]},
              c["priority"]: {"label": "High" if l["score"] >= 90 else "Medium"},
              c["house_link"]: {"url": l["dcad_url"], "text": "DCAD record"},
              c["property_type"]: {"label": lab["property_type"]},
              c["lead_source"]: {"labels": [lab["lead_source"]]},
              c["notes"]: notes, c["sellers_name"]: seller}
        if l["beds"]:
            cv[c["bedrooms"]] = str(int(l["beds"]))
        if l["baths"]:
            cv[c["bathrooms"]] = str(l["baths"])
        if l["sqft"]:
            cv[c["sqft"]] = str(l["sqft"])
        items.append({"name": name, "groupId": BOARD["group_id"], "columnValues": json.dumps(cv),
                      "createLabelsIfMissing": True})

        first, last = (contact[1], contact[2]) if contact else owner_first_last(l["owner"])
        st_rows.append([first, last, l["address"].title(), l["city"], "TX", l["zip"],
                        strip_contact(l["mail_address"]).title(), l["mail_city"].title(),
                        STATE_ABBR.get(l["mail_state"], l["mail_state"]), l["mail_zip"], l["owner"].title()])
        summary.append(f"| {l['score']} | {name} | {l['owner'].title()} | ${float(l['tax_amount_due']):,.0f} | {l['why']} |")

    (args.out / "monday_items.json").write_text(json.dumps(items))
    with (args.out / "skiptrace.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["First Name", "Last Name", "Property Address", "Property City", "Property State",
                    "Property Zip", "Mailing Address", "Mailing City", "Mailing State", "Mailing Zip",
                    "Owner of Record"])
        w.writerows(st_rows)
    (args.out / "summary.md").write_text(
        f"Picked {len(picked)} of {len(pool):,} candidates (score ≥ {args.min_score}) from ZIPs {', '.join(zips)}; "
        f"{len(existing)} already on board skipped.\n\n| Score | Address | Owner | Taxes owed | Why |\n|---|---|---|---|---|\n"
        + "\n".join(summary) + "\n")
    print(f"picked {len(picked)} → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
