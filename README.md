# Digital Editorial & Audience SQL, dbt, Self-Serve BI & Experimentation Engine

A reproducible analytics engineering, self-serve BI, data quality troubleshooting, and experimentation showcase built with **SQL (`SQL Joins & CTEs`, Window Functions)**, **dbt / BigQuery-compatible models**, **Looker LookML**, **Python**, and **read-only AI SQL glossary tooling** across **103,644 SHA-256-verified public records**.

---

## Key Capabilities & Verified Results

| Analytical Workstream | Verified Public Scale | Key Quantitative Outputs |
| :--- | :--- | :--- |
| **Staged SQL & dbt Editorial Marts** | **39,644** articles across **724** publication days & **6** topic desks | **14/14 (`100%`)** automated SQL & LookML data-quality gates passed; exact share and article parity across staging and `fct_editorial_desk_daily` |
| **Source Instrumentation & Taxonomy QA** | **39,644** staged HTML/channel attributes | Isolated **1,181** zero-body parser defects (`n_tokens_content = 0`) and **6,134** unassigned desk taxonomy records prior to BI refresh |
| **News Event Traffic-Spike Deep-Dives** | **724** active days (`14`-day causal trailing baseline) | Detected **298** desk-days exceeding `>= 2.0 SD` trailing mean; weekend stories outperformed weekdays (Welch $t = 24.21$, $p = 1.58 \times 10^{-129}$); L2 Ridge driver decomposition (`RMSE = 0.8598`) |
| **Multi-Arm Reader Newsletter A/B Analysis** | **64,000** randomized assignments (`3` arms) | SRM check passed ($\chi^2 = 0.2025$, $p = 0.9037$); **+57.35%** relative visit lift ($Z = 20.51$, Holm $p = 3.50 \times 10^{-93}$) & **+86.53%** conversion lift ($Z = 6.24$, Holm $p = 8.54 \times 10^{-10}$) |
| **Read-Only AI SQL & Shared Glossary Utility** | **20** canonical partner analytics prompts | **20/20** LookML/SQL queries validated read-only (`SELECT`/`WITH` AST guardrail blocking DDL/DML) and verified non-empty against SQLite |

---

## Architecture & Repository Layout

```text
├── models/
│   ├── stg_editorial_articles.sql         # Typed staging, chronological day index, defect flags
│   ├── int_editorial_spike_events.sql     # Causal 14-day trailing rolling z-score spike detection
│   └── fct_editorial_desk_daily.sql       # Self-serve daily desk BI mart
├── sql/
│   └── ad_hoc_partner_patterns.sql        # Reusable editorial, audience & product partner SQL patterns
├── lookml/
│   └── editorial_audience_performance.view.lkml  # Governed Looker LookML semantic view
├── src/
│   ├── editorial_analytics_pipeline.py    # End-to-end download, SHA-256 verify, SQLite dbt runner, stats & BI
│   └── ai_sql_glossary_assistant.py       # Read-only LLM SQL guardrail & 20-metric shared glossary suite
├── dashboards/
│   └── editorial_self_serve_dashboard.html # Standalone interactive desk & A/B scorecard
├── outputs/
│   ├── validation_summary.json            # Full machine-verified results & 14/14 DQ gates
│   ├── desk_kpi_scorecard.csv             # Editorial desk KPI summary
│   ├── traffic_spike_events.csv           # 298 flagged 2-sigma spike events
│   ├── newsletter_ab_results.csv          # SRM, Newcombe 95% CIs & Holm-Bonferroni p-values
│   └── shared_metric_glossary.json        # 20 validated LookML-linked SQL metrics
├── docs/
│   └── SCHEMA_AND_METHODOLOGY.md          # Mathematical formulations, lineage & dataset provenance
└── tests/
    └── test_editorial_analytics.py        # Unit, boundary, SQL safety & repo hygiene tests
```

---

## Primary & Backup Public Datasets

1. **UCI Online News Popularity Dataset:** `https://archive.ics.uci.edu/static/public/332/online+news+popularity.zip` (`39,644` articles × `61` attributes; ZIP SHA-256 `dba2ae526f62ccef6f2f8efb53b0268319f4d0d2719bb98d88958cfe31d58a22`).
2. **Kevin Hillstrom MineThatData Randomized Email Experiment:** `http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv` (`64,000` randomized assignments × `12` attributes; CSV SHA-256 `0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece`).
3. **Documented Backup Sources:** Microsoft MIND News Impression Dataset (`https://msnews.github.io/`) and AG News Topic Corpus (`https://huggingface.co/datasets/fancyzhx/ag_news`).

---

## Quick Reproduction

```bash
python3 -m src.editorial_analytics_pipeline
python3 -m unittest discover -s tests -v
```
