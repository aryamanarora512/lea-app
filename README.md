# LEA Target Screener

A tool for a private-equity deal team acquiring personal-injury law firms. A
non-technical reviewer drops an incoming firm's messy Excel files, the pipeline
cleans and loads them, and the app shows — in plain language — whether the
firm's data looks anomalous versus the existing portfolio, with a clear "what to
investigate" list.

Runs locally on synthetic data with zero setup; the same code deploys to the
cloud against a real database by changing one connection string.

## How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

On a Mac, double-click **Start LEA App.command** instead — it opens the app in
the browser. That is the only thing an end user needs to do. On first launch the
app seeds a synthetic 12-firm portfolio and two demo targets, so there is
something to screen immediately.

## The three screens

- **🎯 Screen an incoming firm** (home) — the deal-team screen. Pick a target;
  see a red/amber/green verdict, a plain-language summary of what to
  investigate, and every metric plotted against the portfolio range. No SQL, no
  statistics knowledge required.
- **📥 Load new data** — the drag-and-drop Excel loader (below). Loading a firm
  here makes it immediately screenable on the home page.
- **📊 Portfolio baseline** — the firms every target is compared against, plus a
  validation report (detection rate vs false-positive rate) so you can judge how
  much to trust a flag.

## How the anomaly detection works — and why it's honest about small samples

The portfolio is small (fewer than ten real firms today), and the method is
built to be truthful about that rather than to look sophisticated:

- **When there are enough firms** (≥ 8), each metric uses a robust outlier score
  — **median + MAD** (median absolute deviation), *not* mean and standard
  deviation. A single extreme firm — the very thing being hunted — corrupts the
  mean and inflates the standard deviation, letting the outlier hide itself. The
  median barely moves.
- **When firms are few**, a z-score would be statistical theatre. The app falls
  back to a distribution-free statement — *"below all 8 of our firms"* — which
  is exactly the honest thing a partner can act on.
- **No data is never zero.** A metric with no source file (office count today)
  is shown greyed out and excluded, never guessed.
- Every flag carries its sample size, so nothing is presented as more certain
  than the data supports.

The **validation harness** (on the Portfolio baseline page) leaves each firm
out, perturbs a metric by a known amount, and measures how often the detector
catches it — reported next to the false-positive rate on untouched firms, so
sensitivity can be tuned to a target (~5% FPR) to avoid alert fatigue.

## The optional AI layer — and why it can't fabricate numbers

The plain-language summary runs deterministically with no API key. Turning on
the AI toggle asks Claude Haiku to phrase the **same computed numbers** into a
paragraph — and every number in its output is checked against the allowed set
before it is shown. If a single figure doesn't trace back to the data, the AI
text is discarded and the template is used. **The statistics are always ground
truth; the model only phrases.** Cost is roughly $0.002 per summary.

---

# Data loader (the ingestion half)

Drag-and-drop ingestion of target-firm Excel files into the LEA portfolio
database. Built so a non-technical deal-team member can load a new firm's data
without touching a terminal, and so re-running is always safe.

By default the app writes to a local SQLite file (`data/lea_portfolio.db`),
which is what makes the repo runnable on sample data with no infrastructure.
To point it at the real SQL Server instance, set one environment variable:

```bash
export LEA_DB_URL="mssql+pyodbc://user:pass@host/LEA?driver=ODBC+Driver+18+for+SQL+Server"
export LEA_PII_SALT="<a long random string, kept out of source control>"
```

Nothing else changes — every query goes through SQLAlchemy.

## What happens when you drop a file

```
  Excel file
      │
      ▼
  ① fingerprint ── SHA-256 of the bytes ──► already loaded? warn, don't block
      │
      ▼
  ② probe each sheet ── find the real header row, normalise the labels
      │
      ▼
  ③ match a recipe ── by header fingerprint, not by filename or position
      │                 no match → the tab is skipped and reported, the rest load
      ▼
  ④ parse + check ── typed values, data-quality findings per row
      │
      ▼
  ⑤ REVIEW GATE ── the user sees rows, warnings, and a preview
      │              nothing has touched the database yet
      ▼
  ⑥ upsert on the natural key ──► Silver tables (the 33 from the DBML)
      │
      ▼
  ⑦ load_log + dq_result ── every load and every finding is recorded
```

## Design decisions, and why

**The DBML file is the source of truth.** `Table firms {.go` is a dbdiagram.io
export, and `lea/dbml.py` parses it into `CREATE TABLE` statements. Editing the
ERD and re-running the app propagates the change to the database, so the
diagram and the physical schema cannot drift apart.

**Natural keys, not just surrogate keys.** The DBML declares `id integer [pk]`
on most tables — a surrogate key generated fresh on every insert, which can
never detect that a row already exists. `NATURAL_KEYS` in `lea/dbml.py` adds
the business key for each table (`firm_id + employee_number`, and so on) and
becomes a unique index. This is what makes loading **idempotent**: verified by
loading every sample file three times and confirming identical row counts.

**Content hashing for duplicate detection.** Hashing the file bytes rather
than the filename means `Copy of closed_cases.xlsx` and `closed_cases (1).xlsx`
are recognised as the same load.

**Recipes matched by header fingerprint.** A recipe claims a sheet based on the
set of normalised header tokens, not the filename, sheet position, or column
order. One recipe therefore handles all seven case-type tabs of the closed-cases
workbook, and keeps working when a firm reorders columns or changes
capitalisation. An unrecognised tab is reported and skipped — it never blocks
the tabs that *are* recognised.

**Header detection, not "row 1 is the header".** Real seller files put the
header several rows down and a column or two in, under footnotes. `lea/excel.py`
scores candidate rows on width and how textual they are, so a title banner
(one populated cell) and a totals row (numeric-heavy) both lose to the real
header. Verified against all seven sample workbooks.

**Money is `DECIMAL`, never `float`.** The DBML says `real`. Binary floating
point cannot represent 0.01 exactly, which makes footing checks fail
nondeterministically — the sample census already has four rows where
`salary + bonus ≠ total`, and those need to be real findings, not rounding
noise.

**Review before write.** Parsing produces a plan; the plan is displayed; only a
button press commits it. For a non-technical user loading data that feeds a
valuation, seeing what will happen before it happens is the whole point.

**PII is hashed at the boundary.** Employee and plaintiff names are salted-hashed
on the way in. They are not needed for any statistic the pipeline computes, and
the salt lives in an environment variable so the published version cannot
reverse them.

**Unmapped columns are reported.** When a file contains a column no recipe
consumes, that is logged as a finding. A new column is the signal that a firm's
reporting changed — silently dropping it is how pipelines rot.

## Repository layout

```
app.py                    Streamlit GUI (the four-step flow above)
lea/dbml.py               DBML → DDL; natural keys; audit columns
lea/db.py                 Engine, schema init (SQLite ⇄ SQL Server)
lea/firms.py              Firm registry, 4-digit ID minting
lea/excel.py              Header detection, fingerprinting, value coercion
lea/schema_map.py         Source vocabulary; tables missing from the DBML
lea/recipes/__init__.py   Recipe registry and matching
lea/recipes/builtin.py    One recipe per known file shape
lea/load.py               Planning, idempotent upsert, load logging
```

## Status

**Working now:** schema generation from DBML (33 tables), firm registry,
drag-and-drop GUI, five recipes covering the sample files, data-quality
findings, idempotent loading, full load audit trail.

**Next:** a recipe for the quarterly settled-cases matrix (stacked year blocks
with merged headers); manual column mapping in the GUI for unrecognised tabs,
saved as a reusable recipe; then the anomaly-detection layer.

## Known gaps in the source data

Findings that need a seller conversation, not a code change:

- The closed-case ledger has an **open date but no close date**, so case
  duration and settlement-year attribution cannot be derived from it.
- **Disposition codes** (`SET`, `DRP`, `SUB`, `INI`, `LIT`, `L-P`, `I-P`,
  `ARB`, `SRL`, `A-P`) are undocumented. `ref_disposition_code` holds inferred
  readings marked `INFERRED` — confirm before trusting any settlement rate.
- The **Top 25 Cases** workbook is an empty template in all three year tabs.
- `geo_office_overview` has **no source file**, so office count — the headline
  anomaly metric — currently has no ingestion path.
- The tools list names **Smart Advocate** as case management while the
  diligence answers name **Law Ruler** for intake; `firms.cms_platform` holds one.
- Sample files span **three deal identities** (Project Palm, Project Wolf,
  Ellis Law Corporation) in two states. Register them as separate firms.
