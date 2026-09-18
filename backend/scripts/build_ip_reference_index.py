# -*- coding: utf-8 -*-
"""IP 参考图收集与索引构建工具（实施方案 v2 §5 阶段 2）。

两个子命令：

1. extract —— 从视频抽帧生成候选图（人工从中挑选参考图）：
     python backend/scripts/build_ip_reference_index.py extract \
         测试广告视频1.mp4 --out datasets/ip_reference/candidates/视频1

2. index  —— 把人工确认的参考图目录算 SSCD embedding 入索引：
     python backend/scripts/build_ip_reference_index.py index \
         datasets/ip_reference/confirmed/disney_mickey/ --ip-id disney_mickey

⚠️ 参考图来源纪律（AGENTS.md）：
   - 用**自己拍摄/自制**的素材，或权利方公开授权的图；
   - 不从搜索引擎/社交媒体爬版权图入库（版权全保留）；
   - 参考图仅内部特征比对，不对外分发（方案 §12 风险登记册）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from app.ip.sscd import SSCDEmbedder  # noqa: E402
from app.ip.vectors import PurePythonVectorIndex, VectorMeta  # noqa: E402

PROJECT_ROOT = _HERE.resolve().parents[1]  # backend/scripts → backend → 项目根
INDEX_PATH = PROJECT_ROOT / "data" / "ip_models" / "reference_index.json"


def cmd_extract(args) -> None:
    """抽帧：场景关键帧 ∪ 2fps，pHash 去重，输出候选图供人工挑选。"""
    from app.config import get_settings
    from app.pipeline.extract import extract

    video = Path(args.video)
    out = Path(args.out)
    cfg = get_settings().pipeline
    ex = extract(video, out / "_work", cfg)
    kept = []
    for f in ex.frames:
        if f.path and f.path.exists():
            dest = out / f.path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.path.read_bytes())
            kept.append({"frame": dest.name, "t": round(f.t, 2),
                         "span": [round(f.span_start, 2), round(f.span_end, 2)]})
    (out / "candidates.json").write_text(json.dumps({
        "video": str(video), "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "candidates": kept}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 抽出 {len(kept)} 张候选帧 → {out}")
    print("下一步：人工浏览，把含目标 IP 的图移到 datasets/ip_reference/confirmed/<ip_id>/")


def cmd_index(args) -> None:
    """把 confirmed/<ip_id>/ 下的图全部算 embedding，合并进索引文件。"""
    src = Path(args.dir)
    images = sorted(p for p in src.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not images:
        sys.exit(f"目录里没有图片：{src}")
    embedder = SSCDEmbedder()
    index = PurePythonVectorIndex(dim=embedder.dim)
    if INDEX_PATH.exists():
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        for item in data["vectors"]:
            index.add(item["vector"], VectorMeta(item["ip_id"], item["ref"]))
        print(f"载入已有索引：{len(data['vectors'])} 条")
    added = 0
    for img_path in images:
        from PIL import Image

        vec = embedder.embed_image(Image.open(img_path))
        index.add(vec, VectorMeta(args.ip_id, img_path.name))
        added += 1
    payload = {
        "meta": {"dim": embedder.dim, "model": embedder.name,
                 "updated_at": datetime.now().isoformat(timespec="seconds")},
        "vectors": [
            {"ip_id": m.ip_id, "ref": m.ref_name, "vector": v}
            for v, m in zip(index._vectors, index._metas)
        ],
    }
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(payload), encoding="utf-8")
    counts = index.ip_counts()
    print(f"✅ 新增 {added} 张（{args.ip_id}）；索引共 {len(index)} 条 → {INDEX_PATH}")
    print("各 IP 参考图数：", json.dumps(counts, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="IP 参考图收集与索引构建")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="从视频抽帧生成候选图")
    e.add_argument("video", type=Path)
    e.add_argument("--out", type=Path, required=True)

    i = sub.add_parser("index", help="把确认的参考图算 embedding 入索引")
    i.add_argument("dir", type=Path, help="confirmed/<ip_id>/ 目录")
    i.add_argument("--ip-id", required=True)

    args = ap.parse_args()
    {"extract": cmd_extract, "index": cmd_index}[args.cmd](args)


if __name__ == "__main__":
    main()
