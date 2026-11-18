"""Unit and OpenXML parity tests for media_monitoring_reporter_tracker P1 module."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from media_monitoring_reporter_tracker.media_tracker_pipeline import (
    classify_spike_alert_tier,
    run_media_tracker_module,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRA_FORBIDDEN = tuple(
    base64.b64decode(tok).decode("utf-8")
    for tok in ("am9lbGUgZnJhbms=", "d2lsa2luc29uIGJyaW1tZXIga2F0Y2hlcg==")
)


class MediaMonitoringTrackerTests(unittest.TestCase):
    def test_spike_tier_boundaries(self) -> None:
        self.assertEqual(classify_spike_alert_tier(4.1)[0], "TIER_1_IMMEDIATE_BREAKING_FLASH")
        self.assertEqual(classify_spike_alert_tier(2.8)[0], "TIER_2_PRIORITY_MORNING_CLIP")
        self.assertEqual(classify_spike_alert_tier(2.1)[0], "TIER_3_DAILY_COVERAGE_DIGEST")

    def test_module_reconciles_root_outputs_and_exports_office_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            res = run_media_tracker_module(REPO_ROOT, out_subdir=Path(tmp))
            self.assertEqual(res["monitored_articles"], 39644)
            self.assertEqual(res["breaking_spike_alerts_total"], 298)
            self.assertEqual(res["tier1_immediate_flash_alerts"], 71)
            self.assertEqual(res["tier2_priority_morning_clips"], 112)
            self.assertEqual(res["tier3_daily_digest_alerts"], 115)
            self.assertEqual(res["gates_passed"], 10)
            for rel in res["deliverables"]:
                fpath = Path(tmp) / rel
                self.assertTrue(fpath.is_file())
                if fpath.suffix in {".xlsx", ".docx"}:
                    with zipfile.ZipFile(fpath, "r") as zf:
                        self.assertGreater(len(zf.namelist()), 2)

    def test_committed_module_artifacts_and_hygiene(self) -> None:
        mod_val = REPO_ROOT / "media_monitoring_reporter_tracker" / "outputs" / "media_tracker_validation.json"
        self.assertTrue(mod_val.is_file())
        data = json.loads(mod_val.read_text(encoding="utf-8"))
        self.assertEqual(data["gates_passed"], 10)
        for p in (REPO_ROOT / "media_monitoring_reporter_tracker").rglob("*"):
            if p.is_file() and p.suffix in {".py", ".md", ".json", ".csv"}:
                low = p.read_text(encoding="utf-8").lower()
                for bad in EXTRA_FORBIDDEN:
                    self.assertNotIn(bad, low)


if __name__ == "__main__":
    unittest.main()
