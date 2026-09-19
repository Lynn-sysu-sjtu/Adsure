from __future__ import annotations

import base64
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.video_mvp import volc_asr


VOLC_ENV = {
    "VIDEO_MVP_ENV_FILE": "/private/tmp/no-such-adsure-env",
    "VIDEO_MVP_VOLC_SPEECH_API_KEY": "test-api-key",
    "VIDEO_MVP_VOLC_SPEECH_INLINE_DATA": "1",
    "VIDEO_MVP_VOLC_POLL_INTERVAL_S": "0",
    "VIDEO_MVP_VOLC_POLL_TIMEOUT_S": "5",
}


class _FakeContainer:
    streams = [object()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def demux(self, stream):
        return iter(())

    def add_stream_from_template(self, stream):
        return object()

    def mux(self, packet):
        return None


class VolcAsrProtocolTests(unittest.TestCase):
    def setUp(self):
        self.posts = []

    def _fake_post(self, url, body, headers, timeout):
        self.posts.append((url, body, headers))
        if url.endswith("/submit"):
            return {}
        if len(self.posts) == 2:
            return {}
        if len(self.posts) == 3:
            return {"resp": {"code": 1001}}
        return {"audio_info": {"duration": 1800},
                "result": {"result": {"text": "这款粉底液堪称瑕疵橡皮擦", "utterances": [
                    {"text": "这款粉底液堪称瑕疵橡皮擦", "start_time": 200, "end_time": 1800,
                     "words": [{"text": "橡皮擦", "start_time": 1200, "end_time": 1800,
                                "confidence": 0}]}]}}}

    def _fake_audio(self, *args, **kwargs):
        return np.ones(16000, dtype=np.float32) * 0.1

    def test_submit_poll_and_millisecond_timestamps(self):
        fake_av = types.SimpleNamespace(open=lambda *a, **k: _FakeContainer())
        audio_mod = types.SimpleNamespace(decode_audio=self._fake_audio)
        env = {**VOLC_ENV}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(volc_asr, "_tracks", return_value=[{"index": 0, "offset": 0.0}]), \
             patch.object(volc_asr, "_post_json", side_effect=self._fake_post), \
             patch.dict(sys.modules, {"av": fake_av, "faster_whisper.audio": audio_mod}):
            report = volc_asr.transcribe_worker(Path("fixture.mp4"), "化妆品")

        self.assertEqual("transcribed", report["status"])
        self.assertEqual("volcengine/seed-asr-bigmodel", report["provider"])
        self.assertEqual("live_validated_20260917", report["model_provenance"]["live_validation_status"])
        segment = report["segments"][0]
        self.assertEqual("这款粉底液堪称瑕疵橡皮擦", segment["text"])
        self.assertEqual((0.2, 1.8), (segment["start"], segment["end"]))
        self.assertEqual(1.2, segment["words"][0]["start"])

        submit_url, submit_body, headers = self.posts[0]
        self.assertTrue(submit_url.endswith("/api/v3/auc/bigmodel/submit"))
        self.assertEqual("test-api-key", headers["x-api-key"])
        self.assertEqual("volc.seedasr.auc", headers["X-Api-Resource-Id"])
        self.assertTrue(headers["X-Api-Request-Id"])
        # 凭据只能出现在专用请求头，不能进入 URL 或请求体（后者会被留痕）。
        self.assertNotIn("test-api-key", submit_url)
        self.assertNotIn("test-api-key", repr(submit_body))
        self.assertNotIn("hotwords", submit_body["request"])
        self.assertEqual("bigmodel", submit_body["request"]["model_name"])
        self.assertEqual("volc.seedasr.auc", headers["X-Api-Resource-Id"])
        wav = base64.b64decode(submit_body["audio"]["data"])
        self.assertEqual(b"RIFF", wav[:4])
        self.assertEqual("raw", submit_body["audio"]["codec"])

        query_url, query_body, _ = self.posts[2]
        self.assertTrue(query_url.endswith("/query"))
        self.assertEqual({}, query_body)

    def test_missing_credentials_does_not_call_remote(self):
        with patch.dict(os.environ, {"VIDEO_MVP_ENV_FILE": "/private/tmp/no-such-adsure-env"}, clear=True), \
             patch.object(volc_asr, "_post_json") as post:
            report = volc_asr.transcribe_worker(Path("fixture.mp4"), "化妆品")
        self.assertEqual("failed", report["status"])
        post.assert_not_called()

    def test_protocol_error_is_redacted(self):
        def post(url, body, headers, timeout):
            if url.endswith("/submit"):
                return {}
            return {"header": {"code": 2002, "message": "sk-secret"}}

        fake_av = types.SimpleNamespace(open=lambda *a, **k: _FakeContainer())
        audio_mod = types.SimpleNamespace(decode_audio=self._fake_audio)
        with patch.dict(os.environ, {**VOLC_ENV}, clear=False), \
             patch.object(volc_asr, "_tracks", return_value=[{"index": 0, "offset": 0.0}]), \
             patch.object(volc_asr, "_post_json", side_effect=post), \
             patch.dict(sys.modules, {"av": fake_av, "faster_whisper.audio": audio_mod}):
            report = volc_asr.transcribe_worker(Path("fixture.mp4"), "化妆品")
        self.assertEqual("failed", report["status"])
        self.assertNotIn("sk-secret", repr(report))
        self.assertIn("2002", report["track_results"][0]["error"])


class VolcEngineWiringTests(unittest.TestCase):
    def test_run_worker_selects_volc_and_keeps_local_verification(self):
        from src.video_mvp import asr
        primary = {"status": "transcribed", "provider": "volcengine/seed-asr-bigmodel",
                   "segments": [{"text": "原相机无滤镜", "start": 0, "end": 1, "audio_track": 1,
                                 "words": [{"word": "原相机无滤镜", "start": 0, "end": 1}]}],
                   "track_results": [{"status": "transcribed"}]}
        secondary = {"status": "transcribed", "provider": "sherpa-onnx/SenseVoice",
                     "segments": [{"text": "原相机无滤镜", "start": 0, "end": 1, "audio_track": 1,
                                   "words": [{"word": "原相机无滤镜", "start": 0, "end": 1}]}]}
        with patch.dict(os.environ, {"VIDEO_MVP_ASR_ENGINE": "volc"}), \
             patch("src.video_mvp.chinese_asr.readiness",
                   return_value={"dependency_ready": True, "model_ready": True}), \
             patch("src.video_mvp.chinese_asr.run_worker", return_value=secondary), \
             patch("src.video_mvp.volc_asr.transcribe_worker", return_value=primary) as worker, \
             patch("src.video_mvp.volc_asr.volc_readiness",
                   return_value={"configured": True, "provider": "volcengine/seed-asr-bigmodel"}):
            result = asr.run_worker(Path("fixture.mp4"), "化妆品")
        worker.assert_called_once()
        self.assertEqual("化妆品", worker.call_args.args[1])
        self.assertEqual("sherpa-onnx/SenseVoice", result["verification"]["provider"])
        self.assertEqual("cross_checked_unverified", result["quality_status"])

    def test_run_worker_reads_engine_choice_from_selected_env_file(self):
        from src.video_mvp import asr
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("VIDEO_MVP_ASR_ENGINE=volc\nVIDEO_MVP_VOLC_SPEECH_API_KEY=test-key\n")
            env_path = handle.name
        primary = {"status": "transcribed", "provider": "volcengine/seed-asr-bigmodel",
                   "segments": [], "track_results": [{"status": "no_speech_detected"}]}
        try:
            with patch.dict(os.environ, {"VIDEO_MVP_ENV_FILE": env_path}, clear=True), \
                 patch("src.video_mvp.chinese_asr.readiness",
                       return_value={"dependency_ready": False, "model_ready": False}), \
                 patch("src.video_mvp.volc_asr.transcribe_worker", return_value=primary) as worker, \
                 patch("src.video_mvp.volc_asr.volc_readiness",
                       return_value={"configured": True, "provider": "volcengine/seed-asr-bigmodel"}):
                asr.run_worker(Path("fixture.mp4"), "化妆品")
            worker.assert_called_once()
        finally:
            Path(env_path).unlink(missing_ok=True)

    def test_health_snapshot_exposes_volc_without_secret(self):
        from src.video_mvp.asr import readiness
        snapshot = readiness()
        self.assertIn("volc", snapshot)
        self.assertNotIn("access_key", str(snapshot).lower())

    def test_invalid_engine_rejected(self):
        from src.video_mvp import asr
        with patch.dict(os.environ, {"VIDEO_MVP_ASR_ENGINE": "nope"}):
            with self.assertRaises(ValueError):
                asr.run_worker(Path("fixture.mp4"))

    def test_official_default_requires_public_audio_url(self):
        fake_av = types.SimpleNamespace(open=lambda *a, **k: _FakeContainer())
        audio_mod = types.SimpleNamespace(decode_audio=lambda *a, **k: np.ones(16000, dtype=np.float32) * .1)
        env = {"VIDEO_MVP_ENV_FILE": "/private/tmp/no-such-adsure-env",
               "VIDEO_MVP_VOLC_SPEECH_API_KEY": "test-api-key"}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(volc_asr, "_tracks", return_value=[{"index": 0, "offset": 0.0}]), \
             patch.object(volc_asr, "_post_json") as post, \
             patch.dict(sys.modules, {"av": fake_av, "faster_whisper.audio": audio_mod}):
            report = volc_asr.transcribe_worker(Path("fixture.mp4"), "化妆品")
        post.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertIn("audio_public_url_required", report["track_results"][0]["error"])

    def test_hotwords_remain_disabled_by_default(self):
        with patch.dict(os.environ, {"VIDEO_MVP_ENV_FILE": "/private/tmp/no-such-adsure-env"}, clear=True):
            self.assertEqual([], volc_asr._hotwords("化妆品"))


class ArkDefaultTests(unittest.TestCase):
    def test_ark_default_flagship_model(self):
        from src.video_mvp.cloud_config import config
        env = {"VIDEO_MVP_VLM_PROVIDER": "cloud",
               "VIDEO_MVP_CLOUD_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
               "VIDEO_MVP_ENV_FILE": "/private/tmp/no-such-adsure-env"}
        with patch.dict(os.environ, env, clear=False):
            cloud = config()
        self.assertEqual("doubao-seed-2-1-pro-260915", cloud.model)


if __name__ == "__main__":
    unittest.main()
