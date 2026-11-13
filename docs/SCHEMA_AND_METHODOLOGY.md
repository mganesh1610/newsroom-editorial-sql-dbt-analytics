# Schema, Lineage & Statistical Methodology

## 1. Public Datasets & Cryptographic Provenance

1. **UCI Online News Popularity Dataset**
   - Source: `https://archive.ics.uci.edu/static/public/332/online+news+popularity.zip`
   - Verified ZIP SHA-256: `dba2ae526f62ccef6f2f8efb53b0268319f4d0d2719bb98d88958cfe31d58a22`
   - Granularity: `39,644` published digital articles × `61` attributes spanning `724` distinct publication days (`timedelta` 8 to 731).
   - Desk Channels: `Business`, `World`, `Tech`, `Entertainment`, `Lifestyle`, `Social Media`, plus `Unassigned` multi-topic records.
   - Backup Source: Microsoft MIND News Impression Dataset (`https://msnews.github.io/`).

2. **Kevin Hillstrom MineThatData Randomized Newsletter / Multi-Channel Experiment**
   - Source: `http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv`
   - Verified CSV SHA-256: `0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece`
   - Granularity: `64,000` randomized reader assignments × `12` columns across 3 arms (`Mens E-Mail`, `Womens E-Mail`, `No E-Mail` control) and 2-week visit/conversion/spend outcomes.
   - Backup Source: AG News Topic Corpus (`https://huggingface.co/datasets/fancyzhx/ag_news`).

---

## 2. Staged dbt / SQL Model Architecture

1. `models/stg_editorial_articles.sql`:
   - Casts raw CSV attributes into typed SQL fields, converts `timedelta` into chronological `pub_day_seq = 731 - timedelta`, maps mutually exclusive channel flags into `editorial_desk`, and computes four deterministic data-quality flags:
     - `flag_zero_body_parser_defect`: detects HTML body extraction failures (`n_tokens_content = 0`).
     - `flag_missing_desk_taxonomy`: detects articles missing all six canonical topic channel tags.
     - `flag_multi_desk_collision`: asserts mutually exclusive desk taxonomy (`desk_flag_sum <= 1`).
     - `flag_invalid_weekday_flag`: enforces exactly one publication weekday indicator per article.
2. `models/int_editorial_spike_events.sql`:
   - Computes strict causal trailing 14-day desk baseline (`ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING`) and flags performance spikes with `rolling_14d_zscore >= 2.0`.
3. `models/fct_editorial_desk_daily.sql`:
   - Materializes self-serve BI metrics consumed by `lookml/editorial_audience_performance.view.lkml` and the interactive HTML dashboard.

---

## 3. Mathematical & Statistical Formulations

1. **Rolling 14-Day Traffic Spike Z-Score:**
   $$z_{d,t} = \frac{\bar{Y}_{d,t} - \mu_{d, t-14:t-1}}{\sigma_{d, t-14:t-1}}, \quad Y = \ln(1 + \text{shares})$$
2. **Weekday vs. Weekend Welch's Two-Sample t-Test:**
   $$t = \frac{\bar{Y}_{\text{weekend}} - \bar{Y}_{\text{weekday}}}{\sqrt{\frac{s_1^2}{n_1} + \frac{s_2^2}{n_2}}}$$
3. **L2-Regularized Ridge Driver Decomposition ($\lambda = 10.0$):**
   $$\hat{\beta} = (X^\top X + \lambda I)^{-1} X^\top y$$
   evaluated on standardized content features (`title_word_count`, `body_word_count`, `image_count`, `video_count`, `internal_link_count`, `avg_keyword_share_velocity`, `title_subjectivity`) excluding `flag_zero_body_parser_defect = 1` records.
4. **A/B Experimentation (SRM, Balance, Wilson-Newcombe CI, Holm-Bonferroni):**
   - Sample Ratio Mismatch check via Pearson $\chi^2$ across 3 arms (`1/3` expected allocation).
   - Pre-treatment Standardized Mean Difference (`SMD`) across `history` and `recency`.
   - Two-proportion $Z$-test, Wilson score 95% confidence intervals, and step-down Holm-Bonferroni adjusted $p$-values across treatment contrasts.

---

## 4. Read-Only AI SQL & Shared Glossary Utility

`src/ai_sql_glossary_assistant.py` translates 20 canonical partner prompts into parameterized SQLite queries guarded by a strict read-only AST/token validator rejecting `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `PRAGMA`, and multi-statement queries (`;`), and exports `outputs/shared_metric_glossary.json`.
