"""End-to-end Digital Editorial & Audience SQL, dbt, BI & Experimentation Pipeline.

Ingests SHA-256-verified public editorial article telemetry (UCI Online News Popularity)
and randomized multi-arm reader newsletter experiment data (Kevin Hillstrom MineThatData),
executes BigQuery/dbt-compatible SQL models in SQLite, audits source instrumentation
defects, evaluates rolling 14-day traffic spikes and Ridge engagement drivers, performs
SRM-checked A/B hypothesis testing, validates 20 read-only AI SQL glossary queries, and
emits governed self-serve dashboard and validation artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.ai_sql_glossary_assistant import run_glossary_suite

NEWS_ZIP_URL = "https://archive.ics.uci.edu/static/public/332/online+news+popularity.zip"
NEWS_ZIP_SHA256 = "dba2ae526f62ccef6f2f8efb53b0268319f4d0d2719bb98d88958cfe31d58a22"
HILLSTROM_CSV_URL = (
    "http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
)
HILLSTROM_CSV_SHA256 = "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece"


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file using buffered reads."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_verified_download(
    url: str,
    dest: Path,
    expected_sha256: Optional[str],
    verify_hash: bool = True,
) -> str:
    """Download file if missing and verify its SHA-256 checksum."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "EditorialAnalyticsPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
    actual_sha = sha256_file(dest)
    if verify_hash and expected_sha256 and actual_sha != expected_sha256:
        raise ValueError(f"Checksum mismatch for {dest.name}: expected {expected_sha256}, got {actual_sha}")
    return actual_sha


def normal_two_sided_p(z_abs: float) -> float:
    """Two-sided p-value under standard normal distribution."""
    return math.erfc(abs(z_abs) / math.sqrt(2.0))


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """Compute Wilson score 95% confidence interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * total)) / total)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def newcombe_diff_ci(s1: int, n1: int, s0: int, n0: int) -> Tuple[float, float]:
    """Compute Newcombe-Wilson 95% confidence interval for p1 - p0."""
    l1, u1 = wilson_ci(s1, n1)
    l0, u0 = wilson_ci(s0, n0)
    p1 = s1 / n1
    p0 = s0 / n0
    diff = p1 - p0
    lower = diff - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)
    upper = diff + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)
    return lower, upper


def solve_linear_system(matrix: List[List[float]], rhs: List[float]) -> List[float]:
    """Solve Ax = b using Gaussian elimination with partial pivoting."""
    n = len(rhs)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-12:
            raise ValueError("Singular matrix encountered in Ridge solver.")
        factor = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= factor
        for r in range(n):
            if r != col and abs(aug[r][col]) > 0.0:
                mult = aug[r][col]
                for j in range(col, n + 1):
                    aug[r][j] -= mult * aug[col][j]
    return [aug[i][n] for i in range(n)]


def fit_ridge_drivers(conn: sqlite3.Connection, l2_lambda: float = 10.0) -> Dict[str, Any]:
    """Fit L2-regularized Ridge regression predicting log1p(shares) on clean staged articles."""
    feature_names = [
        "title_word_count",
        "body_word_count",
        "image_count",
        "video_count",
        "internal_link_count",
        "avg_keyword_share_velocity",
        "title_subjectivity",
    ]
    rows = conn.execute(
        f"""
        SELECT {', '.join(feature_names)}, log1p_shares
        FROM stg_editorial_articles
        WHERE flag_zero_body_parser_defect = 0
        ORDER BY pub_day_seq, article_url
        """
    ).fetchall()
    if len(rows) < 25:
        return {"sample_size": len(rows), "holdout_rmse": 0.0, "holdout_r2": 0.0, "feature_betas": {}}

    split_idx = int(len(rows) * 0.8)
    train_rows = rows[:split_idx]
    test_rows = rows[split_idx:]

    k = len(feature_names)
    means = [sum(r[j] for r in train_rows) / len(train_rows) for j in range(k)]
    stds = []
    for j in range(k):
        var = sum((r[j] - means[j]) ** 2 for r in train_rows) / max(1, len(train_rows) - 1)
        stds.append(math.sqrt(var) if var > 1e-12 else 1.0)

    y_mean = sum(r[k] for r in train_rows) / len(train_rows)

    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for r in train_rows:
        z = [(r[j] - means[j]) / stds[j] for j in range(k)]
        y_c = r[k] - y_mean
        for i in range(k):
            xty[i] += z[i] * y_c
            for j in range(k):
                xtx[i][j] += z[i] * z[j]
    for i in range(k):
        xtx[i][i] += l2_lambda

    betas = solve_linear_system(xtx, xty)

    preds = []
    actuals = []
    for r in test_rows:
        z = [(r[j] - means[j]) / stds[j] for j in range(k)]
        y_hat = y_mean + sum(betas[j] * z[j] for j in range(k))
        preds.append(y_hat)
        actuals.append(r[k])

    mse = sum((a - p) ** 2 for a, p in zip(actuals, preds)) / len(actuals)
    act_mean = sum(actuals) / len(actuals)
    sst = sum((a - act_mean) ** 2 for a in actuals)
    sse = sum((a - p) ** 2 for a, p in zip(actuals, preds))
    r2 = 1.0 - (sse / sst) if sst > 1e-12 else 0.0

    return {
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "l2_lambda": l2_lambda,
        "holdout_rmse": round(math.sqrt(mse), 4),
        "holdout_r2": round(r2, 4),
        "feature_betas": {name: round(b, 4) for name, b in zip(feature_names, betas)},
    }


def compute_welch_weekend_test(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Run Welch two-sample t-test comparing weekend vs weekday log1p(shares)."""
    wk_vals = [
        r[0]
        for r in conn.execute("SELECT log1p_shares FROM stg_editorial_articles WHERE is_weekend = 1").fetchall()
    ]
    wd_vals = [
        r[0]
        for r in conn.execute("SELECT log1p_shares FROM stg_editorial_articles WHERE is_weekend = 0").fetchall()
    ]
    n1, n0 = len(wk_vals), len(wd_vals)
    m1 = sum(wk_vals) / max(1, n1)
    m0 = sum(wd_vals) / max(1, n0)
    v1 = sum((x - m1) ** 2 for x in wk_vals) / max(1, n1 - 1)
    v0 = sum((x - m0) ** 2 for x in wd_vals) / max(1, n0 - 1)
    se = math.sqrt((v1 / max(1, n1)) + (v0 / max(1, n0)))
    t_stat = (m1 - m0) / se if se > 1e-12 else 0.0
    return {
        "weekend_articles": n1,
        "weekday_articles": n0,
        "weekend_mean_log1p": round(m1, 4),
        "weekday_mean_log1p": round(m0, 4),
        "weekend_geometric_mean_shares": round(math.expm1(m1), 2),
        "weekday_geometric_mean_shares": round(math.expm1(m0), 2),
        "welch_t_stat": round(t_stat, 4),
        "p_value": float(f"{normal_two_sided_p(t_stat):.6e}"),
    }


def analyze_newsletter_experiment(conn: sqlite3.Connection, csv_out: Path) -> Dict[str, Any]:
    """Compute 3-arm SRM chi-square, covariate SMD balance, Z-tests, and Holm-Bonferroni p-values."""
    arms = conn.execute(
        """
        SELECT segment, COUNT(*) AS n, SUM(visit) AS visits, SUM(conversion) AS convs,
               SUM(spend) AS total_spend, AVG(history) AS mean_history,
               SUM((history - (SELECT AVG(history) FROM raw_newsletter_experiment)) *
                   (history - (SELECT AVG(history) FROM raw_newsletter_experiment))) / COUNT(*) AS var_history,
               AVG(recency) AS mean_recency
        FROM raw_newsletter_experiment
        GROUP BY segment
        """
    ).fetchall()
    arm_map = {row[0]: row for row in arms}
    total_n = sum(row[1] for row in arms)
    expected_per_arm = total_n / 3.0
    chi2_srm = sum(((row[1] - expected_per_arm) ** 2) / expected_per_arm for row in arms)
    # P(chi2_2 >= x) = exp(-x / 2)
    srm_p = math.exp(-chi2_srm / 2.0)

    ctrl = arm_map["No E-Mail"]
    c_n, c_vis, c_conv, c_spend, c_hist, c_hist_var, c_rec = ctrl[1], ctrl[2], ctrl[3], ctrl[4], ctrl[5], ctrl[6], ctrl[7]

    contrasts_raw: List[Dict[str, Any]] = []
    comparisons = [
        ("Mens E-Mail vs No E-Mail", arm_map["Mens E-Mail"][1], arm_map["Mens E-Mail"][2], arm_map["Mens E-Mail"][3], arm_map["Mens E-Mail"][4], arm_map["Mens E-Mail"][5], arm_map["Mens E-Mail"][6], arm_map["Mens E-Mail"][7]),
        ("Womens E-Mail vs No E-Mail", arm_map["Womens E-Mail"][1], arm_map["Womens E-Mail"][2], arm_map["Womens E-Mail"][3], arm_map["Womens E-Mail"][4], arm_map["Womens E-Mail"][5], arm_map["Womens E-Mail"][6], arm_map["Womens E-Mail"][7]),
    ]
    comb_n = arm_map["Mens E-Mail"][1] + arm_map["Womens E-Mail"][1]
    comb_vis = arm_map["Mens E-Mail"][2] + arm_map["Womens E-Mail"][2]
    comb_conv = arm_map["Mens E-Mail"][3] + arm_map["Womens E-Mail"][3]
    comb_spend = arm_map["Mens E-Mail"][4] + arm_map["Womens E-Mail"][4]
    comb_hist = (arm_map["Mens E-Mail"][5] * arm_map["Mens E-Mail"][1] + arm_map["Womens E-Mail"][5] * arm_map["Womens E-Mail"][1]) / comb_n
    comb_rec = (arm_map["Mens E-Mail"][7] * arm_map["Mens E-Mail"][1] + arm_map["Womens E-Mail"][7] * arm_map["Womens E-Mail"][1]) / comb_n
    comparisons.append(
        ("Combined Newsletter vs No E-Mail", comb_n, comb_vis, comb_conv, comb_spend, comb_hist, c_hist_var, comb_rec)
    )

    for label, t_n, t_vis, t_conv, t_spend, t_hist, t_hist_var, t_rec in comparisons:
        p1_vis, p0_vis = t_vis / t_n, c_vis / c_n
        p_pool_vis = (t_vis + c_vis) / (t_n + c_n)
        se_vis = math.sqrt(p_pool_vis * (1.0 - p_pool_vis) * (1.0 / t_n + 1.0 / c_n))
        z_vis = (p1_vis - p0_vis) / se_vis if se_vis > 0 else 0.0
        p_vis = normal_two_sided_p(z_vis)
        ci_l_vis, ci_u_vis = newcombe_diff_ci(t_vis, t_n, c_vis, c_n)

        p1_conv, p0_conv = t_conv / t_n, c_conv / c_n
        p_pool_conv = (t_conv + c_conv) / (t_n + c_n)
        se_conv = math.sqrt(p_pool_conv * (1.0 - p_pool_conv) * (1.0 / t_n + 1.0 / c_n))
        z_conv = (p1_conv - p0_conv) / se_conv if se_conv > 0 else 0.0
        p_conv = normal_two_sided_p(z_conv)
        ci_l_conv, ci_u_conv = newcombe_diff_ci(t_conv, t_n, c_conv, c_n)

        pooled_hist_sd = math.sqrt(max(1e-9, (t_hist_var + c_hist_var) / 2.0))
        smd_history = abs(t_hist - c_hist) / pooled_hist_sd

        contrasts_raw.append(
            {
                "contrast": label,
                "treatment_n": t_n,
                "control_n": c_n,
                "treatment_visit_rate_pct": round(p1_vis * 100.0, 4),
                "control_visit_rate_pct": round(p0_vis * 100.0, 4),
                "visit_abs_lift_pp": round((p1_vis - p0_vis) * 100.0, 4),
                "visit_rel_lift_pct": round(((p1_vis - p0_vis) / max(1e-9, p0_vis)) * 100.0, 2),
                "visit_newcombe_95ci_pp": [round(ci_l_vis * 100.0, 4), round(ci_u_vis * 100.0, 4)],
                "visit_z": round(z_vis, 4),
                "visit_p_raw": p_vis,
                "treatment_conv_rate_pct": round(p1_conv * 100.0, 4),
                "control_conv_rate_pct": round(p0_conv * 100.0, 4),
                "conv_abs_lift_pp": round((p1_conv - p0_conv) * 100.0, 4),
                "conv_rel_lift_pct": round(((p1_conv - p0_conv) / max(1e-9, p0_conv)) * 100.0, 2),
                "conv_newcombe_95ci_pp": [round(ci_l_conv * 100.0, 4), round(ci_u_conv * 100.0, 4)],
                "conv_z": round(z_conv, 4),
                "conv_p_raw": p_conv,
                "smd_history": round(smd_history, 4),
                "recency_diff": round(abs(t_rec - c_rec), 4),
            }
        )

    # Holm-Bonferroni adjustment across the 3 visit tests and 3 conversion tests separately
    for metric_key in ("visit", "conv"):
        indexed = sorted(enumerate(contrasts_raw), key=lambda item: item[1][f"{metric_key}_p_raw"])
        m = len(indexed)
        running_max = 0.0
        for rank, (orig_idx, item) in enumerate(indexed):
            adj = min(1.0, (m - rank) * item[f"{metric_key}_p_raw"])
            running_max = max(running_max, adj)
            contrasts_raw[orig_idx][f"{metric_key}_p_holm"] = float(f"{running_max:.6e}")
            contrasts_raw[orig_idx][f"{metric_key}_p_raw"] = float(f"{item[f'{metric_key}_p_raw']:.6e}")

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(contrasts_raw[0].keys())
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in contrasts_raw:
            writer.writerow(row)

    return {
        "total_assignments": total_n,
        "srm_chi2": round(chi2_srm, 4),
        "srm_p_value": round(srm_p, 4),
        "srm_passed": srm_p > 0.01,
        "contrasts": contrasts_raw,
    }


def load_datasets_to_sqlite(
    conn: sqlite3.Connection,
    news_csv_text: str,
    hillstrom_csv_text: str,
) -> Tuple[int, int]:
    """Load raw editorial and newsletter CSV datasets into SQLite tables."""
    news_reader = csv.DictReader(io.StringIO(news_csv_text))
    assert news_reader.fieldnames is not None
    cleaned_headers = [h.strip() for h in news_reader.fieldnames]
    news_reader.fieldnames = cleaned_headers

    # Normalize UCI's upstream typo 'self_reference_avg_sharess' -> 'self_reference_avg_shares'
    db_columns = ["self_reference_avg_shares" if c == "self_reference_avg_sharess" else c for c in cleaned_headers]
    col_defs = ", ".join(f'"{c}" TEXT' if c == "url" else f'"{c}" REAL' for c in db_columns)
    conn.execute("DROP TABLE IF EXISTS raw_editorial_articles")
    conn.execute(f"CREATE TABLE raw_editorial_articles ({col_defs})")

    placeholders = ", ".join("?" for _ in db_columns)
    insert_news_sql = f"INSERT INTO raw_editorial_articles VALUES ({placeholders})"
    news_batch = []
    for row in news_reader:
        vals = [row["url"].strip()]
        for c in cleaned_headers[1:]:
            vals.append(float(row[c].strip()))
        news_batch.append(tuple(vals))
    conn.executemany(insert_news_sql, news_batch)

    hill_reader = csv.DictReader(io.StringIO(hillstrom_csv_text))
    conn.execute("DROP TABLE IF EXISTS raw_newsletter_experiment")
    conn.execute(
        """
        CREATE TABLE raw_newsletter_experiment (
            recency INTEGER,
            history_segment TEXT,
            history REAL,
            mens INTEGER,
            womens INTEGER,
            zip_code TEXT,
            newbie INTEGER,
            channel TEXT,
            segment TEXT,
            visit INTEGER,
            conversion INTEGER,
            spend REAL
        )
        """
    )
    hill_batch = [
        (
            int(r["recency"]),
            r["history_segment"].strip(),
            float(r["history"]),
            int(r["mens"]),
            int(r["womens"]),
            r["zip_code"].strip(),
            int(r["newbie"]),
            r["channel"].strip(),
            r["segment"].strip(),
            int(r["visit"]),
            int(r["conversion"]),
            float(r["spend"]),
        )
        for r in hill_reader
    ]
    conn.executemany(
        "INSERT INTO raw_newsletter_experiment VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        hill_batch,
    )
    conn.commit()
    return len(news_batch), len(hill_batch)


def execute_sql_models(conn: sqlite3.Connection, models_dir: Path) -> None:
    """Register math functions and materialize staging, spike, and BI mart tables from SQL files."""
    conn.create_function("LN", 1, lambda x: math.log(x) if x and x > 0 else 0.0)
    conn.create_function("SQRT", 1, lambda x: math.sqrt(max(0.0, x)) if x is not None else 0.0)

    for table_name, sql_file in (
        ("stg_editorial_articles", models_dir / "stg_editorial_articles.sql"),
        ("int_editorial_spike_events", models_dir / "int_editorial_spike_events.sql"),
        ("fct_editorial_desk_daily", models_dir / "fct_editorial_desk_daily.sql"),
    ):
        select_sql = sql_file.read_text(encoding="utf-8").strip().rstrip(";")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(f"CREATE TABLE {table_name} AS {select_sql}")
    conn.commit()


def run_data_quality_gates(conn: sqlite3.Connection, lookml_path: Path, raw_news_n: int, raw_hill_n: int) -> List[Dict[str, Any]]:
    """Run 14 automated SQL, schema, instrumentation, and LookML parity checks."""
    stg_n = conn.execute("SELECT COUNT(*) FROM stg_editorial_articles").fetchone()[0]
    uniq_urls = conn.execute("SELECT COUNT(DISTINCT article_url) FROM stg_editorial_articles").fetchone()[0]
    nonpos_shares = conn.execute("SELECT COUNT(*) FROM stg_editorial_articles WHERE shares <= 0").fetchone()[0]
    multi_desk = conn.execute("SELECT SUM(flag_multi_desk_collision) FROM stg_editorial_articles").fetchone()[0]
    bad_weekday = conn.execute("SELECT SUM(flag_invalid_weekday_flag) FROM stg_editorial_articles").fetchone()[0]
    zero_body = conn.execute("SELECT SUM(flag_zero_body_parser_defect) FROM stg_editorial_articles").fetchone()[0]
    missing_tax = conn.execute("SELECT SUM(flag_missing_desk_taxonomy) FROM stg_editorial_articles").fetchone()[0]
    mart_articles, mart_shares = conn.execute(
        "SELECT SUM(published_articles), SUM(total_shares) FROM fct_editorial_desk_daily"
    ).fetchone()
    stg_shares = conn.execute("SELECT SUM(shares) FROM stg_editorial_articles").fetchone()[0]
    day_min, day_max = conn.execute("SELECT MIN(pub_day_seq), MAX(pub_day_seq) FROM stg_editorial_articles").fetchone()
    hill_n = conn.execute("SELECT COUNT(*) FROM raw_newsletter_experiment").fetchone()[0]
    hill_invalid = conn.execute(
        "SELECT COUNT(*) FROM raw_newsletter_experiment "
        "WHERE visit NOT IN (0, 1) OR conversion NOT IN (0, 1) OR spend < 0"
    ).fetchone()[0]
    arms = conn.execute("SELECT COUNT(*) FROM raw_newsletter_experiment GROUP BY segment").fetchall()
    total_arm = sum(a[0] for a in arms)
    exp_arm = total_arm / max(1, len(arms))
    chi2 = sum(((a[0] - exp_arm) ** 2) / max(1.0, exp_arm) for a in arms)
    srm_p = math.exp(-chi2 / 2.0)

    lookml_text = lookml_path.read_text(encoding="utf-8")
    expected_lookml_fields = (
        "pub_day_seq",
        "editorial_desk",
        "publish_weekday",
        "is_weekend",
        "is_traffic_spike_2sigma",
        "published_articles",
        "total_shares",
        "high_velocity_articles",
        "zero_body_defect_count",
        "missing_taxonomy_count",
    )
    lookml_ok = all(f in lookml_text for f in expected_lookml_fields)

    gates = [
        {"gate_id": "DQ01_raw_to_staging_conservation", "passed": stg_n == raw_news_n, "observed": stg_n, "expected": raw_news_n},
        {"gate_id": "DQ02_unique_article_url", "passed": uniq_urls == stg_n, "observed": uniq_urls, "expected": stg_n},
        {"gate_id": "DQ03_positive_share_counts", "passed": nonpos_shares == 0, "observed": nonpos_shares, "expected": 0},
        {"gate_id": "DQ04_mutually_exclusive_desk_flags", "passed": multi_desk == 0, "observed": multi_desk, "expected": 0},
        {"gate_id": "DQ05_single_weekday_flag_invariant", "passed": bad_weekday == 0, "observed": bad_weekday, "expected": 0},
        {"gate_id": "DQ06_zero_body_parser_defect_isolated", "passed": zero_body >= 0 and zero_body < stg_n, "observed": zero_body, "expected": "Flagged isolated subset"},
        {"gate_id": "DQ07_unassigned_taxonomy_isolated", "passed": missing_tax >= 0 and missing_tax < stg_n, "observed": missing_tax, "expected": "Flagged isolated subset"},
        {"gate_id": "DQ08_mart_article_conservation", "passed": mart_articles == stg_n, "observed": mart_articles, "expected": stg_n},
        {"gate_id": "DQ09_mart_total_shares_parity", "passed": mart_shares == stg_shares, "observed": mart_shares, "expected": stg_shares},
        {"gate_id": "DQ10_pub_day_sequence_non_negative", "passed": day_min >= 0 and day_max >= day_min, "observed": [day_min, day_max], "expected": "Non-negative ordered horizon"},
        {"gate_id": "DQ11_newsletter_row_conservation", "passed": hill_n == raw_hill_n, "observed": hill_n, "expected": raw_hill_n},
        {"gate_id": "DQ12_newsletter_outcome_domain_valid", "passed": hill_invalid == 0, "observed": hill_invalid, "expected": 0},
        {"gate_id": "DQ13_newsletter_srm_balance", "passed": srm_p > 0.01, "observed": round(srm_p, 4), "expected": "> 0.01"},
        {"gate_id": "DQ14_lookml_semantic_coverage", "passed": lookml_ok, "observed": len(expected_lookml_fields), "expected": len(expected_lookml_fields)},
    ]
    return gates


def build_self_serve_dashboard(
    desk_rows: List[Dict[str, Any]],
    ab_summary: Dict[str, Any],
    summary: Dict[str, Any],
    out_html: Path,
) -> None:
    """Emit a standalone interactive HTML self-serve editorial BI dashboard."""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    desk_json = json.dumps(desk_rows)
    ab_json = json.dumps(ab_summary["contrasts"])
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Editorial &amp; Audience Self-Serve BI Scorecard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; margin: 28px; color: #1f2933; background: #f8fafc; }}
  h1 {{ color: #173B55; margin-bottom: 4px; }}
  .sub {{ color: #52606d; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 14px; margin-bottom: 22px; }}
  .card {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 14px; }}
  .kpi-val {{ font-size: 24px; font-weight: 700; color: #173B55; }}
  .kpi-lbl {{ font-size: 12px; color: #616e7c; text-transform: uppercase; letter-spacing: 0.4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; margin-bottom: 24px; border: 1px solid #d9e2ec; }}
  th, td {{ padding: 9px 12px; border-bottom: 1px solid #e4e7eb; text-align: left; font-size: 13px; }}
  th {{ background: #173B55; color: #fff; }}
  select {{ padding: 6px 10px; border: 1px solid #cbd2d9; border-radius: 6px; margin-bottom: 12px; }}
</style>
</head>
<body>
<h1>Editorial &amp; Audience Self-Serve BI Scorecard</h1>
<div class="sub">SQL &amp; dbt Warehouse Summary across {summary['total_combined_records']:,} Verified Records ({summary['dq_gates_passed']}/{summary['dq_gates_total']} DQ Gates Passed)</div>
<div class="grid">
  <div class="card"><div class="kpi-val">{summary['editorial_articles']:,}</div><div class="kpi-lbl">Staged Articles</div></div>
  <div class="card"><div class="kpi-val">{summary['traffic_spike_days_2sigma']:,}</div><div class="kpi-lbl">2-Sigma Spike Desk-Days</div></div>
  <div class="card"><div class="kpi-val">{summary['zero_body_parser_defects']:,}</div><div class="kpi-lbl">Parser Zero-Body Defects</div></div>
  <div class="card"><div class="kpi-val">{summary['unassigned_taxonomy_rows']:,}</div><div class="kpi-lbl">Unassigned Desk Rows</div></div>
</div>
<label for="deskFilter"><strong>Filter Desk:</strong></label>
<select id="deskFilter" onchange="renderDeskTable()">
  <option value="ALL">All Editorial Desks</option>
</select>
<table>
  <thead>
    <tr><th>Editorial Desk</th><th>Articles</th><th>Total Shares</th><th>Mean Shares</th><th>High-Velocity %</th><th>2-Sigma Spikes</th><th>Zero-Body Defects</th></tr>
  </thead>
  <tbody id="deskBody"></tbody>
</table>
<h2>Randomized Newsletter A/B Experiment Contrasts</h2>
<table>
  <thead>
    <tr><th>Contrast</th><th>Treatment N</th><th>Visit Rate %</th><th>Visit Lift (Rel)</th><th>Holm p (Visit)</th><th>Conv Lift (Rel)</th><th>Holm p (Conv)</th></tr>
  </thead>
  <tbody id="abBody"></tbody>
</table>
<script>
const deskData = {desk_json};
const abData = {ab_json};
const sel = document.getElementById('deskFilter');
deskData.forEach(r => {{
  const o = document.createElement('option');
  o.value = r.editorial_desk;
  o.textContent = r.editorial_desk;
  sel.appendChild(o);
}});
function renderDeskTable() {{
  const val = sel.value;
  const rows = val === 'ALL' ? deskData : deskData.filter(r => r.editorial_desk === val);
  document.getElementById('deskBody').innerHTML = rows.map(r => `
    <tr>
      <td><strong>${{r.editorial_desk}}</strong></td>
      <td>${{Number(r.articles).toLocaleString()}}</td>
      <td>${{Number(r.total_shares).toLocaleString()}}</td>
      <td>${{r.avg_shares}}</td>
      <td>${{r.high_velocity_rate_pct}}%</td>
      <td>${{r.spike_days}}</td>
      <td>${{Number(r.zero_body_defects).toLocaleString()}}</td>
    </tr>`).join('');
}}
document.getElementById('abBody').innerHTML = abData.map(r => `
  <tr>
    <td><strong>${{r.contrast}}</strong></td>
    <td>${{Number(r.treatment_n).toLocaleString()}}</td>
    <td>${{r.treatment_visit_rate_pct}}%</td>
    <td>+${{r.visit_rel_lift_pct}}%</td>
    <td>${{r.visit_p_holm}}</td>
    <td>+${{r.conv_rel_lift_pct}}%</td>
    <td>${{r.conv_p_holm}}</td>
  </tr>`).join('');
renderDeskTable();
</script>
</body>
</html>"""
    out_html.write_text(html, encoding="utf-8")


def run_pipeline(
    repo_root: Path,
    news_csv_text: Optional[str] = None,
    hillstrom_csv_text: Optional[str] = None,
    verify_hashes: bool = True,
) -> Dict[str, Any]:
    """Run the full editorial analytics pipeline and emit verified outputs."""
    data_dir = repo_root / "data" / "raw"
    models_dir = repo_root / "models"
    outputs_dir = repo_root / "outputs"
    lookml_path = repo_root / "lookml" / "editorial_audience_performance.view.lkml"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    news_sha = "fixture"
    hill_sha = "fixture"
    if news_csv_text is None:
        zip_path = data_dir / "online+news+popularity.zip"
        news_sha = ensure_verified_download(NEWS_ZIP_URL, zip_path, NEWS_ZIP_SHA256, verify_hash=verify_hashes)
        with zipfile.ZipFile(zip_path) as zf:
            csv_member = next(n for n in zf.namelist() if n.endswith(".csv"))
            news_csv_text = zf.read(csv_member).decode("utf-8")

    if hillstrom_csv_text is None:
        hill_path = data_dir / "hillstrom_email_experiment.csv"
        hill_sha = ensure_verified_download(
            HILLSTROM_CSV_URL, hill_path, HILLSTROM_CSV_SHA256, verify_hash=verify_hashes
        )
        hillstrom_csv_text = hill_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    try:
        raw_news_n, raw_hill_n = load_datasets_to_sqlite(conn, news_csv_text, hillstrom_csv_text)
        execute_sql_models(conn, models_dir)
        dq_gates = run_data_quality_gates(conn, lookml_path, raw_news_n, raw_hill_n)
        if not all(g["passed"] for g in dq_gates):
            failed = [g["gate_id"] for g in dq_gates if not g["passed"]]
            raise AssertionError(f"Data quality gates failed: {failed}")

        desk_rows_raw = conn.execute(
            """
            SELECT
                editorial_desk,
                SUM(published_articles) AS articles,
                SUM(total_shares) AS total_shares,
                ROUND(1.0 * SUM(total_shares) / SUM(published_articles), 2) AS avg_shares,
                ROUND(100.0 * SUM(high_velocity_articles) / SUM(published_articles), 2) AS high_velocity_rate_pct,
                SUM(is_traffic_spike_2sigma) AS spike_days,
                SUM(zero_body_defect_count) AS zero_body_defects,
                SUM(missing_taxonomy_count) AS unassigned_rows
            FROM fct_editorial_desk_daily
            GROUP BY editorial_desk
            ORDER BY total_shares DESC
            """
        ).fetchall()
        desk_cols = [
            "editorial_desk",
            "articles",
            "total_shares",
            "avg_shares",
            "high_velocity_rate_pct",
            "spike_days",
            "zero_body_defects",
            "unassigned_rows",
        ]
        desk_scorecard = [dict(zip(desk_cols, r)) for r in desk_rows_raw]
        with (outputs_dir / "desk_kpi_scorecard.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=desk_cols)
            w.writeheader()
            w.writerows(desk_scorecard)

        spike_rows = conn.execute(
            """
            SELECT pub_day_seq, editorial_desk, article_count, total_shares, avg_shares,
                   trailing_14d_mean_log_shares, trailing_14d_sd_log_shares, rolling_14d_zscore
            FROM int_editorial_spike_events
            WHERE is_traffic_spike_2sigma = 1
            ORDER BY rolling_14d_zscore DESC
            """
        ).fetchall()
        spike_cols = [
            "pub_day_seq",
            "editorial_desk",
            "article_count",
            "total_shares",
            "avg_shares",
            "trailing_14d_mean_log_shares",
            "trailing_14d_sd_log_shares",
            "rolling_14d_zscore",
        ]
        with (outputs_dir / "traffic_spike_events.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=spike_cols)
            w.writeheader()
            for row in spike_rows:
                w.writerow(dict(zip(spike_cols, row)))

        welch = compute_welch_weekend_test(conn)
        ridge = fit_ridge_drivers(conn)
        ab_summary = analyze_newsletter_experiment(conn, outputs_dir / "newsletter_ab_results.csv")
        glossary = run_glossary_suite(conn, outputs_dir / "shared_metric_glossary.json")

        zero_body_defects = conn.execute(
            "SELECT SUM(flag_zero_body_parser_defect) FROM stg_editorial_articles"
        ).fetchone()[0]
        unassigned_rows = conn.execute(
            "SELECT SUM(flag_missing_desk_taxonomy) FROM stg_editorial_articles"
        ).fetchone()[0]
        distinct_days = conn.execute(
            "SELECT COUNT(DISTINCT pub_day_seq) FROM stg_editorial_articles"
        ).fetchone()[0]

        summary = {
            "editorial_articles": raw_news_n,
            "newsletter_assignments": raw_hill_n,
            "total_combined_records": raw_news_n + raw_hill_n,
            "distinct_publication_days": distinct_days,
            "zero_body_parser_defects": zero_body_defects,
            "unassigned_taxonomy_rows": unassigned_rows,
            "traffic_spike_days_2sigma": len(spike_rows),
            "dq_gates_passed": sum(1 for g in dq_gates if g["passed"]),
            "dq_gates_total": len(dq_gates),
            "dq_gates": dq_gates,
            "dataset_sha256": {
                "online_news_popularity_zip": news_sha,
                "hillstrom_email_experiment_csv": hill_sha,
            },
            "weekend_vs_weekday_welch": welch,
            "ridge_engagement_drivers": ridge,
            "newsletter_ab_experiment": ab_summary,
            "ai_sql_glossary_metrics_validated": glossary["total_governed_metrics"],
        }
        (outputs_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        build_self_serve_dashboard(
            desk_scorecard,
            ab_summary,
            summary,
            repo_root / "dashboards" / "editorial_self_serve_dashboard.html",
        )
        return summary
    finally:
        conn.close()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    res = run_pipeline(root)
    print(json.dumps({k: v for k, v in res.items() if k != "dq_gates"}, indent=2))
