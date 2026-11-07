# What Makes a House Good for Wholesaling — and Where to Find Them for Free

Research notes behind `pipeline/` (November 2026). Focus: Dallas County, TX.

---

## 1. What makes a good wholesale deal

A wholesale deal works when **two things are true at once**:

1. **A motivated seller** — someone who values speed, certainty, or relief
   over top dollar.
2. **A real spread** — the price you can contract at leaves room for your
   fee *and* a profit for your cash buyer.

### The spread (the math)

```
Max offer  ≈  ARV × 70%  −  repairs  −  your assignment fee
```

- **ARV** = after-repair value from recent comps (`/comp-analyzer`).
- Flippers typically want 15–25% of ARV as gross profit; 30% all-in is
  where "70%" comes from. In hot markets buyers stretch to 75–78%; in
  expensive areas 70% is hard to hit.
- Underestimating repairs is the most common reason a wholesale deal falls
  apart after assignment. Pad the estimate (`/rehab-estimator`).
- Keep the fee reasonable — buyers walk from deals with outrageous fees.

Worked example: ARV $300k, buyer wants 20%, $45k repairs, $10k fee →
max offer ≈ $185k (≈ 62% of ARV).

### The house (what cash buyers want)

| Trait | Why |
|-------|-----|
| Single-family, 3 bed / 1–2 bath, 1,000–1,800 sqft | Biggest buyer pool (flippers + landlords) |
| Built ~1950–1990, cosmetic-to-moderate repairs | Margin comes from rehab; full gut jobs scare buyers |
| Priced in the bottom half of the local market | Landlords buy for rent ratio; flippers need room under ARV |
| Neighborhood with recent investor sales | Proves buyers exist — check comps for cash sales |
| Long ownership / no or low mortgage | Equity is what makes a discount possible |

### The seller (motivation signals)

Lead vendors all sell the same core lists. Single signals cast a wide net;
**stacking** signals (e.g. absentee + high equity + tax delinquent) narrows
to the most motivated owners.

| Signal | Why the owner may sell at a discount | Free in Dallas? |
|--------|--------------------------------------|-----------------|
| Tax delinquent (esp. 2+ years, suit filed) | Penalties grow ~monthly; a tax suit can end in a sheriff's sale | ✅ County TRW file — **built** |
| Inherited / estate owner | Heirs often live elsewhere, split ownership, don't want the house | ✅ DCAD "EST OF" + "(INHERIT)" — **built** |
| Absentee / out-of-state owner | Tired landlords, managing from afar | ✅ DCAD homestead + mailing address — **built** |
| Long ownership (20+ yrs) | Likely free and clear → high equity | ✅ DCAD deed date — **built** |
| Poor condition | Too costly to fix; can't sell retail | ✅ DCAD condition rating — **built** |
| Code violations | Fines, liens, city pressure | ✅ Dallas 311 — **built** (city limits only) |
| Unregistered rental | Landlord already in trouble with the city | ✅ Dallas 311 — **built** |
| Pre-foreclosure (mortgage) | Must sell before the auction date | ✅ County Clerk notices — manual (see §3) |
| Probate filing | Estate must liquidate | ✅ County court records — manual |
| Eviction filings | Landlord with problem tenants | ✅ JP court records — manual |
| Vacant | No one maintaining it | Partly (USPS vacancy is paid; code complaints + absentee is a proxy) |
| High equity (exact) | Needs mortgage data | ❌ Paid (PropStream, BatchData) |

---

## 2. What the pipeline uses today (all free, no key)

| Source | What it gives | Refresh | Script |
|--------|---------------|---------|--------|
| [DCAD data products](https://www.dallascad.org/DataProducts.aspx) — "Most Current Ownership" zip | 684k residential parcels: owner, mailing address, property ZIP, deed date, value, year built, sqft, beds/baths, condition, homestead, inherited owners | Monthly-ish | `build_dallas_db.py` |
| [Dallas County Tax Roll (TRW)](https://www.dallascounty.org/departments/tax/tax-roll.php) | Every unpaid account: years owed, amount due, tax suit, bankruptcy, payment plan | Weekly | `build_dallas_db.py` |
| [Dallas 311 Service Requests](https://www.dallasopendata.com/d/d7e7-envw) | Code complaints, open cases, unregistered rentals (city of Dallas only) | Daily | `find_leads.py` |

Scoring weights live in `score()` in `pipeline/find_leads.py`.

> Dallas's older "Code Violations" dataset (`x9pz-kdq9`) stopped updating
> in July 2018. Don't use it.

---

## 3. More free sources to add next

| Source | Lead type | How | Effort |
|--------|-----------|-----|--------|
| Dallas County Clerk foreclosure notices — [dallas.tx.publicsearch.us](https://dallas.tx.publicsearch.us) (notices filed since Feb 24, 2026; older ones on the [Clerk's page](https://www.dallascounty.org/government/county-clerk/recording/foreclosures.php)) | Pre-foreclosure | Notices are posted 21 days before the sale; sales are the first Tuesday of each month. Searchable by address; the clerk does not publish a list. Some notices lack a street address. | Medium — search site, needs a scraper or monthly manual pull |
| Dallas County Tax Office [sheriff's sales / tax foreclosure resales](https://taxoffice.dallascounty.org/hc/en-us/articles/52332852588571-Sheriff-Sales-Tax-Foreclosure-Resales) | Tax foreclosure | Upcoming sale lists; cross-match with `tax_suit` leads to find ones with a sale date | Low |
| Dallas Building Permits (`e7gq-4sah`, Dallas Open Data) | Stalled rehab / unpermitted work | Same API as 311 | Low |
| Probate court filings (Dallas County Probate Courts) | Probate | Search new estate filings, match decedent name to DCAD owner | Medium |
| JP court eviction filings | Tired landlord | Search new forcible-detainer cases, match to DCAD | Medium |
| Tarrant (TAD), Collin (CCAD), Denton (DCAD) appraisal districts | Expand to DFW | Most Texas appraisal districts publish free bulk files like Dallas does — verify each | Medium per county |
| Driving for dollars | Vacant / distressed | Note addresses, run `find_leads.py` / `/property-recon` | Manual |
| FSBO and expired listings | Tired sellers | Zillow/Craigslist FSBO, old listings with long days on market | Manual / Firecrawl free tier |

### Paid (only if free runs dry)

PropStream, BatchData, DealMachine and similar add mortgage balances
(true equity), USPS vacancy, phone numbers (skip tracing) and pre-built
lists. Most of their Dallas list types are built from the same public
records above.

---

## 4. Texas rules for wholesalers

- An unlicensed person may sell or assign an **equitable interest** in a
  contract only if they don't engage in brokerage **and disclose in writing**
  that they are selling the contract interest, not the property (Tex. Occ.
  Code § 1101.0045).
- Since **January 1, 2024**, that written disclosure must go to the
  **seller as well as the buyer**.
- Failing to disclose is treated as unlicensed brokerage — a Class A
  misdemeanor (§ 1101.351).
- Check the current statute and TREC rules, or ask a Texas real estate
  attorney, before your first contract.

### Using these lists responsibly

- Many top leads are **estates and long-time elderly owners**. Be
  straightforward about what you are offering and what the house is worth.
  Don't pressure grieving heirs.
- Lead files contain real people's names and mailing addresses: they are
  gitignored and should stay private.
- Follow federal and Texas rules on calls and texts (Do Not Call registry,
  TCPA) before you call or text from these lists.

---

## Sources

- [DCAD Data Products](https://www.dallascad.org/DataProducts.aspx)
- [Dallas County Tax Roll (TRW)](https://www.dallascounty.org/departments/tax/tax-roll.php) · [TRW FAQ](https://www.dallascounty.org/Assets/uploads/docs/tax/trw/1_TRWfile_FAQ_v12.pdf) · [Delinquent-roll questions](https://taxoffice.dallascounty.org/hc/en-us/articles/52331684250779-Questions-regarding-the-TRW-file-delinquent-tax-roll)
- [Dallas County Clerk — foreclosures](https://www.dallascounty.org/government/county-clerk/recording/foreclosures.php)
- [Dallas County Tax Office — sheriff's sales](https://taxoffice.dallascounty.org/hc/en-us/articles/52332852588571-Sheriff-Sales-Tax-Foreclosure-Resales)
- [Dallas Open Data](https://www.dallasopendata.com)
- Lead stacking: [REsimpli](https://resimpli.com/blog/best-seller-list-combinations-for-real-estate-investors/), [DealMachine](https://www.dealmachine.com/blog/the-essential-lead-lists-for-wholesaling-success), [Realeflow](https://get.realeflow.com/real-estate-leads) (vendor blogs — treat as marketing)
- Deal math: [BiggerPockets on the 70% rule](https://www.biggerpockets.com/blog/90493-2), [REsimpli 70% rule calculator](https://resimpli.com/blog/70-rule-calculator/), [Goliath Data on MAO](https://goliathdata.com/use-mao-formula-to-know-when-to-act)
- Texas law: [Tex. Occ. Code § 1101.0045](https://codes.findlaw.com/tx/occupations-code/occ-sect-1101-0045/), [SB 1577 (2023) text](https://capitol.texas.gov/tlodocs/88R/billtext/html/SB01577H.htm), [SB 2212 (2017) analysis](https://capitol.texas.gov/tlodocs/85R/analysis/html/SB02212F.htm)
