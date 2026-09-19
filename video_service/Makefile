PYTHON ?= .venv-video/bin/python

.PHONY: video-service preflight-video smoke-video-service test-video-service test-video-mvp

video-service:
	VIDEO_SERVICE_HOST=127.0.0.1 VIDEO_SERVICE_PORT=8520 ./scripts/start_video_service.sh

preflight-video:
	$(PYTHON) -m scripts.preflight_video

smoke-video-service:
	$(PYTHON) scripts/smoke_video_service.py

test-video-service:
	$(PYTHON) -m unittest tests.test_video_service tests.test_video_mvp_v3 tests.test_video_volc_asr tests.test_video_rapidocr_env -v

test-video-mvp:
	$(PYTHON) -m unittest tests.test_video_mvp tests.test_video_mvp_v2 tests.test_video_mvp_v3 tests.test_video_feishu_adapter tests.test_video_service -v
