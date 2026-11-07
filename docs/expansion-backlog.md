# Expansion Backlog — new free lead sources and U.S. markets

The daily run (`.claudeskills/daily-leads-SKILL.md`) takes the top `todo`
item each day. Status values: `todo`, `done`, `blocked: needs host <name>`,
`dropped: <reason>`. Sources must be official and free: government open
data, appraisal or tax bulk files, and court or clerk public search. Hosts
listed are unverified until a run probes them.

## Priority 1: Dallas County, more signals

| # | Item | Signal | Likely hosts | Status |
|---|------|--------|--------------|--------|
| 1 | County Clerk foreclosure notices (posted 21 days before first-Tuesday sales) | Pre-foreclosure | dallas.tx.publicsearch.us | todo |
| 2 | Tax Office sheriff's / tax resale lists, matched to `tax_suit` leads | Tax foreclosure date | taxoffice.dallascounty.org | todo |
| 3 | Dallas building permits (`e7gq-4sah`): expired or stalled permits | Stalled rehab | www.dallasopendata.com (allowed) | todo |
| 4 | Probate court new estate filings, matched by owner name | Probate | courtsportal.dallascounty.org | todo |

## Priority 2: rest of Texas (same playbook as DCAD + TRW)

| # | Market | What to look for | Likely hosts | Status |
|---|--------|------------------|--------------|--------|
| 5 | Tarrant County (Fort Worth) | TAD bulk appraisal file + tax office delinquent roll | www.tad.org, taxoffice.tarrantcounty.com | todo |
| 6 | Harris County (Houston) | HCAD public data download + delinquent tax data; repo already has `deals/county-configs/harris-county-tx.md` | download.hcad.org, www.hctax.net | todo |
| 7 | Bexar County (San Antonio) | BCAD exports + tax office delinquent list | www.bcad.org, www.bexar.org | todo |
| 8 | Collin and Denton Counties | CAD bulk data | www.collincad.org, www.dentoncad.com | todo |

## Priority 3: other U.S. cities with strong open data

| # | Market | What to look for | Likely hosts | Status |
|---|--------|------------------|--------------|--------|
| 9 | Philadelphia, PA | OPA property assessments + real estate tax delinquencies + L&I violations, all on OpenDataPhilly / Carto | phl.carto.com, opendataphilly.org | todo |
| 10 | Detroit, MI | Blight violations, property sales, parcel data | data.detroitmi.gov | todo |
| 11 | Baltimore, MD | Vacant building notices + real property data | data.baltimorecity.gov | todo |
| 12 | Chicago, IL | Building violations + vacant building registrations | data.cityofchicago.org | todo |
| 13 | Memphis / Shelby County, TN | Code enforcement + Shelby County Trustee delinquent taxes | data.memphistn.gov | todo |
| 14 | Cleveland, OH | Code violations + Cuyahoga County delinquent tax list | data.clevelandohio.gov | todo |
| 15 | Socrata cities already listed in `property-recon-SKILL.md` (New Orleans, LA, SF, Buffalo, Seattle) | Code violations | data.nola.gov, data.lacity.org, data.sfgov.org, data.buffalony.gov, data.seattle.gov | todo |

## Ideas to evaluate (not yet scoped)

- USPS vacancy data (HUD aggregates are free but tract-level only)
- Utility shutoff or water-meter-off lists where cities publish them
- Eviction filings via JP courts (useful for tired-landlord leads)
- Lis pendens filings in county clerk records

## Done

_(the daily run moves finished items here with a one-line note)_
