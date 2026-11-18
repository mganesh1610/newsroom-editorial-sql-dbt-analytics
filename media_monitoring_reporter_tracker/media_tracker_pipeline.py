"""Media Monitoring, Breaking-News Alert Triage & Reporter Inquiry Tracker (P1 Module).

Extends the verified 39,644-article / 724-day Online News Popularity & 298 2-sigma
spike outputs into a strategic communications daily media-clipping, breaking-news
escalation, and reporter beat coordination workflow with native OpenXML Excel (.xlsx)
and Word (.docx) briefing exports plus 10 deterministic QA parity checks.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence
from xml.sax.saxutils import escape
import zipfile


BEAT_ROSTER_MAP: dict[str, tuple[str, str, int]] = {
    "Business": ("Financial Markets & M&A Beat", "Capital Markets Desk", 15),
    "Tech": ("Enterprise Tech & Cyber Beat", "Technology Desk", 20),
    "World": ("Global Macro & Regulatory Beat", "Policy & Regulatory Desk", 20),
    "Entertainment": ("Corporate Brand & Media Beat", "Broadcast & Print Desk", 30),
    "Social Media": ("Digital Syndication & Rapid Response Beat", "Digital Wire Desk", 15),
    "Lifestyle": ("Consumer & Customer Communications Beat", "Consumer Press Desk", 45),
    "Unassigned": ("General Wire & Cross-Sector Beat", "National News Wire Desk", 30),
}


def classify_spike_alert_tier(zscore: float) -> tuple[str, int, str]:
    """Classify a >=2.0 SD breaking-news desk spike into SLA tier, minutes, and action."""
    if zscore >= 3.5:
        return ("TIER_1_IMMEDIATE_BREAKING_FLASH", 15, "Immediate client flash alert + Q&A holding statement")
    if zscore >= 2.5:
        return ("TIER_2_PRIORITY_MORNING_CLIP", 45, "Priority morning media clip + reporter inquiry check")
    return ("TIER_3_DAILY_COVERAGE_DIGEST", 120, "Include in daily client coverage & sentiment rollup")


def _col_letter(col_idx_1based: int) -> str:
    res = ""
    n = col_idx_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res


def _write_xlsx(path: Path, sheets: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb_sheets, wb_rels, overrides, ws_files = [], [], [], []
    for idx, (name, headers, rows) in enumerate(sheets, start=1):
        wb_sheets.append(f'<sheet name="{escape(name[:31])}" sheetId="{idx}" r:id="rId{idx}"/>')
        wb_rels.append(
            f'<Relationship Id="rId{idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
        )
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        row_xml = []
        for r_i, r_vals in enumerate([headers, *rows], start=1):
            cells = []
            for c_i, val in enumerate(r_vals, start=1):
                if val is None or val == "":
                    continue
                ref = f"{_col_letter(c_i)}{r_i}"
                if isinstance(val, (int, float)) and r_i > 1:
                    cells.append(f'<c r="{ref}"><v>{val}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(val))}</t></is></c>')
            row_xml.append(f'<row r="{r_i}">{"".join(cells)}</row>')
        ws_files.append(
            (
                f"xl/worksheets/sheet{idx}.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
            )
        )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'{"".join(overrides)}</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>',
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(wb_sheets)}</sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(wb_rels)}</Relationships>',
        )
        for member, content in ws_files:
            zf.writestr(member, content)
    return path


def _write_docx(path: Path, paragraphs: Sequence[tuple[str, bool]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    p_xml = []
    for text, is_bold in paragraphs:
        b = "<w:b/>" if is_bold else ""
        p_xml.append(
            f"<w:p><w:r><w:rPr>{b}</w:rPr><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"
        )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{"".join(p_xml)}</w:body></w:document>',
        )
    return path


def run_media_tracker_module(repo_root: Path, out_subdir: Path | None = None) -> dict[str, Any]:
    """Build daily media clip, breaking spike alert, and reporter beat tracker from root outputs."""
    root_outputs = repo_root / "outputs"
    mod_dir = out_subdir or (repo_root / "media_monitoring_reporter_tracker")
    mod_out = mod_dir / "outputs"
    mod_out.mkdir(parents=True, exist_ok=True)

    val_summary = json.loads((root_outputs / "validation_summary.json").read_text(encoding="utf-8"))
    with (root_outputs / "desk_kpi_scorecard.csv").open("r", encoding="utf-8") as fh:
        desk_rows = list(csv.DictReader(fh))
    with (root_outputs / "traffic_spike_events.csv").open("r", encoding="utf-8") as fh:
        spike_rows = list(csv.DictReader(fh))

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(
        """
        CREATE TABLE dim_media_beats (
            editorial_desk TEXT PRIMARY KEY,
            media_beat_name TEXT NOT NULL,
            outlet_desk_group TEXT NOT NULL,
            inquiry_response_sla_min INTEGER NOT NULL,
            monitored_articles INTEGER NOT NULL,
            total_shares INTEGER NOT NULL,
            avg_shares REAL NOT NULL,
            high_velocity_rate_pct REAL NOT NULL,
            spike_days INTEGER NOT NULL
        );

        CREATE TABLE fct_breaking_media_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pub_day_seq INTEGER NOT NULL,
            editorial_desk TEXT NOT NULL REFERENCES dim_media_beats(editorial_desk),
            media_beat_name TEXT NOT NULL,
            article_count INTEGER NOT NULL,
            total_shares INTEGER NOT NULL,
            rolling_14d_zscore REAL NOT NULL,
            alert_tier TEXT NOT NULL,
            alert_sla_minutes INTEGER NOT NULL,
            recommended_comms_action TEXT NOT NULL
        );
        """
    )

    for r in desk_rows:
        desk = r["editorial_desk"]
        beat_name, group_name, sla_min = BEAT_ROSTER_MAP.get(
            desk, ("General Press Beat", "General News Desk", 30)
        )
        conn.execute(
            "INSERT INTO dim_media_beats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                desk,
                beat_name,
                group_name,
                sla_min,
                int(r["articles"]),
                int(r["total_shares"]),
                float(r["avg_shares"]),
                float(r["high_velocity_rate_pct"]),
                int(r["spike_days"]),
            ),
        )

    for s in spike_rows:
        desk = s["editorial_desk"]
        beat_name = BEAT_ROSTER_MAP.get(desk, ("General Press Beat", "General News Desk", 30))[0]
        z = float(s["rolling_14d_zscore"])
        tier, sla_m, action = classify_spike_alert_tier(z)
        conn.execute(
            """
            INSERT INTO fct_breaking_media_alerts (
                pub_day_seq, editorial_desk, media_beat_name, article_count,
                total_shares, rolling_14d_zscore, alert_tier, alert_sla_minutes, recommended_comms_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(s["pub_day_seq"]),
                desk,
                beat_name,
                int(s["article_count"]),
                int(s["total_shares"]),
                z,
                tier,
                sla_m,
                action,
            ),
        )

    total_articles = int(conn.execute("SELECT SUM(monitored_articles) FROM dim_media_beats").fetchone()[0])
    total_shares = int(conn.execute("SELECT SUM(total_shares) FROM dim_media_beats").fetchone()[0])
    total_spikes = int(conn.execute("SELECT COUNT(*) FROM fct_breaking_media_alerts").fetchone()[0])
    tier1_count = int(
        conn.execute("SELECT COUNT(*) FROM fct_breaking_media_alerts WHERE alert_tier = 'TIER_1_IMMEDIATE_BREAKING_FLASH'").fetchone()[0]
    )
    tier2_count = int(
        conn.execute("SELECT COUNT(*) FROM fct_breaking_media_alerts WHERE alert_tier = 'TIER_2_PRIORITY_MORNING_CLIP'").fetchone()[0]
    )
    tier3_count = int(
        conn.execute("SELECT COUNT(*) FROM fct_breaking_media_alerts WHERE alert_tier = 'TIER_3_DAILY_COVERAGE_DIGEST'").fetchone()[0]
    )

    beat_export_rows = conn.execute(
        """
        SELECT editorial_desk, media_beat_name, outlet_desk_group, inquiry_response_sla_min,
               monitored_articles, total_shares, avg_shares, high_velocity_rate_pct, spike_days
        FROM dim_media_beats
        ORDER BY monitored_articles DESC
        """
    ).fetchall()

    alert_export_rows = conn.execute(
        """
        SELECT pub_day_seq, editorial_desk, media_beat_name, article_count,
               total_shares, rolling_14d_zscore, alert_tier, alert_sla_minutes, recommended_comms_action
        FROM fct_breaking_media_alerts
        ORDER BY rolling_14d_zscore DESC
        """
    ).fetchall()

    csv_path = mod_out / "breaking_media_alert_queue.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "pub_day_seq", "editorial_desk", "media_beat_name", "article_count",
            "total_shares", "rolling_14d_zscore", "alert_tier", "alert_sla_minutes", "recommended_comms_action",
        ])
        w.writerows(alert_export_rows)

    xlsx_path = mod_out / "daily_media_clip_and_reporter_tracker.xlsx"
    _write_xlsx(
        xlsx_path,
        sheets=[
            (
                "Media_Beat_Roster_KPIs",
                [
                    "Editorial Desk", "Media Beat Name", "Outlet Desk Group",
                    "Inquiry SLA (Min)", "Monitored Articles", "Total Shares",
                    "Avg Shares", "High-Velocity (%)", "2-Sigma Spike Days",
                ],
                beat_export_rows,
            ),
            (
                "Breaking_News_Spike_Alerts",
                [
                    "Pub Day Seq", "Editorial Desk", "Media Beat", "Spike Articles",
                    "Total Shares", "14d Rolling Z-Score", "Alert Tier", "SLA (Min)", "Comms Action",
                ],
                alert_export_rows[:100],
            ),
        ],
    )

    docx_path = mod_out / "morning_breaking_news_briefing_and_media_qa.docx"
    _write_docx(
        docx_path,
        paragraphs=[
            ("DAILY CLIENT MEDIA MONITORING, BREAKING ALERT DIGEST & REPORTER TRACKER", True),
            (
                f"Monitored Corpus: {total_articles:,} published digital news articles across "
                f"{val_summary['distinct_publication_days']} days and {len(beat_export_rows)} media beats "
                f"({total_shares:,} total audience shares).",
                False,
            ),
            ("1. Breaking-News Escalation Summary", True),
            (
                f"Detected {total_spikes} causal >=2.0 SD breaking desk-day surges: "
                f"{tier1_count} Tier-1 Immediate Breaking Flashes (<=15 min client alert + holding statement), "
                f"{tier2_count} Tier-2 Priority Morning Clips (<=45 min reporter beat check), and "
                f"{tier3_count} Tier-3 Daily Coverage Digest items.",
                False,
            ),
            ("2. Reporter Inquiry & Spokesperson Prep Protocol", True),
            (
                "Financial Markets & M&A Beat inquiries carry a 15-minute response SLA; all outgoing "
                "spokesperson talking points and Q&A sheets reconcile directly against the verified Excel clip log.",
                False,
            ),
        ],
    )

    with zipfile.ZipFile(docx_path, "r") as zd:
        doc_xml = zd.read("word/document.xml").decode("utf-8")
    with zipfile.ZipFile(xlsx_path, "r") as zx:
        xls_xml = zx.read("xl/worksheets/sheet1.xml").decode("utf-8")

    gates = {
        "M01_article_count_matches_root_39644": total_articles == int(val_summary["editorial_articles"]),
        "M02_share_count_matches_root_134606452": total_shares == 134606452,
        "M03_spike_count_matches_root_298": total_spikes == int(val_summary["traffic_spike_days_2sigma"]),
        "M04_alert_tiers_partition_all_spikes": (tier1_count + tier2_count + tier3_count) == total_spikes,
        "M05_tier1_flash_alerts_non_empty": tier1_count > 0,
        "M06_foreign_key_integrity_clean": len(conn.execute("PRAGMA foreign_key_check;").fetchall()) == 0,
        "M07_sqlite_integrity_ok": conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok",
        "M08_xlsx_beat_roster_populated": "Financial Markets &amp; M&amp;A Beat" in xls_xml,
        "M09_docx_briefing_reconciles_totals": f"{total_articles:,}" in doc_xml and f"{total_spikes}" in doc_xml,
        "M10_source_sha256_preserved": val_summary["dataset_sha256"]["online_news_popularity_zip"]
        == "dba2ae526f62ccef6f2f8efb53b0268319f4d0d2719bb98d88958cfe31d58a22",
    }
    conn.close()

    passed = sum(1 for v in gates.values() if v)
    if passed != len(gates):
        raise RuntimeError(f"Media tracker gate failure: {[k for k, v in gates.items() if not v]}")

    report = {
        "monitored_articles": total_articles,
        "distinct_publication_days": int(val_summary["distinct_publication_days"]),
        "media_beats_tracked": len(beat_export_rows),
        "total_audience_shares": total_shares,
        "breaking_spike_alerts_total": total_spikes,
        "tier1_immediate_flash_alerts": tier1_count,
        "tier2_priority_morning_clips": tier2_count,
        "tier3_daily_digest_alerts": tier3_count,
        "deliverables": [
            str(xlsx_path.relative_to(mod_dir)),
            str(docx_path.relative_to(mod_dir)),
            str(csv_path.relative_to(mod_dir)),
        ],
        "gates_passed": passed,
        "gates_total": len(gates),
        "gates": gates,
    }
    (mod_out / "media_tracker_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[1]
    out = run_media_tracker_module(root_dir)
    print(json.dumps({k: v for k, v in out.items() if k != "gates"}, indent=2))
