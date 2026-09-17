# -*- coding: utf-8 -*-
"""对答案：把系统产出与预先埋好的 ground truth 逐条比对，给出召回与误报。

    python backend/scripts/score_truth.py out/truth/ground_truth.json out/gt_report.json

两条纪律，都是踩过才写下来的：

1. **只用命中的词条本身判定，不能拿"风险表达"去匹配。**
   风险表达里含上下文原文，用它匹配会把"上下文里出现过某词"错判成
   "该词被命中"，凭空造出根本不存在的误报。（第一版就犯了这个错。）

2. **「正确抑制」必须以「取证层确实读到了这段文字」为前提。**
   若对照词根本没被 OCR/ASR 读出来，它没被命中不是白名单起了作用，
   而是压根没走到判断那一步 —— 记成成绩就是自欺。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    gt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rp = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    ev = {"口播": "", "画面": ""}
    for e in rp["evidence"]:
        ev["口播" if e["source"] == "asr" else "画面"] += e["text"]
    all_text = ev["口播"] + ev["画面"]

    hits = []
    for f in rp["findings"]:
        m = re.search(r"「([^」]+)」", f["title"] or "")
        hits.append((f["t_start"], f["t_end"], m.group(1) if m else (f["title"] or "")))

    def find(term, a, b):
        return next((h for h in hits
                     if term in h[2] and not (h[1] < a - 1.0 or h[0] > b + 1.0)), None)

    print("=" * 74)
    print("  对答案：构造广告（答案预先写死，非真实投放素材）")
    print("=" * 74)
    print(f"取证：口播 {len(ev['口播'])} 字 · 画面 {len(ev['画面'])} 字")
    print(f"口播识别内容：{ev['口播'][:70]}\n")

    print("【应命中】")
    tp = 0
    for e in gt["expect_hit"]:
        term, ch, (a, b) = e["term"], e["channel"], e["at"]
        got = find(term, a, b)
        if got:
            tp += 1
            print(f"  ✓ {ch}「{term}」预期 {a}-{b}s → 命中 {got[0]:.2f}-{got[1]:.2f}s")
        else:
            why = "取证层已读到，找法漏检" if term in ev[ch] else "**取证层根本没读到这段文字**"
            print(f"  ✗ {ch}「{term}」预期 {a}-{b}s → 未命中（{why}）")
    print(f"  召回：{tp}/{len(gt['expect_hit'])}\n")

    print("【应不命中（误报对照组）】")
    ok = 0
    for e in gt["expect_not_hit"]:
        term = e["term"]
        if any(term in h[2] for h in hits):
            print(f"  ✗ 「{term}」被误报 —— {e['why']}")
        elif term in all_text:
            ok += 1
            print(f"  ✓ 「{term}」取证层读到了，且未被误报")
        else:
            print(f"  ⚠ 「{term}」取证层没读到，**本条不构成有效对照**，不计成绩")
    print(f"  有效抑制：{ok}/{len(gt['expect_not_hit'])}\n")

    print("【L4 必备要素显著性】")
    g = gt["expect_l4"]
    l4 = next((f for f in rp["findings"] if g["requirement"] in f["title"]), None)
    if not l4:
        print(f"  ✗ 未产出「{g['requirement']}」相关结论")
    else:
        print(f"  产出：{l4['title']}")
        print(f"  预期：{g['verdict']}（埋点 时长 {g['duration_s']}s / "
              f"字高 {g['font_scale']*100:.2f}%）")
        print(f"  取证层是否读到那行小字：{'是' if g['text'] in ev['画面'] else '否'}")
        expr = l4.get("报告", {}).get("风险表达", "")
        if expr:
            print(f"  量化依据：{expr[:130]}")

    print("\n【时间定位】")
    print("  注：口播项的偏差是相对「整句窗口」的，系统定位的是句中那个「词」——")
    print("      落在窗口内即为正确，这正是「定位到词不是句」的产品承诺。")
    for e in gt["expect_hit"]:
        term, ch, (a, b) = e["term"], e["channel"], e["at"]
        got = find(term, a, b)
        if got:
            tag = "（词在句中）" if ch == "口播" else ""
            print(f"  {ch}「{term}」{got[0]:.2f}-{got[1]:.2f}s　"
                  f"埋点 {a}-{b}s　起点差 {got[0]-a:+.2f}s {tag}")


if __name__ == "__main__":
    main()
