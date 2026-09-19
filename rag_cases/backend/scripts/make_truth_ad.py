# -*- coding: utf-8 -*-
"""构造一条**答案已知**的保健食品广告，用作准确率基准。

为什么需要它：在拿到 40–60 条人工标注的真实投放素材之前，
"跑得准不准"这个问题没有任何数据可以回答。而没有能跑的检查，
"看起来做完了"就是唯一信号，人就成了验证循环。

这个脚本用构造代替采集：每个埋点的文本、时间、字号、位置都预先写死，
所以跑完可以直接对答案（配合 `score_truth.py`）。

    # 1) 先合成口播（需要 Windows 中文 TTS 语音）
    powershell -File backend/scripts/make_truth_tts.ps1 -OutDir out/truth

    # 2) 生成广告 + ground truth
    python backend/scripts/make_truth_ad.py out/truth

    # 3) 跑真实链路
    python backend/scripts/review_video.py out/truth/ad_ground_truth.mp4 \
        --industry health_food --out out/gt_report.json

    # 4) 对答案
    python backend/scripts/score_truth.py out/truth/ground_truth.json out/gt_report.json

⚠️ **局限必须说清楚**：真实投放素材的画质、压缩、字体、排版、背景干扰
   与此都不同，所以这里得到的召回/误报**不能外推到真实投放**。
   它能证明的是：在明确知道答案的情况下，系统到底找不找得出来、会不会误报。
   它替代不了那 40–60 条真实标注素材，只是在它们到位之前先建起一道检查。

背景刻意用静态色块：全片只有一个场景、文字却不断变化，
正好检验「不能只抽场景关键帧」这条设计——实测 0 个场景、60 帧采样 → 10 帧，
两条花字与那行 0.4 秒的小字全部被抓到。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FONT = r"C\:/Windows/Fonts/simhei.ttf"
W, H, DUR = 1920, 1080, 30.0

# (id, 文本, 起, 止, 字号, x, y, 期望)
OVERLAYS = [
    ("o_sales", "全网销量第一", 5.0, 6.5, 72, "(w-tw)/2", "200", "命中 L1 绝对化用语"),
    ("o_cure", "三天彻底根治老胃病", 8.0, 9.2, 72, "(w-tw)/2", "300", "命中 L2 疾病治疗"),
    ("o_promo", "限时特惠", 8.0, 8.5, 56, "(w-tw)/2", "800", "同屏另一条花字，不应与上条合并"),
    ("o_ship", "第一时间发货", 15.0, 17.0, 60, "(w-tw)/2", "500", "**不应命中**（执法指南豁免）"),
    # L4 埋点：又小（2.0% < 2.5%）、又短（0.4s < 1.0s）、又贴边
    ("o_disc", "本品不能代替药物", 28.1, 28.5, 22, "w-tw-28", "h-th-22", "L4 判「已出现但不显著」"),
]

VOICES = [
    ("vo1.wav", 3.0, "本品采用国家级配方", "命中 L1「国家级」"),
    ("vo2.wav", 12.0, "每天两粒轻松改善睡眠", "**不应命中**（改善为法定保健功能用语）"),
    ("vo3.wav", 20.0, "上市以来销量第一值得信赖", "命中 L1「销量第一」"),
]


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("FFMPEG 失败：\n", (r.stderr or "")[-1500:])
        raise SystemExit(1)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out/truth")
    out.mkdir(parents=True, exist_ok=True)

    missing = [v[0] for v in VOICES if not (out / v[0]).exists()]
    if missing:
        raise SystemExit(
            f"缺少口播文件 {missing}。先跑：\n"
            f"  powershell -File backend/scripts/make_truth_tts.ps1 -OutDir {out}")

    # 1) 口播按已知偏移混音
    parts, labels, cmd = [], [], ["ffmpeg", "-y", "-loglevel", "error"]
    for i, (f, at, _t, _e) in enumerate(VOICES):
        cmd += ["-i", str(out / f)]
        ms = int(at * 1000)
        parts.append(f"[{i}]adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    fc = ";".join(parts) + ";" + "".join(labels) + \
         f"amix=inputs={len(VOICES)}:normalize=0,apad=whole_dur={DUR}[o]"
    voice = out / "voice.wav"
    run(cmd + ["-filter_complex", fc, "-map", "[o]", "-ac", "1", "-ar", "16000", str(voice)])

    # 2) 画面。中文一律走 textfile，避开 drawtext 的转义地狱
    filters = []
    brand = out / "o_brand.txt"
    brand.write_text("秋实牌 益生元固体饮料", encoding="utf-8")
    bp = str(brand).replace("\\", "/").replace(":", r"\:")
    filters.append(f"drawtext=fontfile='{FONT}':textfile='{bp}':fontcolor=0xffe9a8"
                   f":fontsize=44:x=60:y=60")
    for oid, text, t0, t1, size, x, y, _e in OVERLAYS:
        tf = out / f"{oid}.txt"
        tf.write_text(text, encoding="utf-8")
        p = str(tf).replace("\\", "/").replace(":", r"\:")
        filters.append(
            f"drawtext=fontfile='{FONT}':textfile='{p}':fontcolor=white:fontsize={size}"
            f":x={x}:y={y}:enable='between(t,{t0},{t1})'")

    ad = out / "ad_ground_truth.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c=0x14283c:s={W}x{H}:d={DUR}:r=25",
         "-i", str(voice), "-vf", ",".join(filters),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-shortest", str(ad)])
    print(f"广告已生成：{ad}  ({ad.stat().st_size/1024/1024:.2f} MB)")

    gt = {
        "video": str(ad), "duration": DUR, "width": W, "height": H,
        "expect_hit": [
            {"term": "国家级", "channel": "口播", "at": [3.0, 6.4]},
            {"term": "销量第一", "channel": "画面", "at": [5.0, 6.5]},
            {"term": "根治", "channel": "画面", "at": [8.0, 9.2]},
            {"term": "销量第一", "channel": "口播", "at": [20.0, 23.8]},
        ],
        "expect_not_hit": [
            {"term": "改善", "why": "法定保健功能用语，收进禁用语会把合规产品全打成违规"},
            {"term": "第一时间", "why": "《广告绝对化用语执法指南》豁免情形"},
        ],
        "expect_l4": {
            "requirement": "保健食品必备声明", "text": "本品不能代替药物",
            "at": [28.1, 28.5], "duration_s": 0.4, "font_scale": 22 / H,
            "verdict": "已出现但可能未显著标明",
        },
        "overlays": [{"id": o[0], "text": o[1], "t": [o[2], o[3]],
                      "font_scale": o[4] / H, "expect": o[7]} for o in OVERLAYS],
        "voices": [{"file": v[0], "at": v[1], "text": v[2], "expect": v[3]} for v in VOICES],
    }
    (out / "ground_truth.json").write_text(
        json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ground truth 已落盘：{out/'ground_truth.json'}")
    print(f"埋点：应命中 {len(gt['expect_hit'])} 条 · "
          f"应不命中 {len(gt['expect_not_hit'])} 条 · L4 显著性 1 条")


if __name__ == "__main__":
    main()
