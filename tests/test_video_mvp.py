from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.video_mvp.models import EvidenceUnit
from src.video_mvp.pipeline import analyze_video
from src.video_mvp.rules import MANDATORY_WARNING, analyze_rules
from src.video_mvp.transcript import transcript_evidence


class TranscriptTests(unittest.TestCase):
    def test_srt_preserves_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.srt"
            path.write_text(
                "1\n00:00:01,250 --> 00:00:03,500\n国家级配方\n\n"
                "2\n00:00:04,000 --> 00:00:05,000\n仅供演示\n",
                encoding="utf-8",
            )
            evidence, warnings = transcript_evidence(
                transcript_path=path,
                transcript_text="",
                duration=8,
            )
        self.assertEqual(2, len(evidence))
        self.assertEqual(1.25, evidence[0].t_start)
        self.assertEqual(3.5, evidence[0].t_end)
        self.assertEqual([], warnings)

    def test_missing_transcript_is_explicit(self) -> None:
        evidence, warnings = transcript_evidence(
            transcript_path=None,
            transcript_text="",
            duration=10,
        )
        self.assertEqual([], evidence)
        self.assertIn("不能视为已审核口播", warnings[0])


class RuleTests(unittest.TestCase):
    def _evidence(self, frame: int, text: str) -> EvidenceUnit:
        return EvidenceUnit(
            id=f"ocr_{frame}",
            source="ocr",
            kind="text",
            text=text,
            t_start=float(frame),
            t_end=float(frame + 1),
            bbox=[0.1, 0.2, 0.3, 0.1],
            frame_ids=[f"frame_{frame:06d}"],
        )

    def test_absolute_and_health_food_treatment_claims(self) -> None:
        risks, _ = analyze_rules(
            [self._evidence(0, "国家级配方，三天根治")],
            industry="保健食品",
            frame_count=1,
            coverage_complete=True,
            sample_interval=1,
        )
        self.assertEqual({"国家级", "根治"}, {risk.matched_text for risk in risks})
        self.assertTrue(all(risk.review_status == "pending_human_review" for risk in risks))

    def test_mandatory_warning_is_not_a_treatment_claim(self) -> None:
        evidence = [self._evidence(index, MANDATORY_WARNING) for index in range(3)]
        risks, checks = analyze_rules(
            evidence,
            industry="保健食品",
            frame_count=3,
            coverage_complete=True,
            sample_interval=1,
        )
        self.assertEqual([], risks)
        warning = next(item for item in checks if item.check_id == "l4_health_food_warning_continuity")
        self.assertEqual("observed_in_all_samples", warning.status)
        self.assertEqual(1.0, warning.coverage_ratio)

    def test_partial_warning_does_not_pass_continuity(self) -> None:
        risks, checks = analyze_rules(
            [self._evidence(0, MANDATORY_WARNING), self._evidence(1, "普通画面")],
            industry="保健食品",
            frame_count=2,
            coverage_complete=True,
            sample_interval=1,
        )
        self.assertEqual([], risks)
        warning = next(item for item in checks if item.check_id == "l4_health_food_warning_continuity")
        self.assertEqual("not_continuously_observed", warning.status)


class PipelineTests(unittest.TestCase):
    def test_report_and_evidence_chain_are_written(self) -> None:
        native_result = {
            "duration": 1.0,
            "engine": "test extractor",
            "frames": [{
                "frameId": "frame_000000",
                "timestamp": 0.0,
                "imagePath": "/tmp/frame_000000.jpg",
                "ocr": [{"text": "国家级配方", "confidence": 0.99, "bbox": [0.1, 0.2, 0.3, 0.1]}],
            }],
            "errors": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "source.mp4"
            video.write_bytes(b"test-video-evidence")
            output = root / "job"
            with patch("src.video_mvp.pipeline.extract_video_frames", return_value=native_result), patch(
                "src.video_mvp.pipeline._retrieve_cases", return_value=([], [])
            ), patch("src.video_mvp.pipeline.transcribe_video", return_value=([], {"status": "no_audio_track"})
            ):
                report = analyze_video(video, output, sample_interval=1.0)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))

        self.assertEqual("pending_human_review", report["review_status"])
        self.assertEqual("sampled_complete", report["coverage_status"])
        self.assertEqual("国家级", report["risks"][0]["matched_text"])
        self.assertEqual(64, len(manifest["source"]["sha256"]))
        self.assertEqual("ocr_", evidence["items"][0]["id"][:4])
        self.assertIn("音乐曲库/授权链核验", report["capability_boundaries"]["not_connected"])


if __name__ == "__main__":
    unittest.main()
