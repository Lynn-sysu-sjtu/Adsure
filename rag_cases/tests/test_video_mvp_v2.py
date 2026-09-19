from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.video_mvp.models import EvidenceUnit
from src.video_mvp.pipeline import analyze_video
from src.video_mvp.rules import analyze_rules
from src.video_mvp.sampling import select_candidates, adaptive_frames
from src.video_mvp.asr import transcribe_video

ROOT = Path(__file__).resolve().parents[1]


def unit(text, start=0., end=1., source="asr", eid="e", bbox=None, frame_ids=None):
    return EvidenceUnit(id=eid, source=source, kind="text", text=text, t_start=start,
                        t_end=end, bbox=bbox, frame_ids=frame_ids or [])


def risks(items, industry="一般行业"):
    return analyze_rules(items, industry=industry, frame_count=2, coverage_complete=True, sample_interval=.5)[0]


class RecallRegression(unittest.TestCase):
    def test_labeled_positive_negative_corpus(self):
        corpus = json.loads((ROOT / "data/evaluation/video_claim_regression.json").read_text())
        for case in corpus["cases"]:
            with self.subTest(case=case["id"]):
                found = {r.pattern_id for r in risks([unit(case["text"])], case["industry"])}
                self.assertEqual(set(case["expected"]), found)

    def test_cross_asr_boundary_preserves_original_ids(self):
        found = risks([unit("采用国家", 0, 1, eid="a"), unit("级配方", 1.1, 2, eid="b")])
        self.assertEqual(1, len(found))
        self.assertEqual(["a", "b"], found[0].evidence_ids)
        self.assertEqual("国家级", found[0].matched_text)

    def test_distant_audio_is_not_joined(self):
        self.assertEqual([], risks([unit("国家", 0, 1), unit("级配方", 5, 6, eid="b")]))

    def test_cross_ocr_line(self):
        found = risks([unit("国家", source="ocr", eid="a", bbox=[.1,.1,.2,.05],frame_ids=["f"]),
                       unit("级配方", source="ocr", eid="b", bbox=[.1,.16,.2,.05],frame_ids=["f"])])
        self.assertEqual(["a", "b"], found[0].evidence_ids)

    def test_different_scenes_are_not_joined(self):
        self.assertEqual([], risks([unit("国家", source="ocr", frame_ids=["a"]),
                                    unit("级配方", source="ocr", eid="b",frame_ids=["b"])]))

    def test_split_warning_not_flagged(self):
        self.assertEqual([], risks([unit("保健食品不是药物，不能代替药物", 0, 1, eid="a"),
                                    unit("治疗疾病", 1, 2, eid="b")], "保健食品"))

    def test_two_sources_keep_separate_positions(self):
        found = risks([unit("国家级", source="ocr", bbox=[.1,.2,.3,.1]), unit("国家级", eid="audio")])
        self.assertEqual({"asr", "ocr"}, {r.source for r in found})

    def test_word_timestamps_narrow_audio_risk(self):
        item = unit("这是国家级配方", 0, 4)
        item.raw_ref = {"words":[{"word":"这是","start":0,"end":1},
                                 {"word":"国家级","start":1,"end":2},
                                 {"word":"配方","start":2,"end":4}]}
        found = risks([item])
        self.assertEqual((1, 2), (found[0].t_start, found[0].t_end))

    def test_low_priority_offer_is_not_a_falsity_finding(self):
        found = risks([unit("买二送一")])
        self.assertEqual("low", found[0].severity)
        self.assertIn("不违法", found[0].recommendation)
        self.assertEqual({"ADLAW-008-01", "ADLAW-008-02"}, {b["rule_id"] for b in found[0].legal_basis})


class CoverageRegression(unittest.TestCase):
    def _run(self, native, audio):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p/"source.mp4").write_bytes(b"fixture")
            with patch("src.video_mvp.pipeline.extract_video_frames", return_value=native), patch(
                "src.video_mvp.pipeline.transcribe_video", return_value=audio), patch(
                "src.video_mvp.pipeline._retrieve_cases", return_value=([], [])):
                return analyze_video(p/"source.mp4", p/"output")

    def test_asr_failure_is_not_success(self):
        r = self._run({"duration": .5, "frames": [{"timestamp":0,"ocr":[]}]}, ([], {"status":"failed","error":"model missing"}))
        self.assertEqual("needs_attention", r["analysis_status"])
        self.assertEqual("not_proven", r["coverage_status"])

    def test_ocr_failure_preserves_audio_risk(self):
        r = self._run({"duration":.5,"frames":[{"timestamp":0,"ocr":[{"error":"failed"}]}]},
                      ([unit("国家级")], {"status":"transcribed"}))
        self.assertEqual("needs_attention", r["analysis_status"])
        self.assertTrue(r["risks"])

    def test_missing_middle_frame_not_complete(self):
        r = self._run({"duration":2,"frames":[{"timestamp":0,"ocr":[]},{"timestamp":1.5,"ocr":[]}]},
                      ([],{"status":"no_audio_track"}))
        self.assertEqual("not_proven", r["coverage_status"])

    def test_low_confidence_is_not_complete(self):
        r = self._run({"duration": .5, "frames": [{"timestamp":0,"ocr":[]}]},
                      ([unit("国家级")], {"status":"transcribed", "low_confidence_segments":[{"start":0,"end":1,"confidence":.2}]}))
        self.assertEqual("needs_attention", r["analysis_status"])
        self.assertTrue(r["risks"])

    def test_timeout_is_explicit(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp, patch("src.video_mvp.asr.subprocess.run", side_effect=subprocess.TimeoutExpired("asr",1)):
            units, state = transcribe_video(Path("source.mp4"), Path(tmp))
            self.assertEqual([], units)
            self.assertEqual("failed", state["status"])


class SamplingRegression(unittest.TestCase):
    def test_budget_covers_end_not_just_prefix(self):
        candidates = [{"timestamp":i,"index":i,"reasons":["baseline"],"change_score":0} for i in range(20)]
        selected, omitted = select_candidates(candidates, 3)
        self.assertEqual([0,10,19], [s["timestamp"] for s in selected])
        self.assertEqual(17, omitted)

    def test_short_overlay_between_baselines_is_sampled(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"fixture.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20., (320,180))
            self.assertTrue(writer.isOpened())
            for i in range(40):
                frame = np.zeros((180,320,3), dtype=np.uint8)
                if 5 <= i <= 8:
                    cv2.rectangle(frame,(20,120),(280,170),(255,255,255),-1)
                writer.write(frame)
            writer.release()
            result = adaptive_frames(path, Path(tmp)/"frames", 1., 100)
            self.assertTrue(any(.2 <= f["timestamp"] <= .45 and "visual_change" in f["reasons"] for f in result["frames"]))
            self.assertGreater(result["frames"][-1]["timestamp"],1.8)
            self.assertTrue(result["sampling"]["sampling_complete"])


class WebRegression(unittest.TestCase):
    def test_upload_partial_report_and_downloads(self):
        from fastapi.testclient import TestClient
        from src.video_mvp import api
        item = unit("国家级<script>", 0, .5)
        item.provider = "faster-whisper"
        item.confidence = .2
        with tempfile.TemporaryDirectory() as temporary, patch.object(api, "JOBS_ROOT", Path(temporary)), patch(
            "src.video_mvp.pipeline.extract_video_frames", return_value={"duration":.5,"frames":[{"timestamp":0,"ocr":[]}]}), patch(
            "src.video_mvp.pipeline.transcribe_video", return_value=([item], {"status":"transcribed","low_confidence_segments":[{"start":0,"end":.5,"confidence":.2}]})), patch(
            "src.video_mvp.pipeline._retrieve_cases", return_value=([], [])):
            with TestClient(api.create_app()) as client:
                response = client.post("/api/jobs", files={"video":("video.mp4",b"fixture","video/mp4")})
                self.assertEqual(202, response.status_code)
                job = response.json()["job_id"]
                self.assertEqual("needs_attention", client.get(f"/api/jobs/{job}").json()["status"])
                page = client.get(f"/jobs/{job}").text
                self.assertIn("低置信度，请回听", page)
                self.assertIn("国家级&lt;script&gt;", page)
                self.assertNotIn("国家级<script>", page)
                for artifact in ["report","evidence","manifest","media"]:
                    self.assertEqual(200, client.get(f"/api/jobs/{job}/{artifact}").status_code)

    def test_invalid_upload_is_rejected_before_processing(self):
        from fastapi.testclient import TestClient
        from src.video_mvp import api
        with tempfile.TemporaryDirectory() as temporary, patch.object(api, "JOBS_ROOT", Path(temporary)):
            with TestClient(api.create_app()) as client:
                response = client.post("/api/jobs", files={"video":("payload.txt", b"fixture")})
                self.assertEqual(400, response.status_code)
                self.assertEqual([], list(Path(temporary).iterdir()))


if __name__ == "__main__":
    unittest.main()
