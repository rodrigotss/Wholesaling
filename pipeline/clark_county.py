#!/usr/bin/env python3
"""
Lead finder — Clark County, NV (Las Vegas, Henderson, North Las Vegas)

Free, official sources only:
  1. Clark County Treasurer — annual "Notice of Delinquent Taxes on Real
     Property" (NRS 361.565), Excel version: parcel, owner, taxes,
     penalty/interest, costs. ~14,000 parcels.
     https://www.clarkcountynv.gov/government/elected_officials/county_treasurer/notice-of-delinquent-taxes-nrs-361-565
  2. City of Las Vegas — Code Enforcement Open Data (ArcGIS FeatureServer):
     cases by parcel since 2015 (feed ends Feb 2024 as of Nov 2026).
  3. Clark County Assessor — public parcel detail page, one lookup per
     shortlisted parcel (owner, mailing address, location, land use,
     beds/baths, sqft, year built, last sale, taxable value). The bulk
     assessor extract is a paid product, so we only look up the few hundred
     parcels that survive the pre-filter, slowly.

Why no "years delinquent": the notice lists the amount due, not the years.
A large amount relative to the home's taxable value implies several years.

Usage:
  python3 pipeline/clark_county.py --count 100 --lookups 450 --out out/clark
Outputs (gitignored): leads.csv (all scored), plus whatever next steps use.
"""

import argparse
import csv
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

NOTICE_PAGE = ("https://www.clarkcountynv.gov/government/elected_officials/county_treasurer/"
               "notice-of-delinquent-taxes-nrs-361-565")
# Current publication (FY2026). The script tries to discover a newer link from the notice PDF first.
NOTICE_XLSX = ("https://www.clarkcountynv.gov/adobe/assets/urn:aaid:aem:fb735729-434b-4b9f-8fe2-4228a6bfbe0b/"
               "original/as/FY26-Annual-Delinquency-Publication.xlsx")
CODE_URL = ("https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/"
            "Code_Enforcement_Open_Data/FeatureServer/0/query")
PARCEL_URL = ("https://maps.clarkcountynv.gov/assessor/AssessorParcelDetail/parceldetail.aspx"
              "?hdnParcel={apn}&hdnInstance=pcl7")

NON_PERSON = re.compile(
    r"\b(L ?L ?C|INC|CORP|LP|LTD|CO|COMPANY|HOLDINGS|PROPERTIES|INVESTMENTS?|REALTY|PARTNERS|FUND|"
    r"BANK|ASSOCIATION|ASSN|HOA|CHURCH|CITY OF|COUNTY|STATE OF|UNITED STATES|DBA|MINISTR\w*|GROUP|"
    r"VENTURES|DEVELOPMENT|ENTERPRISES|UNKNOWN OWNER|LAND|HOMES|BUILDERS|CAPITAL|MANAGEMENT|PROJECT|"
    r"SERIES|IGLESIA|TEMPLO|BAPTIST|HOUSING AUTH\w*)\b")
ESTATE = re.compile(r"\b(EST OF|HEIRS|DECEASED)\b|(?<!REAL )\bESTATE\b(?! (REVOCABLE|LIVING|FAMILY|TRUST|PLANNING))")


def get(url, timeout=90, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def load_notice(path: Path | None):
    import openpyxl  # pip install openpyxl
    data = path.read_bytes() if path else get(NOTICE_XLSX, timeout=300)
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True).worksheets[0]
    out = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        if not r or not r[0]:
            continue
        apn = re.sub(r"\D", "", str(r[0]))
        due = sum(float(x or 0) for x in r[2:5])
        out[apn] = {"apn_fmt": str(r[0]), "notice_owner": str(r[1] or "").strip(), "amount_due": round(due, 2)}
    return out


def load_code_cases():
    by = defaultdict(lambda: {"cases": 0, "open": 0, "last": None, "types": set()})
    offset = 0
    while True:
        q = urllib.parse.urlencode({"where": "Parcel_Number IS NOT NULL", "outFields": "Parcel_Number,STAT,Event_Date,DESCRIPT",
                                    "resultOffset": offset, "resultRecordCount": 2000, "returnGeometry": "false",
                                    "orderByFields": "ObjectId", "f": "json"})
        page = json.loads(get(f"{CODE_URL}?{q}"))
        feats = page.get("features", [])
        for f in feats:
            a = f["attributes"]
            apn = str(a["Parcel_Number"]).split(".")[0].zfill(11)
            c = by[apn]
            c["cases"] += 1
            c["open"] += a["STAT"] == "Open"
            if a.get("Event_Date"):
                d = datetime.fromtimestamp(a["Event_Date"] / 1000, timezone.utc).date()
                c["last"] = max(c["last"], d) if c["last"] else d
            if a.get("DESCRIPT") and a["DESCRIPT"] != "None":
                c["types"].add(a["DESCRIPT"])
        if not feats or not page.get("exceededTransferLimit"):
            return by
        offset += len(feats)


def text_of(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def between(t, a, b):
    m = re.search(re.escape(a) + r"\s*(.*?)\s*" + re.escape(b), t)
    return m.group(1).strip() if m else ""


def parse_parcel(t: str) -> dict:
    owner_mail = between(t, "Owner and Mailing Address", "Location Address")
    # Mailing block ends with "CITY ST 12345"; owner lines precede the first line that starts with a digit or PO BOX
    m = re.search(r"^(.*?)\s+((?:\d|P ?O BOX|PO BOX|C/O|%).*)$", owner_mail)
    owner, mailing = (m.group(1), m.group(2)) if m else (owner_mail, "")
    loc = between(t, "Location Address", "City/Unincorporated Town")
    town = between(t, "City/Unincorporated Town", "Assessor Description")
    land_use = between(t, "Land Use", "Dwelling Units")
    sale = re.search(r"Sale Type\s+(\d+)\s+(\d{1,2})/(\d{4})", t)
    taxable = re.search(r"Total Taxable Value\s+([\d,]+)\s+([\d,]+)", t)
    beds = re.search(r"Bedrooms\s+(\d+)", t)
    baths = re.search(r"Bathrooms\s+(\d+)\s*FULL(?:\s*/\s*(\d+)\s*HALF)?", t)
    year = re.search(r"Original Const\. Year\s+(\d{4})", t)
    f1 = re.search(r"1st Floor Sq\. Ft\.\s+(\d+)", t)
    f2 = re.search(r"2nd Floor Sq\. Ft\.\s+(\d+)", t)
    mzip = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", mailing)
    mstate = re.search(r"\b([A-Z]{2})\s+\d{5}", mailing)
    co = re.match(r"^(?:C/O|%)\s*(.+?)\s+(?=\d|P ?O BOX)", mailing.strip(), re.I)
    return {
        "contact": co.group(1).title() if co and "TRUSTEE" not in co.group(1).upper() else "",
        "owner": owner.strip(), "mailing": mailing.strip(), "mail_zip": mzip.group(1) if mzip else "",
        "mail_state": mstate.group(1) if mstate else "", "address": loc.strip(), "town": town.strip(),
        "land_use": land_use.strip(),
        "last_sale_price": int(sale.group(1)) if sale else None,
        "last_sale": date(int(sale.group(3)), int(sale.group(2)), 1) if sale else None,
        "taxable_value": int(taxable.group(1).replace(",", "")) if taxable else None,
        "beds": int(beds.group(1)) if beds else None,
        "baths": (int(baths.group(1)) + 0.5 * int(baths.group(2) or 0)) if baths else None,
        "year_built": int(year.group(1)) if year else None,
        "sqft": (int(f1.group(1)) if f1 else 0) + (int(f2.group(1)) if f2 else 0) or None,
    }


def score(p: dict) -> tuple[int, list[str]]:
    s, why = 0, []
    due, val = p["amount_due"], p.get("taxable_value") or 0
    # One year of Clark County tax is roughly 1% of taxable value.
    yrs_est = due / (0.01 * val) if val else 0
    if yrs_est >= 2.5:
        s += 35; why.append(f"~{yrs_est:.0f}yrs of taxes owed (${due:,.0f})")
    elif yrs_est >= 1.5:
        s += 28; why.append(f"~2yrs of taxes owed (${due:,.0f})")
    else:
        s += 20; why.append(f"taxes delinquent (${due:,.0f})")
    if ESTATE.search(p["owner"].upper()):
        s += 25; why.append("estate/heirs")
    loc_num = re.match(r"(\d+)", p["address"] or "")
    mail_num = re.match(r"(\d+)", p["mailing"] or "")
    absentee = not (loc_num and mail_num and loc_num.group(1) == mail_num.group(1))
    if absentee:
        s += 15; why.append("absentee owner")
        if p["mail_state"] and p["mail_state"] != "NV":
            s += 10; why.append(f"out of state ({p['mail_state']})")
    p["absentee"] = absentee
    if p.get("last_sale"):
        yo = (date.today() - p["last_sale"]).days / 365.25
        p["years_owned"] = round(yo, 1)
        if yo >= 20:
            s += 10; why.append(f"owned {yo:.0f}yrs")
        elif yo >= 10:
            s += 5; why.append(f"owned {yo:.0f}yrs")
    c = p.get("code")
    if c and c["cases"]:
        n = c["cases"]
        s += 20 if n >= 5 else 15 if n >= 3 else 10 if n == 2 else 5
        why.append(f"{n} code cases (Las Vegas)")
        if c["open"]:
            s += 5; why.append("open code case")
    if val and due > 0.5 * val:
        s -= 60; why.append("back taxes over half of value")
    return max(0, min(100, s)), why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notice-xlsx", type=Path)
    ap.add_argument("--min-due", type=float, default=2500)
    ap.add_argument("--max-due", type=float, default=60000)
    ap.add_argument("--lookups", type=int, default=450, help="Max assessor page lookups")
    ap.add_argument("--start", type=int, default=0, help="Skip this many pre-ranked candidates (resume a run)")
    ap.add_argument("--delay", type=float, default=0.8, help="Seconds between assessor lookups")
    ap.add_argument("--max-value", type=float, default=600000)
    ap.add_argument("--exclude", type=Path, help="Board item names already on monday (skip)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("notice…", flush=True)
    notice = load_notice(args.notice_xlsx)
    print(f"  {len(notice):,} delinquent parcels", flush=True)
    print("code cases…", flush=True)
    code = load_code_cases()
    print(f"  {len(code):,} parcels with Las Vegas code cases", flush=True)

    pool = [dict(apn=a, **v) for a, v in notice.items()
            if args.min_due <= v["amount_due"] <= args.max_due and not NON_PERSON.search(v["notice_owner"].upper())]
    for p in pool:
        p["code"] = code.get(p["apn"])
    # Pre-rank: estates, code cases, then amount due (bigger usually = more years behind)
    pool.sort(key=lambda p: (-bool(ESTATE.search(p["notice_owner"].upper())),
                             -((p["code"] or {}).get("cases", 0) > 0), -p["amount_due"]))
    print(f"  {len(pool):,} individual-owner candidates; looking up {min(args.lookups, len(pool))}", flush=True)

    exclude = set()
    if args.exclude and args.exclude.exists():
        exclude = {l.split(",")[0].strip().upper() for l in args.exclude.read_text().splitlines() if l.strip()}

    leads = []
    for i, p in enumerate(pool[args.start:args.start + args.lookups]):
        try:
            d = parse_parcel(text_of(get(PARCEL_URL.format(apn=p["apn"])).decode("utf-8", "replace")))
        except Exception as e:  # noqa: BLE001
            print(f"  {p['apn']}: lookup failed ({e})", file=sys.stderr)
            continue
        finally:
            time.sleep(args.delay)
        p.update(d)
        if not p["land_use"].startswith("20.110") or not p["address"]:
            continue  # single-family residential only
        if NON_PERSON.search(p["owner"].upper()) or "TRUSTEE CLARK COUNTY TREASURER" in p["mailing"].upper():
            continue  # company owner, or already deeded to the County Treasurer as trustee
        if p.get("last_sale") and (date.today() - p["last_sale"]).days < 365:
            continue  # bought within a year: the delinquency is likely the seller's, settled at closing
        if p.get("taxable_value") and p["taxable_value"] > args.max_value:
            continue
        if p["address"].upper() in exclude:
            continue
        p["score"], why = score(p)
        p["why"] = "; ".join(why)
        leads.append(p)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1} looked up, {len(leads)} single-family kept", flush=True)

    leads.sort(key=lambda p: (-p["score"], -p["amount_due"]))
    cols = ["score", "address", "town", "apn_fmt", "owner", "contact", "mailing", "mail_state", "amount_due", "taxable_value",
            "last_sale_price", "last_sale", "years_owned", "beds", "baths", "sqft", "year_built", "absentee", "why"]
    with (args.out / "leads.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in leads:
            w.writerow(p)
    print(f"done: {len(leads)} single-family leads → {args.out / 'leads.csv'}")


if __name__ == "__main__":
    sys.exit(main())
