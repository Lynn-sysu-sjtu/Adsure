# -*- coding: utf-8 -*-
"""
规则引擎检测器（确定性层：关键词 + 正则）
用规则库对案例库逐条检测，输出命中规则/依据/后果，并与人工标注对比，给出召回与覆盖缺口。
用法： <python> detect.py
"""
import json, re
import pandas as pd

RULES_FN = "美妆广告合规规则库_v0.2_统一schema.json"
CASES_FN = "广告违规案例库(1).xlsx"
OUT_FN = "检测结果_v0.2.xlsx"

with open(RULES_FN, "r", encoding="utf-8") as f:
    lib = json.load(f)
rules = lib["rules"]
sources = {s["id"]: s for s in lib["legal_sources"]}


def basis_str(rule):
    parts = []
    for lb in rule.get("legal_basis", []):
        src = sources.get(lb["source_id"], {})
        parts.append(f"{src.get('short', lb['source_id'])}{lb.get('article','')}")
    return "；".join(parts)


def consequence_str(rule):
    c = rule.get("consequence", {}) or {}
    out = []
    if c.get("legal"):
        out.append("法律：" + c["legal"].get("summary", ""))
    if c.get("platform"):
        out.append("平台：" + c["platform"].get("summary", ""))
    return " | ".join(out)


def match_rule(text, rule):
    """返回命中的关键词/正则列表（确定性层）"""
    hits = []
    ks = rule.get("detection", {}).get("keyword_signals", {})
    for term in ks.get("hit_terms", []):
        if term and term in text:
            hits.append(term)
    for pat in ks.get("regex", []):
        try:
            if re.search(pat, text):
                hits.append(f"/{pat}/")
        except re.error:
            pass
    return hits


def detect(text):
    text = str(text or "")
    matched = []
    for r in rules:
        hits = match_rule(text, r)
        if hits:
            matched.append((r, hits))
    return matched


def is_compliant_sample(type_val):
    s = str(type_val)
    return ("合规" in s) or s.strip() in ("无", "nan", "")


def run_sheet(sheet, text_col, type_col, risk_col, industry_col="行业领域"):
    df = pd.read_excel(CASES_FN, sheet_name=sheet)
    rows = []
    # 混淆矩阵（仅美妆范围内统计）
    TP = FN = FP = TN = 0
    fn_list, fp_list, oos_list = [], [], []
    for _, row in df.iterrows():
        text = str(row.get(text_col, ""))
        matched = detect(text)
        flagged = bool(matched)
        industry = str(row.get(industry_col, "")).strip()
        in_scope = (industry == "美妆")
        compliant = is_compliant_sample(row.get(type_col, ""))
        no = row.get("编号", "")
        if not in_scope:
            scope_tag = f"范围外({industry})"
            oos_list.append((no, industry, row.get(type_col, "")))
        else:
            scope_tag = "美妆"
            if compliant and flagged:
                FP += 1; fp_list.append((no, row.get(type_col, "")))
            elif compliant and not flagged:
                TN += 1
            elif (not compliant) and flagged:
                TP += 1
            else:
                FN += 1; fn_list.append((no, row.get(type_col, "")))
        rows.append({
            "编号": no,
            "范围": scope_tag,
            "文案": text[:60],
            "案例库_违规类型": row.get(type_col, ""),
            "案例库_风险": row.get(risk_col, ""),
            "引擎_是否命中": "✔命中" if flagged else "✘未命中",
            "引擎_命中规则": "；".join(f"{r['rule_id']}({r['title'][:10]})" for r, _ in matched),
            "引擎_命中词": "；".join(sorted({h for _, hs in matched for h in hs})),
            "引擎_依据法条": " ‖ ".join(basis_str(r) for r, _ in matched),
            "引擎_后果": " ‖ ".join(consequence_str(r) for r, _ in matched),
            "引擎_处置": " ‖ ".join(r.get("disposition", "") for r, _ in matched),
        })
    out = pd.DataFrame(rows)
    print(f"\n===== {sheet} =====")
    print(f"美妆违规样本: 命中(TP)={TP} 漏报(FN)={FN}  ->  召回率={TP/(TP+FN)*100:.0f}%" if (TP+FN) else "无美妆违规样本")
    print(f"美妆合规样本: 误报(FP)={FP} 正确放行(TN)={TN}")
    print(f"范围外(非美妆)样本: {len(oos_list)} 条（当前美妆规则不处理，属正常）")
    if fn_list:
        print(f"-- 美妆漏报(真缺口，应补规则) {len(fn_list)} 条：")
        for no, t in fn_list:
            print(f"     {no}: {t}")
    if fp_list:
        print(f"-- 美妆误报(应放行却报警，需收紧词表) {len(fp_list)} 条：")
        for no, t in fp_list:
            print(f"     {no}: {t}")
    return out


def show_examples(out, n=3):
    hit = out[out["引擎_是否命中"] == "✔命中"]
    print(f"\n--- 命中示例（引擎给出依据，共{len(hit)}条命中，展示前{n}条）---")
    for _, r in hit.head(n).iterrows():
        print(f"[{r['编号']}] 文案：{r['文案']}")
        print(f"     命中规则：{r['引擎_命中规则']}")
        print(f"     命中词：{r['引擎_命中词']}")
        print(f"     依据：{r['引擎_依据法条']}")
        print(f"     案例库标注：{r['案例库_违规类型']}\n")


print("规则库规则数：", len(rules), "→", [r["rule_id"] for r in rules])
out1 = run_sheet("真实处罚案例", "违规广告文案原文", "违规类型", "风险等级")
out2 = run_sheet("推测文案案例", "违规广告文案（推测还原）", "违规类型", "风险等级")
show_examples(out2, 4)

with pd.ExcelWriter(OUT_FN, engine="openpyxl") as w:
    out1.to_excel(w, sheet_name="真实案例_检测结果", index=False)
    out2.to_excel(w, sheet_name="推测案例_检测结果", index=False)
print(f"\n结果已写入 {OUT_FN}")
