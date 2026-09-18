from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.video_service.schemas import EvidenceBundle, Coverage, CoverageItem, ExtractorVersion
from src.video_service.store import JobStore

ROOT = Path(__file__).resolve().parents[1]


def bundle(record="rec-1"):
    return EvidenceBundle(
        record_id=record, request_id=record, material_id="mat-1", material_type="video",
        file_sha256="a"*64, evidence_units=[],
        coverage=Coverage(
            overall="partial",
            audio=CoverageItem(status="transcribed"),
            frames=CoverageItem(status="sampled_complete"),
            ocr=CoverageItem(status="executed"),
            visual_semantics=CoverageItem(status="not_connected"),
            rule_engine=CoverageItem(status="not_called"),
        ),
        extractor_version=ExtractorVersion(service="video-extractor/0.1.0", version="test"),
    )


class StoreTests(unittest.TestCase):
    def test_idempotency_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(Path(tmp)/"jobs.sqlite3")
            video=Path(tmp)/"a.mp4"; video.write_bytes(b"x")
            a,_=store.create_job(source_path=video,file_sha256="h",record_id="r1",material_id="",dedupe_by_hash=True)
            b,dup=store.create_job(source_path=video,file_sha256="h",record_id="r1",material_id="",dedupe_by_hash=True)
            self.assertTrue(dup); self.assertEqual(a["job_id"],b["job_id"])
            store.finish(a["job_id"],"completed",{"job_id":a["job_id"],"rule_engine":{"status":"completed"}},[],None)
            reopened=JobStore(Path(tmp)/"jobs.sqlite3")
            self.assertEqual("completed",reopened.get(a["job_id"])["status"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        env={"VIDEO_SERVICE_DATA_DIR":str(self.root),"VIDEO_SERVICE_API_KEY":"test-key",
              "VIDEO_SERVICE_MIN_FREE_BYTES":"1"}
        env_patch=patch.dict("os.environ",env,clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        from src.video_service.service import create_app
        self.client=TestClient(create_app())

    def tearDown(self): self.tmp.cleanup()

    def test_auth_invalid_file_and_duplicate(self):
        r=self.client.get("/ready")
        self.assertIn(r.status_code, (200,503))
        self.assertTrue(r.json()["jobs_db"]["ready"])
        unauthorized = self.client.post(
            "/api/video/jobs", files={"video": ("a.mp4", b"x", "video/mp4")})
        self.assertEqual(401, unauthorized.status_code)
        self.assertEqual(401, self.client.post(
            "/api/video/jobs", headers={"X-API-Key": "wrong"},
            files={"video": ("a.mp4", b"x", "video/mp4")}).status_code)
        headers={"X-API-Key":"test-key"}
        bad=self.client.post("/api/video/jobs",headers=headers,files={"video":("a.txt",b"x","text/plain")})
        self.assertEqual(400,bad.status_code)
        # Valid ftyp header; worker extraction is allowed to fail later, upload must be accepted.
        mp4=(ROOT/"tests/fixtures/sample_ad.mp4").read_bytes()
        first=self.client.post("/api/video/jobs",headers=headers,
                               files={"video":("a.mp4",mp4,"video/mp4")},data={"record_id":"r1"})
        self.assertEqual(202,first.status_code)
        second=self.client.post("/api/video/jobs",headers=headers,
                                files={"video":("a.mp4",mp4,"video/mp4")},data={"record_id":"r1"})
        self.assertEqual(202,second.status_code); self.assertTrue(second.json()["duplicated"])
        job=second.json()["job_id"]
        status=self.client.get(f"/api/video/jobs/{job}",headers=headers)
        self.assertEqual(200,status.status_code); self.assertIn(status.json()["status"],{"queued","processing","failed","partial","completed"})


class RuleClientTests(unittest.TestCase):
    def test_rule_engine_failure_never_passes(self):
        from src.video_service.rule_engine import invoke_rule_engine
        with patch.dict("os.environ",{"RULE_ENGINE_URL":"http://127.0.0.1:9","RULE_ENGINE_RETRIES":"0"}):
            result=invoke_rule_engine(bundle())
        self.assertEqual("failed",result.status); self.assertEqual("rule_engine_unavailable",result.error_code)

if __name__=="__main__": unittest.main()
