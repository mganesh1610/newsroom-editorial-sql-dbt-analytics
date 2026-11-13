"""Unit, boundary, SQL safety, and repository hygiene tests for Editorial Analytics."""

from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.ai_sql_glossary_assistant import UnsafeSQLError, validate_readonly_sql
from src.editorial_analytics_pipeline import (
    ensure_verified_download,
    run_pipeline,
    sha256_file,
    wilson_ci,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Encoded check tokens so repository never stores target brand names verbatim
FORBIDDEN_TERMS = tuple(
    base64.b64decode(tok).decode("utf-8")
    for tok in ("ZG93IGpvbmVz", "d2FsbCBzdHJlZXQgam91cm5hbA==", "d3Nq")
)


def make_synthetic_datasets(n_days: int = 25, articles_per_day: int = 3) -> tuple[str, str]:
    """Build deterministic CSV strings matching UCI Online News and Hillstrom schemas."""
    news_headers = [
        "url",
        "timedelta",
        "n_tokens_title",
        "n_tokens_content",
        "n_unique_tokens",
        "n_non_stop_words",
        "n_non_stop_unique_tokens",
        "num_hrefs",
        "num_self_hrefs",
        "num_imgs",
        "num_videos",
        "average_token_length",
        "num_keywords",
        "data_channel_is_lifestyle",
        "data_channel_is_entertainment",
        "data_channel_is_bus",
        "data_channel_is_socmed",
        "data_channel_is_tech",
        "data_channel_is_world",
        "kw_min_min",
        "kw_max_min",
        "kw_avg_min",
        "kw_min_max",
        "kw_max_max",
        "kw_avg_max",
        "kw_min_avg",
        "kw_max_avg",
        "kw_avg_avg",
        "self_reference_min_shares",
        "self_reference_max_shares",
        "self_reference_avg_sharess",
        "weekday_is_monday",
        "weekday_is_tuesday",
        "weekday_is_wednesday",
        "weekday_is_thursday",
        "weekday_is_friday",
        "weekday_is_saturday",
        "weekday_is_sunday",
        "is_weekend",
        "LDA_00",
        "LDA_01",
        "LDA_02",
        "LDA_03",
        "LDA_04",
        "global_subjectivity",
        "global_sentiment_polarity",
        "global_rate_positive_words",
        "global_rate_negative_words",
        "rate_positive_words",
        "rate_negative_words",
        "avg_positive_polarity",
        "min_positive_polarity",
        "max_positive_polarity",
        "avg_negative_polarity",
        "min_negative_polarity",
        "max_negative_polarity",
        "title_subjectivity",
        "title_sentiment_polarity",
        "abs_title_subjectivity",
        "abs_title_sentiment_polarity",
        "shares",
    ]
    news_lines = [", ".join(news_headers)]
    idx = 0
    for d in range(n_days):
        td = 731 - d
        wd = d % 7
        for j in range(articles_per_day):
            idx += 1
            tokens = 0 if idx == 1 else 250 + j * 40
            bus = 1 if j == 0 else 0
            tech = 1 if j == 1 else 0
            # j == 2 intentionally unassigned taxonomy
            shares = 12000 if (d == n_days - 2 and j == 0) else 1500 + (idx % 5) * 400
            row = {h: "0.0" for h in news_headers}
            row["url"] = f"http://example.org/story-{idx}"
            row["timedelta"] = str(td)
            row["n_tokens_title"] = str(9 + (idx % 5))
            row["n_tokens_content"] = str(tokens)
            row["num_hrefs"] = "5"
            row["num_self_hrefs"] = str(1 + (j % 4))
            row["num_imgs"] = str(1 + (j % 4))
            row["num_videos"] = "1" if j == 1 else "0"
            row["num_keywords"] = "6"
            row["kw_avg_avg"] = str(2000.0 + idx * 5.0)
            row["data_channel_is_bus"] = str(bus)
            row["data_channel_is_tech"] = str(tech)
            wd_cols = [
                "weekday_is_monday",
                "weekday_is_tuesday",
                "weekday_is_wednesday",
                "weekday_is_thursday",
                "weekday_is_friday",
                "weekday_is_saturday",
                "weekday_is_sunday",
            ]
            row[wd_cols[wd]] = "1"
            row["is_weekend"] = "1" if wd >= 5 else "0"
            row["title_subjectivity"] = "0.25"
            row["shares"] = str(shares)
            news_lines.append(", ".join(row[h] for h in news_headers))

    hill_headers = [
        "recency",
        "history_segment",
        "history",
        "mens",
        "womens",
        "zip_code",
        "newbie",
        "channel",
        "segment",
        "visit",
        "conversion",
        "spend",
    ]
    hill_lines = [",".join(hill_headers)]
    arms = ["Mens E-Mail", "Womens E-Mail", "No E-Mail"]
    for i in range(90):
        arm = arms[i % 3]
        visit = 1 if (arm != "No E-Mail" and i % 4 == 0) or (arm == "No E-Mail" and i % 9 == 0) else 0
        conv = 1 if (visit == 1 and i % 8 == 0) else 0
        spend = "45.0" if conv else "0.0"
        hill_lines.append(
            f"{1 + (i % 12)},1) $0 - $100,{50.0 + (i % 10)},1,0,Urban,{i % 2},Web,{arm},{visit},{conv},{spend}"
        )
    return "\n".join(news_lines), "\n".join(hill_lines)


class EditorialAnalyticsTests(unittest.TestCase):
    def test_readonly_sql_guardrail_allows_select_and_blocks_dml_ddl(self) -> None:
        self.assertEqual(
            validate_readonly_sql("WITH x AS (SELECT 1 AS a) SELECT a FROM x;"),
            "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
        )
        for bad_sql in (
            "DROP TABLE stg_editorial_articles;",
            "DELETE FROM stg_editorial_articles WHERE 1=1",
            "INSERT INTO stg_editorial_articles VALUES (1)",
            "SELECT 1; DROP TABLE stg_editorial_articles",
            "PRAGMA table_info(stg_editorial_articles)",
        ):
            with self.assertRaises(UnsafeSQLError):
                validate_readonly_sql(bad_sql)

    def test_checksum_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sample.csv"
            p.write_text("col\n1\n", encoding="utf-8")
            actual = sha256_file(p)
            self.assertEqual(len(actual), 64)
            with self.assertRaises(ValueError):
                ensure_verified_download("http://invalid.localhost", p, "0" * 64, verify_hash=True)

    def test_wilson_bounds_sanity(self) -> None:
        lo, hi = wilson_ci(0, 100)
        self.assertAlmostEqual(lo, 0.0, places=12)
        self.assertGreater(hi, 0.0)
        self.assertLess(hi, 0.1)

    def test_offline_pipeline_conservation_and_defect_detection(self) -> None:
        news_csv, hill_csv = make_synthetic_datasets()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            for sub in ("models", "lookml"):
                (tmp_root / sub).mkdir(parents=True, exist_ok=True)
                for f in (REPO_ROOT / sub).glob("*"):
                    (tmp_root / sub / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

            summary = run_pipeline(
                tmp_root,
                news_csv_text=news_csv,
                hillstrom_csv_text=hill_csv,
                verify_hashes=False,
            )
            self.assertEqual(summary["editorial_articles"], 75)
            self.assertEqual(summary["newsletter_assignments"], 90)
            self.assertEqual(summary["zero_body_parser_defects"], 1)
            self.assertEqual(summary["unassigned_taxonomy_rows"], 25)
            self.assertEqual(summary["dq_gates_passed"], summary["dq_gates_total"])
            self.assertEqual(summary["ai_sql_glossary_metrics_validated"], 20)
            self.assertTrue((tmp_root / "outputs" / "validation_summary.json").exists())
            self.assertTrue((tmp_root / "dashboards" / "editorial_self_serve_dashboard.html").exists())

    def test_committed_outputs_and_no_forbidden_company_names(self) -> None:
        val_file = REPO_ROOT / "outputs" / "validation_summary.json"
        self.assertTrue(val_file.exists(), "Run pipeline before running repository validation tests.")
        val = json.loads(val_file.read_text(encoding="utf-8"))
        self.assertEqual(val["editorial_articles"], 39644)
        self.assertEqual(val["newsletter_assignments"], 64000)
        self.assertEqual(val["dq_gates_passed"], 14)

        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or "data/raw" in str(path) or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix in {".py", ".sql", ".lkml", ".md", ".yml", ".yaml", ".json", ".csv", ".html"}:
                content_lower = path.read_text(encoding="utf-8").lower()
                for term in FORBIDDEN_TERMS:
                    self.assertNotIn(term, content_lower, f"Forbidden term '{term}' found in {path}")


if __name__ == "__main__":
    unittest.main()
