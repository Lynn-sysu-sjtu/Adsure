# ASR 字级时间戳人工标签

方案 §11 硬指标：**ASR 字级时间戳误差 ≤ 0.5s**。供应商不能用自己的输出自证，
每条标签的 true_start/true_end 必须由人工听音频核对（建议用播放器逐帧/0.1s 步进）。

用法：

```bash
PYTHONPATH=backend .venv-handoff/bin/python \
  backend/scripts/verify_asr_word_timestamps.py measure \
  data/video_mvp/jobs/<job_id>/asr_raw.json \
  --labels datasets/golden/asr_timestamp_labels/<name>.yaml
```

标签格式见 `example.yaml`（示例值为占位，不是实测结论，禁止作为指标引用）。
建议每个供应商、每种素材（快口播/慢口播/有背景音乐）各随机抽 ≥10 个词/短语，
覆盖词头、词尾和跨句位置；全部通过才可在报告中声称时间定位能力达标。
