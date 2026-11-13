#!/usr/bin/env python3
"""
Turn clark_county.py output (leads.csv) into:
  monday_items.json  create_items payload for the Sol Acquisitions board
  skiptrace.csv      skip-trace upload file

Usage:
  python3 pipeline/clark_to_monday.py LEADS_CSV --count 100 --group GROUP_ID --out OUTDIR
"""

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BOARD = json.loads((REPO / "pipeline" / "sol_board.json").read_text())
ASSESSOR = "https://maps.clarkcountynv.gov/assessor/AssessorParcelDetail/parceldetail.aspx?hdnParcel={apn}&hdnInstance=pcl7"
TOWN_CITY = {"PARADISE": "Las Vegas", "SPRING VALLEY": "Las Vegas", "SUNRISE MANOR": "Las Vegas",
             "WHITNEY": "Las Vegas", "WINCHESTER": "Las Vegas", "ENTERPRISE": "Las Vegas",
             "SUMMERLIN": "Las Vegas", "CLARK COUNTY": "Las Vegas", "LAS VEGAS": "Las Vegas",
             "NORTH LAS VEGAS": "North Las Vegas", "HENDERSON": "Henderson", "BOULDER CITY": "Boulder City",
             "MESQUITE": "Mesquite", "LAUGHLIN": "Laughlin"}


def owner_first_last(owner: str):
    o = re.sub(r"\b(ESTATE OF|EST OF|ESTATE|HEIRS|TRUST|TRS|TRUSTEES?|FAMILY|LIVING|REVOCABLE|ET AL)\b.*$", "", owner.upper())
    o = o.split("&")[0].split()
    return (" ".join(o[1:]).title(), o[0].title()) if o else ("", "")


def split_mailing(m: str):
    m = re.sub(r"^(C/O|%)\s*.+?\s+(?=\d|P ?O BOX)", "", m.strip(), flags=re.I)
    x = re.match(r"^(.*?)\s+([A-Z][A-Z .'-]+?)\s+([A-Z]{2})\s+(\d{5})(?:-\d{4})?$", m)
    return (x.group(1).title(), x.group(2).title(), x.group(3), x.group(4)) if x else (m.title(), "", "", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("leads", type=Path)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(a.leads.open()))[:a.count]
    c, lab = BOARD["columns"], BOARD["labels"]
    items, st = [], []
    for r in rows:
        city = TOWN_CITY.get(r["town"].upper(), r["town"].title())
        street, mcity, mst, mzip = split_mailing(r["mailing"])
        name = f"{r['address'].title()}, {city} NV"
        seller = r["owner"].title() + (f" — {r['contact']} (c/o on tax bill)" if r["contact"] else "")
        tv = int(float(r["taxable_value"])) if r["taxable_value"] else 0
        sale = f"last sale ${int(float(r['last_sale_price'])):,} ({r['last_sale'][:7]})" if r["last_sale_price"] else "no recorded sale price"
        notes = (f"Lead score {r['score']}/100 (Clark County NV, area: {r['town'].title()}). {r['why']}. "
                 f"Delinquent taxes ${float(r['amount_due']):,.0f} per Treasurer FY2026 notice (as of May 6 2026; confirm current balance). "
                 f"Assessor taxable value ${tv:,}; {sale}; built {r['year_built'] or '?'}. APN {r['apn_fmt']}. "
                 f"Mailing: {r['mailing'].title()}. Source: Clark County Treasurer + Assessor + City of Las Vegas code data "
                 f"({date.today():%b %d %Y}). No phone yet - needs skip trace.")
        cv = {c["status"]: {"label": lab["status_new"]},
              c["priority"]: {"label": "High" if int(r["score"]) >= 70 else "Medium"},
              c["house_link"]: {"url": ASSESSOR.format(apn=re.sub(r"\D", "", r["apn_fmt"])), "text": "Assessor record"},
              c["property_type"]: {"label": lab["property_type"]},
              c["lead_source"]: {"labels": [lab["lead_source"]]},
              c["notes"]: notes, c["sellers_name"]: seller}
        if r["beds"]:
            cv[c["bedrooms"]] = r["beds"]
        if r["baths"]:
            cv[c["bathrooms"]] = r["baths"]
        if r["sqft"]:
            cv[c["sqft"]] = r["sqft"]
        items.append({"name": name, "groupId": a.group, "columnValues": json.dumps(cv), "createLabelsIfMissing": True})
        if r["contact"]:
            parts = r["contact"].split()
            first, last = " ".join(parts[:-1]), parts[-1]
        else:
            first, last = owner_first_last(r["owner"])
        st.append([first, last, r["address"].title(), city, "NV", "", street, mcity, mst, mzip, r["owner"].title(), r["apn_fmt"]])
    (a.out / "monday_items.json").write_text(json.dumps(items))
    with (a.out / "skiptrace.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["First Name", "Last Name", "Property Address", "Property City", "Property State", "Property Zip",
                    "Mailing Address", "Mailing City", "Mailing State", "Mailing Zip", "Owner of Record", "APN"])
        w.writerows(st)
    print(f"{len(items)} items → {a.out}")


if __name__ == "__main__":
    main()
