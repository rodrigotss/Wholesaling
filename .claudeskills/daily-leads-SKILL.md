---
name: daily-leads
description: "The unattended daily run: add 15 new, de-duplicated leads to the Sol Acquisitions monday board, hand the user a skip-trace file, then spend the rest of the run adding one new free lead source or U.S. market from docs/expansion-backlog.md. Use when a scheduled task or the user says 'daily leads' / 'run the daily'."
---

# Daily Leads Runbook

Runs once a day from a scheduled task, in a fresh cloud session, with nobody
watching. Be conservative: never delete or edit existing board items, never
contact anyone, never invent data.

---

## 0. Setup (fresh session)

1. Repo: if `pipeline/` is missing, clone `rodrigotss/Wholesaling` and check
   out branch `claude/new-session-42n4br`. Work on that branch only.
2. Data: `data/` and `deals/leads/` are gitignored, so a fresh session has
   none. Build the database (about 2 minutes, ~450 MB download):
   ```bash
   python3 pipeline/build_dallas_db.py
   ```
   If a download fails after its retries, say which host failed in the
   report and continue with whatever markets do work.

## 1. Read the board (de-duplication)

Board config: `pipeline/sol_board.json` (board 18437049281, group
"1. Lead & Acquisition"). Read **every** item name on the board, all groups
(dead and closed deals too), with monday `get_board_items_page`
(`includeColumns: false`, `limit: 500`, page with the cursor). Write the names, one per line, to
`out/existing.txt`.

## 2. Pick 15 new leads

```bash
python3 pipeline/next_leads.py --exclude out/existing.txt --count 15 --out out/
```

Read `out/summary.md` and sanity-check every pick before writing:
- Drop churches, businesses, government, and anything where back taxes are
  more than half the value. The script filters these, but check the names.
- If fewer than 15 qualify, add what qualifies and say so. Never pad.

## 3. Write to monday

`create_items` on the board with `out/monday_items.json` (≤ 20 per call).
Confirm `created == total`. If the board's columns changed, re-read them
with `get_board_info`, fix `pipeline/sol_board.json`, and retry once.

## 4. Hand off the skip-trace file

Copy `out/skiptrace.csv` to `deals/leads/skiptrace-YYYY-MM-DD.csv` and send
it with `SendUserFile` (`status: "proactive"`, `display: "attach"`). Lead
files contain names and addresses, so **never commit them** (they are
gitignored) and never post them anywhere except the user's monday board and
this file hand-off.

## 5. Improve: one backlog item per day

Open `docs/expansion-backlog.md`, take the highest-priority item marked
`todo`, and try to finish it in this run:

1. Confirm the source is **official and free**: a government open-data
   portal, appraisal district or tax-office bulk file, or a court or clerk
   public search. No scraping of Zillow, Redfin or people-search sites,
   nothing behind a login, and no ignoring a site's terms or robots rules.
2. Probe it with a small request. If the network policy blocks the host
   (proxy 403 / "no rule allows host"), mark the item
   `blocked: needs host <name>`, and list the host in the report so the
   user can allow it. Don't try to work around the block.
3. Build it the same way as the Dallas pipeline: a loader into SQLite
   and signals scored in `find_leads.py` (or a new `pipeline/<market>.py`
   with the same output shape). Test it on one ZIP or neighborhood.
4. Update the backlog item (`done` + one line of what was learned) and
   `docs/wholesale-lead-research.md` if a new source type was found.
5. Commit with a clear message and `git push -u origin claude/new-session-42n4br`.

Once a new market works, the next day's 15 can include its leads. Put the
city and state in the item name.

## 6. Report (keep it short; the user reads it on a phone)

```
DAILY LEADS — Nov 8 2026
Added 15 to Sol Acquisitions (board total 60). Top: 637 Dogwood Trl (100) …
Skip-trace file attached → upload, then send me the results.
Improved: <backlog item> — done / blocked (needs host X) / partial
Needs you: <hosts to allow, or nothing>
```
