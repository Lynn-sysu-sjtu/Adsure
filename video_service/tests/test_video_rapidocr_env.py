from __future__ import annotations

import os
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.video_mvp import vision


class EnvFileTests(unittest.TestCase):
    def test_video_env_file_defaults_to_volc_example(self):
        from src.video_mvp.env_config import env_path, load_env
        with patch.dict(os.environ, {}, clear=True):
            path = env_path()
        self.assertEqual(path.name, ".env.video.volc.example")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "custom.env"
            env_file.write_text("VIDEO_MVP_OCR_ENGINE=rapidocr\nIGNORED=x\n", encoding="utf-8")
            with patch.dict(os.environ, {"VIDEO_MVP_ENV_FILE": str(env_file)}, clear=True):
                values = load_env({"VIDEO_MVP_OCR_ENGINE"})
        self.assertEqual({"VIDEO_MVP_OCR_ENGINE": "rapidocr"}, values)

    def test_environment_overrides_file_value(self):
        from src.video_mvp.env_config import load_env
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "custom.env"
            env_file.write_text("VIDEO_MVP_OCR_ENGINE=apple_vision\n", encoding="utf-8")
            with patch.dict(os.environ, {"VIDEO_MVP_ENV_FILE": str(env_file),
                                         "VIDEO_MVP_OCR_ENGINE": "rapidocr"}, clear=True):
                values = load_env({"VIDEO_MVP_OCR_ENGINE"})
        self.assertEqual("rapidocr", values["VIDEO_MVP_OCR_ENGINE"])


class RapidOCRMappingTests(unittest.TestCase):
    def test_recognize_manifest_maps_polygon_confidence_and_provider(self):
        frame = Path("/private/tmp/adsure-rapid-frame.jpg")
        manifest = [{"frameId": "frame_00000001", "timestamp": 2.5, "imagePath": str(frame)}]
        polygon = [[10.0, 20.0], [110.0, 20.0], [110.0, 60.0], [10.0, 60.0]]
        polygon = [[10.0, 20.0], [110.0, 20.0], [110.0, 60.0], [10.0, 60.0]]

        class _RapidOCR:
            def __call__(self, path):
                return ([[polygon, "登录领20抽", 0.97]], {"ocr": [1.0]})

        fake_module = types.ModuleType("rapidocr_onnxruntime")
        fake_module.RapidOCR = _RapidOCR
        with patch.dict(sys.modules, {"rapidocr_onnxruntime": fake_module}), \
             patch("cv2.imread", return_value=np.zeros((100, 200, 3), dtype=np.uint8)):
            result = vision._recognize_manifest_rapidocr(manifest)
        self.assertEqual([], result["errors"])
        item = result["frames"][0]
        self.assertEqual(2.5, item["timestamp"])
        self.assertEqual("RapidOCR/ONNXRuntime", item["ocr"][0]["provider"])
        self.assertEqual("登录领20抽", item["ocr"][0]["text"])
        self.assertAlmostEqual(0.97, item["ocr"][0]["confidence"])
        self.assertEqual([0.05, 0.2, 0.5, 0.4], item["ocr"][0]["bbox"])
        self.assertIn("rapidocr-onnxruntime/", result["provider_version"])


if __name__ == "__main__":
    unittest.main()
