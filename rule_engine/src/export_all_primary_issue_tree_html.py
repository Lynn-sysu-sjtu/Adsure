# -*- coding: utf-8 -*-
"""Export the complete draft L1-L2-L3 issue tree as a review-only HTML."""

from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path


ROOT_ORDER = (
    "SCOPE_ACCESS",
    "PROHIBITED_CONTENT",
    "TRUTHFULNESS",
    "CLAIM_EXPRESSION",
    "EFFICACY_PERFORMANCE",
    "PRICE_PROMOTION",
    "EVIDENCE_FACT",
    "DISCLOSURE_WARNING",
    "ENDORSEMENT_REVIEW",
    "IP_PERSONALITY",
    "MINORS_PUBLIC_ORDER",
    "MATERIAL_PLATFORM",
    "WORKFLOW_DUTY",
)

ROOT_NAMES = {
    "SCOPE_ACCESS": "适用主体与准入",
    "PROHIBITED_CONTENT": "禁止投放内容",
    "TRUTHFULNESS": "宣传真实性",
    "CLAIM_EXPRESSION": "宣称表达方式",
    "EFFICACY_PERFORMANCE": "功效与性能宣称",
    "PRICE_PROMOTION": "价格与促销",
    "EVIDENCE_FACT": "证明材料与事实核验",
    "DISCLOSURE_WARNING": "信息披露与警示语",
    "ENDORSEMENT_REVIEW": "代言、推荐与证明",
    "IP_PERSONALITY": "知识产权与人格权益",
    "MINORS_PUBLIC_ORDER": "未成年人及公序良俗",
    "MATERIAL_PLATFORM": "素材形式与平台规范",
    "WORKFLOW_DUTY": "投放流程与持续义务",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _confidence_for_node(node):
    direct = str(node.get("confidence") or "").lower()
    if direct in {"high", "medium", "low"}:
        return direct
    values = [
        str(item.get("confidence") or "").lower()
        for item in node.get("candidate_clusters") or []
        if str(item.get("confidence") or "").lower() in {"high", "medium", "low"}
    ]
    if "low" in values:
        return "low"
    if "medium" in values:
        return "medium"
    return "high" if values else ""


def _build_root(root_id, root_name, raw_nodes, mappings=None, source_root_id=None):
    source_root_id = source_root_id or root_id
    mappings_by_issue = defaultdict(list)
    for mapping in mappings or []:
        mappings_by_issue[mapping.get("issue_id")].append(mapping.get("rule_uid"))
    normalized = {}
    order = []
    for raw in raw_nodes:
        if raw.get("level") not in {2, 3}:
            continue
        node = {
            "issue_id": raw["issue_id"],
            "parent_issue_id": root_id if raw.get("parent_issue_id") == source_root_id else raw.get("parent_issue_id"),
            "level": int(raw["level"]),
            "node_type": raw.get("node_type") or ("legal_issue" if raw.get("level") == 3 else "directory"),
            "name": raw.get("name") or raw["issue_id"],
            "definition": raw.get("definition") or "",
            "reason": raw.get("reason") or "",
            "confidence": _confidence_for_node(raw),
            "direct_rule_uids": sorted({uid for uid in mappings_by_issue.get(raw["issue_id"], []) if uid} or set(raw.get("source_occurrence_uids") or raw.get("rule_uids") or [])),
            "children": [],
        }
        normalized[node["issue_id"]] = node
        order.append(node["issue_id"])
    root = {
        "issue_id": root_id,
        "parent_issue_id": None,
        "level": 1,
        "node_type": "directory",
        "name": root_name,
        "definition": "",
        "reason": "",
        "confidence": "",
        "direct_rule_uids": [],
        "children": [],
    }
    for issue_id in order:
        node = normalized[issue_id]
        parent_id = node.get("parent_issue_id")
        if parent_id == root_id:
            root["children"].append(node)
        elif parent_id in normalized:
            normalized[parent_id]["children"].append(node)
    return root


def _expand_endorsement_leaf_directories(raw_nodes, clusters):
    """Materialize reviewed cluster groups beneath empty endorsement L2 nodes."""
    nodes = [dict(node) for node in raw_nodes]
    l2_ids = {node["issue_id"] for node in nodes if node.get("level") == 2}
    parents_with_l3 = {
        node.get("parent_issue_id")
        for node in nodes
        if node.get("level") == 3
    }
    used_ids = {node["issue_id"] for node in nodes}
    for cluster in clusters:
        parent_id = cluster.get("recommended_parent")
        if parent_id not in l2_ids or parent_id in parents_with_l3:
            continue
        cluster_key = str(cluster.get("cluster_key") or "CLUSTER")
        issue_id = f"{parent_id}.{cluster_key}"
        suffix = 2
        while issue_id in used_ids:
            issue_id = f"{parent_id}.{cluster_key}_{suffix}"
            suffix += 1
        used_ids.add(issue_id)
        nodes.append({
            "issue_id": issue_id,
            "parent_issue_id": parent_id,
            "level": 3,
            "node_type": "legal_issue",
            "name": cluster.get("canonical_name") or cluster_key,
            "definition": cluster.get("canonical_name") or "",
            "reason": cluster.get("reason") or "",
            "confidence": cluster.get("confidence") or "",
            "rule_uids": cluster.get("member_rule_uids") or [],
        })
    return nodes


def _annotate_counts(node):
    all_rules = set(node.get("direct_rule_uids") or [])
    level_3_count = 1 if node.get("level") == 3 else 0
    for child in node.get("children") or []:
        child_rules, child_l3 = _annotate_counts(child)
        all_rules.update(child_rules)
        level_3_count += child_l3
    node["rule_count"] = len(all_rules)
    node["level_3_count"] = level_3_count
    node["child_count"] = len(node.get("children") or [])
    return all_rules, level_3_count


def assign_numbers(roots):
    def walk(node, prefix):
        node["number"] = prefix
        for index, child in enumerate(node.get("children") or [], 1):
            walk(child, f"{prefix}.{index}")
    for index, root in enumerate(roots, 1):
        walk(root, str(index))
    return roots


def flatten_tree(roots):
    result = []

    def walk(node):
        result.append(node)
        for child in node.get("children") or []:
            walk(child)

    for root in roots:
        walk(root)
    return result


def validate_tree(roots):
    nodes = flatten_tree(roots)
    ids = [item["issue_id"] for item in nodes]
    known = set(ids)
    duplicate_ids = sorted({issue_id for issue_id in ids if ids.count(issue_id) > 1})
    invalid_parents = sorted({
        item.get("parent_issue_id") for item in nodes
        if item.get("parent_issue_id") and item.get("parent_issue_id") not in known
    })
    invalid_levels = sorted({
        item["issue_id"] for item in nodes
        if item.get("level") not in {1, 2, 3}
        or (item.get("parent_issue_id") and next((p for p in nodes if p["issue_id"] == item["parent_issue_id"]), {}).get("level") != item["level"] - 1)
    })
    if duplicate_ids or invalid_parents or invalid_levels:
        raise ValueError(f"invalid issue tree: duplicates={duplicate_ids}, parents={invalid_parents}, levels={invalid_levels}")
    return {
        "root_count": len(roots),
        "node_count": len(nodes),
        "level_1_count": sum(item["level"] == 1 for item in nodes),
        "level_2_count": sum(item["level"] == 2 for item in nodes),
        "level_3_count": sum(item["level"] == 3 for item in nodes),
        "legal_issue_count": sum(item["node_type"] == "legal_issue" for item in nodes),
        "unique_rule_count": len({uid for item in nodes for uid in item.get("direct_rule_uids") or []}),
        "duplicate_ids": duplicate_ids,
        "invalid_parent_ids": invalid_parents,
    }


def load_combined_tree(project_root):
    project_root = Path(project_root)
    roots = []
    assets_root = project_root / "assets" / "all_primary_issue_review_draft_v0.1"
    for root_id in ROOT_ORDER:
        if root_id == "ENDORSEMENT_REVIEW":
            payload = read_json(project_root / "assets" / "endorsement_issue_taxonomy_draft_v0.3.json")
            clusters = read_json(project_root / "assets" / "endorsement_candidate_clusters_draft_v0.3.json")
            raw_nodes = _expand_endorsement_leaf_directories(payload["nodes"], clusters["clusters"])
            roots.append(_build_root(root_id, ROOT_NAMES[root_id], raw_nodes, source_root_id="ENDORSEMENT"))
            continue
        payload = read_json(assets_root / root_id / "review_assets.json")
        roots.append(_build_root(root_id, payload.get("root_name") or ROOT_NAMES[root_id], payload["nodes"], mappings=payload.get("mappings") or []))
    for root in roots:
        _annotate_counts(root)
    assign_numbers(roots)
    validate_tree(roots)
    return roots


def render_document(roots):
    esc = lambda value: html.escape(str(value or ""), quote=True)
    nodes = flatten_tree(roots)
    stats = validate_tree(roots)

    def render(node):
        children = node.get("children") or []
        level = node["level"]
        confidence = node.get("confidence") or ""
        searchable = " ".join((node.get("number") or "", node["issue_id"], node["name"], node.get("definition") or "", node.get("reason") or ""))
        meta = [f'<span class="badge">L{level}</span>']
        if level < 3:
            meta.append(f'<span class="badge">{node.get("child_count", 0)} 个直属子节点</span>')
            meta.append(f'<span class="badge">{node.get("level_3_count", 0)} 个三级问题</span>')
        meta.append(f'<span class="badge">{node.get("rule_count", 0)} 条关联规则</span>')
        if confidence:
            meta.append(f'<span class="badge confidence {esc(confidence)}">{esc(confidence)}</span>')
        details = []
        if node.get("definition"):
            details.append(f'<div><b>问题定义</b><p>{esc(node["definition"])}</p></div>')
        if node.get("reason"):
            details.append(f'<div><b>模型归并理由</b><p>{esc(node["reason"])}</p></div>')
        if level == 3 and not details:
            details.append('<div><b>问题定义</b><p>当前草案未单独提供定义，请结合问题名称及 Excel 中的规则原文审核。</p></div>')
        control = '<button type="button" class="tree-toggle" aria-label="展开或收起子节点" aria-expanded="false">+</button>' if children else '<span class="leaf-mark">•</span>'
        child_html = f'<ul>{"".join(render(child) for child in children)}</ul>' if children else ""
        detail_html = f'<div class="node-detail">{"".join(details)}</div>' if details else ""
        return (
            f'<li class="node level-{level} {"branch" if children else "leaf-node"}" '
            f'data-id="{esc(node["issue_id"])}" data-parent-id="{esc(node.get("parent_issue_id"))}" '
            f'data-level="{level}" data-confidence="{esc(confidence)}" data-search="{esc(searchable.lower())}">'
            f'<div class="node-row">{control}<button type="button" class="node-title"><span class="number">{esc(node["number"])}</span><span class="name">{esc(node["name"])}</span></button>'
            f'<div class="meta">{"".join(meta)}</div></div>{detail_html}{child_html}</li>'
        )

    tree_html = "".join(render(root) for root in roots)
    stats_json = json.dumps(stats, ensure_ascii=False)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Adsure 全部问题树 v0.1</title>
<style>
:root{{--bg:#f2f5f6;--surface:#fff;--ink:#17252a;--muted:#61727a;--line:#d8e1e4;--brand:#174b5c;--brand-soft:#eaf3f5;--accent:#8a5b13;--accent-soft:#fff5dd;--danger:#a13a35;--danger-soft:#fff0ef;--success:#246346;--success-soft:#eaf6ef}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Microsoft YaHei","Noto Sans CJK SC",sans-serif}}header{{background:var(--brand);color:#fff;padding:25px max(22px,5vw)}}header h1{{margin:0;font-size:28px;letter-spacing:0}}header p{{margin:5px 0 0;color:#d8eaef}}main{{max-width:1380px;margin:0 auto;padding:20px 24px 50px}}.summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:15px}}.metric{{background:var(--surface);padding:12px 15px}}.metric strong{{display:block;font-size:22px;font-weight:500}}.metric span{{color:var(--muted)}}.toolbar{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:rgba(255,255,255,.96);border:1px solid var(--line);padding:10px;margin-bottom:14px}}input,select,.action{{height:38px;border:1px solid #becbd0;background:#fff;color:var(--ink);font:inherit;padding:0 11px}}input{{flex:1;min-width:250px}}.action{{cursor:pointer}}.action:hover,.action[aria-pressed="true"]{{border-color:var(--brand);background:var(--brand-soft);color:var(--brand)}}.notice{{margin-left:auto;color:var(--danger);font-size:12px}}.tree-shell{{background:var(--surface);border:1px solid var(--line);padding:10px 20px 25px}}ul{{list-style:none;margin:0;padding:0}}.node{{border-bottom:1px solid #edf1f2}}.node ul{{margin-left:26px;padding-left:18px;border-left:1px solid var(--line)}}.node-row{{display:flex;align-items:center;gap:8px;min-height:49px;padding:7px 5px}}.node-row:hover{{background:#f7fafb}}.tree-toggle,.leaf-mark{{flex:0 0 27px;width:27px;height:27px;text-align:center}}.tree-toggle{{border:1px solid #aac1c9;background:var(--brand-soft);color:var(--brand);font-size:17px;cursor:pointer}}.leaf-mark{{color:#9aa9af;padding-top:2px}}.node-title{{display:flex;align-items:baseline;gap:9px;min-width:210px;max-width:600px;padding:0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer;font:inherit}}.number{{flex:none;color:var(--brand);font-weight:500;min-width:42px}}.name{{font-weight:500;font-size:15px}}.level-1>.node-row .name{{font-size:19px;color:var(--brand)}}.level-2>.node-row .name{{font-size:16px;color:#315b69}}.meta{{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}}.badge{{display:inline-block;padding:2px 7px;border:1px solid #dbe3e6;background:#f4f6f7;color:#586970;font-size:11px;white-space:nowrap}}.badge.confidence.high{{background:var(--success-soft);color:var(--success)}}.badge.confidence.medium{{background:var(--accent-soft);color:var(--accent)}}.badge.confidence.low{{background:var(--danger-soft);color:var(--danger)}}.node-detail{{display:none;margin:0 8px 12px 36px;padding:10px 14px;border-left:3px solid #b9d0d7;background:#f8fbfc;max-width:1080px}}.node-detail.open{{display:grid;gap:8px}}.node-detail b{{color:#315b69}}.node-detail p{{margin:2px 0;white-space:pre-wrap}}.collapsed>ul{{display:none}}.hidden{{display:none}}.match>.node-row{{background:var(--accent-soft)}}.empty{{display:none;text-align:center;color:var(--muted);padding:45px}}footer{{color:var(--muted);padding-top:12px;font-size:12px}}
@media(max-width:820px){{main{{padding:12px 9px 35px}}header{{padding:20px 16px}}header h1{{font-size:23px}}.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}.tree-shell{{padding:8px 8px 20px}}.node ul{{margin-left:12px;padding-left:9px}}.node-row{{align-items:flex-start;flex-wrap:wrap}}.node-title{{min-width:0;flex:1}}.meta{{width:100%;margin-left:35px}}.notice{{width:100%;margin-left:0}}input{{min-width:180px}}}}
</style></head><body><header><h1>广告合规规则引擎 · 全部问题树</h1><p>一级、二级、三级问题关系总览 | v0.1</p></header><main>
<section class="summary" id="summary"></section>
<div class="toolbar"><input id="search" type="search" aria-label="搜索问题" placeholder="搜索编号、问题名称、定义或问题 ID"><select id="confidence" aria-label="筛选置信度"><option value="">全部置信度</option><option value="high">高置信度</option><option value="medium">中置信度</option><option value="low">低置信度</option></select><button type="button" class="action" id="review-only" aria-pressed="false">仅看中低置信度</button><button type="button" class="action" id="expand">全部展开</button><button type="button" class="action" id="collapse">全部收起</button><button type="button" class="action" id="clear">清除筛选</button><span class="notice">draft，仅供目录关系审核</span></div>
<section class="tree-shell"><ul id="tree">{tree_html}</ul><div class="empty" id="empty">没有匹配的问题节点</div></section>
<footer>具体规则原文、重复来源、赛道污染和人工调整请在《全部一级问题统一人工审核表》中处理。</footer></main>
<script>
const stats={stats_json};
document.getElementById('summary').innerHTML=[['level_1_count','一级问题'],['level_2_count','二级问题'],['level_3_count','三级问题'],['unique_rule_count','已关联规则']].map(([key,label])=>`<div class="metric"><strong>${{stats[key]}}</strong><span>${{label}}</span></div>`).join('');
const nodes=[...document.querySelectorAll('.node')];
const byId=new Map(nodes.map(node=>[node.dataset.id,node]));
function setOpen(node,open){{if(!node.classList.contains('branch'))return;node.classList.toggle('collapsed',!open);const button=node.querySelector(':scope>.node-row>.tree-toggle');if(button){{button.textContent=open?'−':'+';button.setAttribute('aria-expanded',String(open));}}}}
function showAncestors(node){{let parent=byId.get(node.dataset.parentId);while(parent){{parent.classList.remove('hidden');setOpen(parent,true);parent=byId.get(parent.dataset.parentId);}}}}
function showDescendants(node){{node.querySelectorAll('.node').forEach(child=>child.classList.remove('hidden'));}}
document.querySelectorAll('.tree-toggle').forEach(button=>button.addEventListener('click',()=>{{const node=button.closest('.node');setOpen(node,node.classList.contains('collapsed'));}}));
document.querySelectorAll('.node-title').forEach(button=>button.addEventListener('click',()=>{{const detail=button.closest('.node').querySelector(':scope>.node-detail');if(detail)detail.classList.toggle('open');}}));
document.getElementById('expand').addEventListener('click',()=>nodes.forEach(node=>setOpen(node,true)));
document.getElementById('collapse').addEventListener('click',()=>nodes.forEach(node=>setOpen(node,false)));
const reviewButton=document.getElementById('review-only');
reviewButton.addEventListener('click',()=>{{const active=reviewButton.getAttribute('aria-pressed')!=='true';reviewButton.setAttribute('aria-pressed',String(active));document.getElementById('confidence').value='';filterTree();}});
function filterTree(){{const query=document.getElementById('search').value.trim().toLowerCase();const confidence=document.getElementById('confidence').value;const reviewOnly=reviewButton.getAttribute('aria-pressed')==='true';const filtering=Boolean(query||confidence||reviewOnly);nodes.forEach(node=>{{node.classList.toggle('hidden',filtering);node.classList.remove('match');}});if(!filtering){{nodes.forEach(node=>node.classList.remove('hidden'));document.getElementById('empty').style.display='none';return;}}let matches=0;nodes.forEach(node=>{{const queryMatch=!query||node.dataset.search.includes(query);const confidenceMatch=!confidence||node.dataset.confidence===confidence;const reviewMatch=!reviewOnly||['medium','low'].includes(node.dataset.confidence);if(queryMatch&&confidenceMatch&&reviewMatch){{node.classList.remove('hidden');if(query)node.classList.add('match');showAncestors(node);if(query&&Number(node.dataset.level)<3)showDescendants(node);matches++;}}}});document.getElementById('empty').style.display=matches?'none':'block';}}
document.getElementById('search').addEventListener('input',filterTree);document.getElementById('confidence').addEventListener('change',()=>{{reviewButton.setAttribute('aria-pressed','false');filterTree();}});document.getElementById('clear').addEventListener('click',()=>{{document.getElementById('search').value='';document.getElementById('confidence').value='';reviewButton.setAttribute('aria-pressed','false');filterTree();}});nodes.forEach(node=>setOpen(node,false));
</script></body></html>'''


def export_html(project_root, output_path):
    roots = load_combined_tree(project_root)
    stats = validate_tree(roots)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_document(roots), encoding="utf-8", newline="\n")
    return {"output": str(output_path), **stats}


def main(argv=None):
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument("--output", type=Path, default=project_root / "reports" / "all_primary_issue_fingerprint_review_v01" / "全部问题树_一级二级三级关系_v0.1.html")
    args = parser.parse_args(argv)
    print(json.dumps(export_html(args.project_root, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
