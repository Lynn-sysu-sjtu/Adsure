# Adsure Video Service

视频素材解析服务独立目录。该服务只负责视频取证：抽帧、ASR、OCR、视觉语义观察、证据留痕，并通过 HTTP 调用 rule_engine。

## 目录说明

- `src/video_service/`：视频解析服务 API、worker、extractor、store。
- `src/video_mvp/`：视频 MVP 的 ASR、OCR、视觉、规则适配。
- `backend/`：证据层、provider、IP 检测和视频相关测试。
- `deploy/systemd/adsure-video.service`：systemd 示例。
- `deploy/video.env.example`：非敏感环境变量模板。
- `scripts/`：启动、预检、冒烟、清理和模型准备脚本。
- `data/rules/`、`data/platform_rules/`：视频规则和平台规则快照。
- `datasets/golden/`：视频 golden set 框架。

## 不包含

- `.env`、真实密钥
- `.venv*`、`__pycache__`、`.pytest_cache`
- `data/video_mvp/models/` 模型大文件
- `data/video_mvp/jobs/`、`data/video_service/` 临时输出

模型和密钥按部署文档在服务器上单独准备。

## 依赖与证据完整性

- 安装依赖：`.venv-video/bin/pip install -r requirements-video.txt`
  （含主抽取链路必需的 **PyAV `av`**，缺失时 `scripts/preflight_video.py` 直接失败）。
- `data/platform_rules/raw_*` 与 `datasets/golden/**` 在 `.gitattributes` 中标记为
  `-text`：这些是带 SHA256 记录的原始证据，必须逐字节保存，禁止任何换行符转换。
- `data/schemas/audit_response_v0.2.schema.json` 是飞书 v0.2 审核响应的契约文件，
  由 `tests/test_video_feishu_adapter.py` 校验。

## 本地测试

```bash
python -m unittest \
  tests.test_video_service \
  tests.test_video_mvp_v3 \
  tests.test_video_volc_asr \
  tests.test_video_rapidocr_env -v
```

## 预检与启动

```bash
cp deploy/video.env.example /etc/adsure/video.env
.venv-video/bin/python -m scripts.preflight_video
./scripts/start_video_service.sh
```

模型文件不在 Git 中，Linux 服务器上执行：

```bash
bash scripts/setup_video_models.sh
```

完整部署说明见 `docs/视频素材解析服务部署.md`。
