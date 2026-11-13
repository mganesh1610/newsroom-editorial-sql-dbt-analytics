"""Lightweight AI/LLM-ready read-only SQL & shared metric glossary utility.

Translates natural-language editorial, audience, and product partner questions
into governed, parameterized read-only SQLite queries against the staged
analytical warehouse, enforcing strict SQL AST/keyword safety guardrails.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

FORBIDDEN_SQL_TOKENS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "REPLACE",
    "VACUUM",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
)


class UnsafeSQLError(ValueError):
    """Raised when a generated or user-supplied SQL statement violates read-only policy."""


def strip_sql_comments(sql: str) -> str:
    """Remove single-line and block SQL comments prior to read-only inspection."""
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line.strip()


def validate_readonly_sql(sql: str) -> str:
    """Validate that a SQL query is a single read-only SELECT or CTE statement."""
    cleaned = strip_sql_comments(sql)
    if not cleaned:
        raise UnsafeSQLError("Empty SQL statement is not permitted.")

    trimmed = cleaned.rstrip(";").strip()
    if ";" in trimmed:
        raise UnsafeSQLError("Multi-statement SQL execution is blocked.")

    upper = trimmed.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise UnsafeSQLError("Only SELECT or WITH (CTE) read-only queries are permitted.")

    tokens = set(re.findall(r"\b[A-Z_]+\b", upper))
    blocked = sorted(tokens.intersection(FORBIDDEN_SQL_TOKENS))
    if blocked:
        raise UnsafeSQLError(f"Forbidden write/DDL SQL keyword(s) detected: {', '.join(blocked)}")

    return trimmed


SHARED_METRIC_GLOSSARY: List[Dict[str, Any]] = [
    {
        "metric_id": "M01_desk_article_volume",
        "prompt": "How many articles were published by each editorial desk?",
        "lookml_ref": "editorial_audience_performance.published_articles",
        "definition": "Total staged articles grouped by normalized editorial_desk channel.",
        "sql": (
            "SELECT editorial_desk, COUNT(*) AS articles_published "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY articles_published DESC"
        ),
    },
    {
        "metric_id": "M02_desk_total_shares",
        "prompt": "Which editorial desks generated the highest cumulative social shares?",
        "lookml_ref": "editorial_audience_performance.total_shares",
        "definition": "Sum of article shares across each normalized editorial desk.",
        "sql": (
            "SELECT editorial_desk, SUM(shares) AS total_shares "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY total_shares DESC"
        ),
    },
    {
        "metric_id": "M03_desk_mean_shares",
        "prompt": "What is the average share reach per article across editorial desks?",
        "lookml_ref": "editorial_audience_performance.avg_shares_per_article",
        "definition": "Arithmetic mean of article shares per desk.",
        "sql": (
            "SELECT editorial_desk, ROUND(AVG(shares), 2) AS avg_shares "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY avg_shares DESC"
        ),
    },
    {
        "metric_id": "M04_high_velocity_rate",
        "prompt": "What percentage of stories per desk hit the high-velocity >=3,400 share threshold?",
        "lookml_ref": "editorial_audience_performance.high_velocity_rate",
        "definition": "Share of articles reaching >= 3,400 social shares (top-decile proxy).",
        "sql": (
            "SELECT editorial_desk, "
            "ROUND(100.0 * SUM(CASE WHEN shares >= 3400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS viral_rate_pct "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY viral_rate_pct DESC"
        ),
    },
    {
        "metric_id": "M05_above_median_rate",
        "prompt": "What share of stories beat the 1,400-share median benchmark by desk?",
        "lookml_ref": "fct_editorial_desk_daily.above_median_articles",
        "definition": "Percentage of stories reaching >= 1,400 shares.",
        "sql": (
            "SELECT editorial_desk, "
            "ROUND(100.0 * SUM(CASE WHEN shares >= 1400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS above_median_pct "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY above_median_pct DESC"
        ),
    },
    {
        "metric_id": "M06_weekday_performance_profile",
        "prompt": "How does publishing volume and mean share reach vary by day of week?",
        "lookml_ref": "editorial_audience_performance.publish_weekday",
        "definition": "Article counts and average shares by publication weekday.",
        "sql": (
            "SELECT publish_weekday, COUNT(*) AS articles, ROUND(AVG(shares), 1) AS avg_shares "
            "FROM stg_editorial_articles GROUP BY publish_weekday ORDER BY avg_shares DESC"
        ),
    },
    {
        "metric_id": "M07_weekend_vs_weekday_split",
        "prompt": "Do weekend stories outperform weekday stories on average share velocity?",
        "lookml_ref": "editorial_audience_performance.is_weekend",
        "definition": "Comparison of is_weekend = 1 vs is_weekend = 0 log and raw shares.",
        "sql": (
            "SELECT is_weekend, COUNT(*) AS articles, ROUND(AVG(shares), 2) AS avg_shares, "
            "ROUND(AVG(log1p_shares), 4) AS avg_log1p_shares "
            "FROM stg_editorial_articles GROUP BY is_weekend ORDER BY is_weekend"
        ),
    },
    {
        "metric_id": "M08_top_traffic_spike_days",
        "prompt": "Which desk-days experienced >= 2.0 SD traffic spikes above their 14-day baseline?",
        "lookml_ref": "editorial_audience_performance.is_traffic_spike_2sigma",
        "definition": "Desk-days flagged where rolling_14d_zscore >= 2.0.",
        "sql": (
            "SELECT editorial_desk, COUNT(*) AS spike_days, ROUND(MAX(rolling_14d_zscore), 2) AS peak_zscore "
            "FROM fct_editorial_desk_daily WHERE is_traffic_spike_2sigma = 1 "
            "GROUP BY editorial_desk ORDER BY spike_days DESC"
        ),
    },
    {
        "metric_id": "M09_zero_body_parser_defects",
        "prompt": "How many articles have zero parsed body tokens due to upstream scraper failures?",
        "lookml_ref": "editorial_audience_performance.zero_body_defect_count",
        "definition": "Count of staged articles where body_word_count = 0.",
        "sql": (
            "SELECT editorial_desk, SUM(flag_zero_body_parser_defect) AS zero_body_rows, "
            "ROUND(100.0 * SUM(flag_zero_body_parser_defect) / COUNT(*), 2) AS defect_rate_pct "
            "FROM stg_editorial_articles GROUP BY editorial_desk ORDER BY zero_body_rows DESC"
        ),
    },
    {
        "metric_id": "M10_missing_desk_taxonomy",
        "prompt": "How many stories lack an assigned editorial desk tag?",
        "lookml_ref": "editorial_audience_performance.missing_taxonomy_count",
        "definition": "Count of articles flagged with missing channel taxonomy.",
        "sql": (
            "SELECT SUM(flag_missing_desk_taxonomy) AS unassigned_articles, COUNT(*) AS total_articles, "
            "ROUND(100.0 * SUM(flag_missing_desk_taxonomy) / COUNT(*), 2) AS unassigned_pct "
            "FROM stg_editorial_articles"
        ),
    },
    {
        "metric_id": "M11_video_enrichment_lift",
        "prompt": "How do stories with embedded video perform versus text-only stories?",
        "lookml_ref": "fct_editorial_desk_daily.avg_videos",
        "definition": "Comparison of clean articles with video_count > 0 vs video_count = 0.",
        "sql": (
            "SELECT CASE WHEN video_count > 0 THEN 'Has Video' ELSE 'No Video' END AS video_segment, "
            "COUNT(*) AS articles, ROUND(AVG(shares), 1) AS avg_shares "
            "FROM stg_editorial_articles WHERE flag_zero_body_parser_defect = 0 GROUP BY video_segment"
        ),
    },
    {
        "metric_id": "M12_internal_linking_depth",
        "prompt": "Does deeper internal cross-linking associate with higher share performance?",
        "lookml_ref": "fct_editorial_desk_daily.avg_internal_links",
        "definition": "Average shares segmented by internal_link_count bucket.",
        "sql": (
            "SELECT CASE WHEN internal_link_count >= 3 THEN '3+ Internal Links' ELSE '0-2 Internal Links' END AS link_tier, "
            "COUNT(*) AS articles, ROUND(AVG(shares), 1) AS avg_shares "
            "FROM stg_editorial_articles WHERE flag_zero_body_parser_defect = 0 GROUP BY link_tier"
        ),
    },
    {
        "metric_id": "M13_headline_length_bands",
        "prompt": "What headline token length band yields the strongest audience shares?",
        "lookml_ref": "stg_editorial_articles.title_word_count",
        "definition": "Mean shares bucketed across compact, medium, and long headlines.",
        "sql": (
            "SELECT CASE WHEN title_word_count <= 8 THEN 'Short (<=8)' "
            "WHEN title_word_count <= 12 THEN 'Standard (9-12)' ELSE 'Long (13+)' END AS headline_band, "
            "COUNT(*) AS articles, ROUND(AVG(shares), 1) AS avg_shares "
            "FROM stg_editorial_articles GROUP BY headline_band ORDER BY avg_shares DESC"
        ),
    },
    {
        "metric_id": "M14_image_richness_correlation",
        "prompt": "Do visual-rich articles (>=3 images) earn higher high-velocity rates?",
        "lookml_ref": "fct_editorial_desk_daily.avg_images",
        "definition": "Viral share rate segmented by embedded image count.",
        "sql": (
            "SELECT CASE WHEN image_count >= 3 THEN '3+ Images' ELSE '0-2 Images' END AS image_tier, "
            "COUNT(*) AS articles, "
            "ROUND(100.0 * SUM(CASE WHEN shares >= 3400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS viral_rate_pct "
            "FROM stg_editorial_articles WHERE flag_zero_body_parser_defect = 0 GROUP BY image_tier"
        ),
    },
    {
        "metric_id": "M15_keyword_velocity_quartiles",
        "prompt": "How strongly does historical keyword share velocity separate story reach?",
        "lookml_ref": "stg_editorial_articles.avg_keyword_share_velocity",
        "definition": "Top vs non-top keyword share velocity comparison using CTE quartile split.",
        "sql": (
            "WITH ranked AS ("
            "  SELECT shares, NTILE(4) OVER (ORDER BY avg_keyword_share_velocity) AS kw_quartile "
            "  FROM stg_editorial_articles"
            ") "
            "SELECT kw_quartile, COUNT(*) AS articles, ROUND(AVG(shares), 1) AS avg_shares "
            "FROM ranked GROUP BY kw_quartile ORDER BY kw_quartile"
        ),
    },
    {
        "metric_id": "M16_desk_daily_mart_coverage",
        "prompt": "How many desk-day aggregate records are available in the governed BI mart?",
        "lookml_ref": "fct_editorial_desk_daily",
        "definition": "Row count and total articles reconciled inside fct_editorial_desk_daily.",
        "sql": (
            "SELECT COUNT(*) AS desk_day_rows, SUM(published_articles) AS reconciled_articles, "
            "SUM(total_shares) AS reconciled_shares FROM fct_editorial_desk_daily"
        ),
    },
    {
        "metric_id": "M17_newsletter_ab_arm_visits",
        "prompt": "What are the 2-week reader visit rates across randomized newsletter A/B arms?",
        "lookml_ref": "raw_newsletter_experiment.visit",
        "definition": "Assigned users, visits, and visit rate by experiment arm.",
        "sql": (
            "SELECT segment, COUNT(*) AS assigned_readers, SUM(visit) AS visits, "
            "ROUND(100.0 * AVG(visit), 3) AS visit_rate_pct "
            "FROM raw_newsletter_experiment GROUP BY segment ORDER BY visit_rate_pct DESC"
        ),
    },
    {
        "metric_id": "M18_newsletter_ab_conversions",
        "prompt": "What are conversion rates and total spend across randomized newsletter arms?",
        "lookml_ref": "raw_newsletter_experiment.conversion",
        "definition": "Assigned readers, conversions, conversion rate, and revenue by arm.",
        "sql": (
            "SELECT segment, COUNT(*) AS assigned_readers, SUM(conversion) AS conversions, "
            "ROUND(100.0 * AVG(conversion), 3) AS conversion_rate_pct, ROUND(SUM(spend), 2) AS total_spend "
            "FROM raw_newsletter_experiment GROUP BY segment ORDER BY conversion_rate_pct DESC"
        ),
    },
    {
        "metric_id": "M19_new_reader_onboarding_lift",
        "prompt": "How did newsletter treatment arms perform specifically among new readers?",
        "lookml_ref": "raw_newsletter_experiment.newbie",
        "definition": "Visit and conversion breakdown conditioned on newbie = 1 vs 0.",
        "sql": (
            "SELECT newbie, segment, COUNT(*) AS assigned_readers, "
            "ROUND(100.0 * AVG(visit), 2) AS visit_rate_pct, "
            "ROUND(100.0 * AVG(conversion), 3) AS conversion_rate_pct "
            "FROM raw_newsletter_experiment GROUP BY newbie, segment ORDER BY newbie, visit_rate_pct DESC"
        ),
    },
    {
        "metric_id": "M20_channel_history_sensitivity",
        "prompt": "How do experiment visit rates vary across prior reader acquisition channels?",
        "lookml_ref": "raw_newsletter_experiment.channel",
        "definition": "Visit rate grouped by historical acquisition channel and treatment assignment.",
        "sql": (
            "SELECT channel, segment, COUNT(*) AS readers, ROUND(100.0 * AVG(visit), 2) AS visit_rate_pct "
            "FROM raw_newsletter_experiment GROUP BY channel, segment ORDER BY channel, visit_rate_pct DESC"
        ),
    },
]


def execute_governed_query(conn: sqlite3.Connection, sql: str) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """Validate and execute a single read-only SQL query against SQLite."""
    safe_sql = validate_readonly_sql(sql)
    cur = conn.execute(safe_sql)
    columns = [desc[0] for desc in (cur.description or [])]
    rows = cur.fetchall()
    return columns, rows


def run_glossary_suite(conn: sqlite3.Connection, output_path: Path) -> Dict[str, Any]:
    """Validate and execute all 20 shared glossary SQL patterns and write documentation JSON."""
    results: List[Dict[str, Any]] = []
    for entry in SHARED_METRIC_GLOSSARY:
        cols, rows = execute_governed_query(conn, entry["sql"])
        if not rows:
            raise AssertionError(f"Glossary metric {entry['metric_id']} returned 0 rows.")
        results.append(
            {
                "metric_id": entry["metric_id"],
                "prompt": entry["prompt"],
                "lookml_ref": entry["lookml_ref"],
                "definition": entry["definition"],
                "sql": entry["sql"],
                "columns": cols,
                "row_count": len(rows),
                "sample_row": dict(zip(cols, rows[0])),
            }
        )

    payload = {
        "total_governed_metrics": len(results),
        "all_queries_validated_readonly": True,
        "all_queries_nonempty": all(item["row_count"] > 0 for item in results),
        "metrics": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
