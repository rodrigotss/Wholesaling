#!/usr/bin/env python3
"""
Build the Dallas County property database from free public bulk files.

Sources (all free, no key):
  DCAD  — Dallas Central Appraisal District "Most Current Ownership" data
          files: owner, mailing address, property address + ZIP, deed date,
          market value, year built, size, beds/baths, condition, homestead,
          inherited-interest owners.  ~170 MB zip, refreshed regularly.
          https://www.dallascad.org/DataProducts.aspx
  TRW   — Dallas County Tax Office delinquent tax roll: every unpaid
          account, years owed, amount due, pending tax suits, bankruptcies.
          ~275 MB zip, refreshed weekly.
          https://www.dallascounty.org/departments/tax/tax-roll.php

Output: data/dallas.sqlite  (gitignored; rebuild weekly)

Usage:
  python3 pipeline/build_dallas_db.py              # download both, build
  python3 pipeline/build_dallas_db.py --dcad path/to/DCAD.zip --trw path/to/trw.zip
"""

import argparse
import csv
import io
import re
import sqlite3
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "dallas.sqlite"

DCAD_URL = ("https://www.dallascad.org/ViewPDFs.aspx?type=3&id="
            "%5C%5CDCAD.ORG%5CWEB%5CWEBDATA%5CWEBFORMS%5Cdata%20products%5C"
            "DCAD{year}_CURRENT.zip")
TRW_PAGE = "https://www.dallascounty.org/departments/tax/tax-roll.php"

ESTATE_RE = re.compile(r"\b(EST OF|ESTATE OF|HEIRS|DECEASED|\(INHERI?T)|\bEST(ATE)?$")
CORP_RE = re.compile(r"\b(LLC|L L C|INC|CORP|CORPORATION|LP|LTD|COMPANY|CO|HOLDINGS|PROPERTIES|INVESTMENTS?|REALTY|PARTNERS|FUND|REIT)\b")
GOV_RE = re.compile(r"\b(CITY OF|COUNTY OF|STATE OF|HOUSING AUTH|LAND BANK|ISD|SCHOOL DIST|UNITED STATES|HUD|SECRETARY OF|CHURCH|MINISTR)")

csv.field_size_limit(10_000_000)


# ── download helpers ────────────────────────────────────────────────────

def download(url: str, dest: Path, tries: int = 4) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            print(f"  downloading {dest.name} ...", flush=True)
            with urllib.request.urlopen(url, timeout=900) as r, dest.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if zipfile.is_zipfile(dest):
                return dest
            raise IOError("not a zip file")
        except Exception as e:  # noqa: BLE001 — retry on any network error
            print(f"    attempt {i + 1} failed: {e}", flush=True)
            time.sleep(2 ** (i + 1))
    sys.exit(f"Could not download {url}")


def find_trw_url() -> str:
    with urllib.request.urlopen(TRW_PAGE, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r'href="([^"]*trwfile\.\d+\.zip)\s*"', page)
    if not m:
        sys.exit("Could not find the TRW download link on the tax office page.")
    url = m.group(1)
    return url if url.startswith("http") else "https://www.dallascounty.org" + url


def open_member(zf: zipfile.ZipFile, pattern: str):
    name = next((n for n in zf.namelist() if re.search(pattern, n, re.I)), None)
    if not name:
        sys.exit(f"{pattern} not found in {zf.filename}")
    return io.TextIOWrapper(zf.open(name), encoding="latin-1", newline="")


# ── DCAD ────────────────────────────────────────────────────────────────

def num(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_date(v: str):
    for fmt in ("%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            pass
    return None


def street_key(num_: str, street: str) -> str:
    return re.sub(r"\s+", " ", f"{num_.strip()} {street.strip()}".upper()).strip()


def load_dcad(db: sqlite3.Connection, path: Path) -> None:
    zf = zipfile.ZipFile(path)
    today = date.today()

    print("  DCAD: accounts", flush=True)
    rows = {}
    for r in csv.DictReader(open_member(zf, r"ACCOUNT_INFO\.CSV$")):
        if r["DIVISION_CD"] != "RES":
            continue
        situs = street_key(r["STREET_NUM"], r["FULL_STREET_NAME"])
        mail_lines = [r[f"OWNER_ADDRESS_LINE{i}"].strip() for i in range(1, 5)]
        mail_street = next((l for l in mail_lines if re.match(r"^\d", l)), "") or next((l for l in mail_lines if l), "")
        mail_zip = r["OWNER_ZIPCODE"].strip()[:5]
        prop_zip = r["PROPERTY_ZIPCODE"].strip()[:5]
        owner = " ".join(x for x in (r["OWNER_NAME1"].strip(), r["OWNER_NAME2"].strip()) if x)
        deed = parse_date(r["DEED_TXFR_DATE"])
        # Compare house number + ZIP, not the full street text: DCAD spells
        # the same street differently in the two places (RD vs DR, spacing).
        mail_num = re.match(r"^(\d+)", mail_street)
        if mail_num:
            same_addr = mail_num.group(1) == r["STREET_NUM"].strip() and (mail_zip == prop_zip or not prop_zip)
        else:  # PO box or blank: only a different ZIP tells us anything
            same_addr = mail_zip == prop_zip or not prop_zip
        rows[r["ACCOUNT_NUM"]] = {
            "account": r["ACCOUNT_NUM"],
            "address": situs,
            "unit": r["UNIT_ID"].strip(),
            "city": r["PROPERTY_CITY"].strip(),
            "zip": prop_zip,
            "owner": owner,
            "mail_address": ", ".join(l for l in mail_lines if l),
            "mail_city": r["OWNER_CITY"].strip(),
            "mail_state": r["OWNER_STATE"].strip(),
            "mail_zip": mail_zip,
            "mail_differs": int(not same_addr),
            "out_of_state": int(r["OWNER_STATE"].strip() not in ("TEXAS", "TX", "")),
            "deed_date": deed.isoformat() if deed else None,
            "years_owned": round((today - deed).days / 365.25, 1) if deed else None,
            "estate_owner": int(bool(ESTATE_RE.search(owner))),
            "corporate_owner": int(bool(CORP_RE.search(owner))),
            "government_owner": int(bool(GOV_RE.search(owner))),
            "sptd_code": None, "market_value": None,
            "year_built": None, "living_sqft": None, "beds": None, "baths": None,
            "condition": None, "pool": None, "homestead": 0, "inherited": 0,
        }

    print("  DCAD: values", flush=True)
    for r in csv.DictReader(open_member(zf, r"ACCOUNT_APPRL_YEAR\.CSV$")):
        p = rows.get(r["ACCOUNT_NUM"])
        if p:
            p["sptd_code"] = r["SPTD_CODE"].strip()
            p["market_value"] = num(r["TOT_VAL"]) or num(r["PREV_MKT_VAL"]) or None

    print("  DCAD: buildings", flush=True)
    for r in csv.DictReader(open_member(zf, r"RES_DETAIL\.CSV$")):
        p = rows.get(r["ACCOUNT_NUM"])
        sqft = num(r["TOT_LIVING_AREA_SF"])
        if p and sqft >= (p["living_sqft"] or 0):
            p.update(
                year_built=int(num(r["YR_BUILT"])) or None,
                living_sqft=int(sqft) or None,
                beds=int(num(r["NUM_BEDROOMS"])) or None,
                baths=num(r["NUM_FULL_BATHS"]) + 0.5 * num(r["NUM_HALF_BATHS"]) or None,
                condition=r["CDU_RATING_DESC"].strip(),
                pool=int(r["POOL_IND"].strip() == "Y"),
            )

    print("  DCAD: homestead exemptions", flush=True)
    for r in csv.DictReader(open_member(zf, r"APPLIED_STD_EXEMPT\.CSV$")):
        p = rows.get(r["ACCOUNT_NUM"])
        d = parse_date(r["HOMESTEAD_EFF_DT"])
        if p and d and d.year > 1900:
            p["homestead"] = 1

    print("  DCAD: inherited interests", flush=True)
    for r in csv.DictReader(open_member(zf, r"MULTI_OWNER\.CSV$")):
        p = rows.get(r["ACCOUNT_NUM"])
        if p and re.search(r"\(INHERI?T", r["OWNER_NAME"], re.I):
            p["inherited"] = 1

    cols = list(next(iter(rows.values())).keys())
    db.execute("DROP TABLE IF EXISTS parcels")
    db.execute(f"CREATE TABLE parcels ({', '.join(cols)}, PRIMARY KEY (account))")
    db.executemany(
        f"INSERT INTO parcels VALUES ({', '.join('?' * len(cols))})",
        ([p[c] for c in cols] for p in rows.values()),
    )
    db.execute("CREATE INDEX parcels_zip ON parcels(zip)")
    db.execute("CREATE INDEX parcels_addr ON parcels(address, zip)")
    print(f"  DCAD: {len(rows):,} residential parcels", flush=True)


# ── TRW (delinquent tax roll, fixed width) ──────────────────────────────

def load_trw(db: sqlite3.Connection, path: Path) -> None:
    zf = zipfile.ZipFile(path)
    today = date.today().strftime("%Y%m%d")
    acc = {}

    def f(line, start, length):  # 1-indexed positions from the file layout
        return line[start - 1:start - 1 + length]

    print("  TRW: scanning delinquent tax roll (takes a few minutes)", flush=True)
    for line in open_member(zf, r"flat\d+"):
        if f(line, 440, 1) != "R":                 # real property only
            continue
        if f(line, 93, 8).strip():                 # DATE-PAID set → paid
            continue
        balance = num(f(line, 111, 11)) / 100
        due = f(line, 101, 8)
        if balance <= 0 or not due.strip() or due >= today:
            continue
        a = acc.setdefault(f(line, 1, 34).strip(), {
            "years": set(), "due": 0.0, "suit": 0, "bankruptcy": 0,
            "payment_plan": 0, "deferral": 0,
        })
        a["years"].add(int(f(line, 35, 4)))
        a["due"] += num(f(line, 490, 11)) / 100
        a["suit"] |= int(f(line, 122, 1).strip() != "")
        a["bankruptcy"] |= int(f(line, 163, 1).strip() != "")
        a["payment_plan"] |= int(f(line, 489, 1) == "Y")
        a["deferral"] |= int(f(line, 219, 1) == "D")

    db.execute("DROP TABLE IF EXISTS tax_delinquent")
    db.execute("""CREATE TABLE tax_delinquent (
        account PRIMARY KEY, years_delinquent, first_year, last_year,
        amount_due, tax_suit, bankruptcy, payment_plan, deferral)""")
    db.executemany(
        "INSERT INTO tax_delinquent VALUES (?,?,?,?,?,?,?,?,?)",
        ((k, len(v["years"]), min(v["years"]), max(v["years"]), round(v["due"], 2),
          v["suit"], v["bankruptcy"], v["payment_plan"], v["deferral"]) for k, v in acc.items()),
    )
    print(f"  TRW: {len(acc):,} delinquent accounts", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dcad", type=Path, help="Path to an already-downloaded DCAD *_CURRENT.zip")
    p.add_argument("--trw", type=Path, help="Path to an already-downloaded trwfile.*.zip")
    p.add_argument("--dcad-year", default=str(date.today().year + 1),
                   help="DCAD data year (the 'Most Current Ownership' file is next year's)")
    args = p.parse_args()

    dcad = args.dcad or download(DCAD_URL.format(year=args.dcad_year), RAW_DIR / f"DCAD{args.dcad_year}_CURRENT.zip")
    trw = args.trw or download(find_trw_url(), RAW_DIR / "trw.zip")

    DATA_DIR.mkdir(exist_ok=True)
    tmp = DB_PATH.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    load_dcad(db, dcad)
    load_trw(db, trw)
    db.execute("CREATE TABLE meta (key PRIMARY KEY, value)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("built", datetime.now().isoformat(timespec="seconds")),
        ("dcad_file", dcad.name), ("trw_file", trw.name),
    ])
    db.commit()
    db.close()
    tmp.replace(DB_PATH)
    print(f"Done: {DB_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
