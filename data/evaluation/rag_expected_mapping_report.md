# 30 条违规广告「预期召回案例」映射说明

> 生成：2026-09-15。来源：美妆/保健食品/游戏 三套评测集（各 10 条）。
> 预期字段：`expected_rag_case_ids`（库内 case_id 列表，通常 3 条）、`expected_rag_case_titles`、`expected_rag_note`（编排依据/低覆盖说明）。

## 编排原则
1. 同行业优先（美妆→beauty/绝对化；保健食品→health/food_medical/health_food_overclaim；游戏→game/mihoyo）。
2. 同风险维度优先（医疗用语、绝对化用语、疾病治疗功效、虚假宣传、概率公示、功效保证、数据引证）。
3. 正常/对照样例 → `expected_rag_case_ids=[]`（不应召回处罚案例）。
4. 库内无对应风险维度的（未成年人、版号/防沉迷、平台规则类）→ 空 + 注明「低覆盖，需补充案例」。

## 覆盖情况（30 条）
- 有预期 3 案：23 条
- 空（正常样例）：4 条（BEAUTY-AD-009/010、HF-AD-009/010）
- 空（库内低覆盖/非法律违规）：3 条（EVAL-GAME-004 未成年人、007 版号/防沉迷、008 仅平台规则）

## ⚠️ 重要：当前 RAG 实际召回与预期不一致
- 用默认检索（production，lexical 或 semantic，`min_query_coverage=0.25` / `min_relative_score=0.25` / `min_semantic_score=0.62`）对这 30 条新广告文案实测，**绝大多数返回空或 1 条**（词面/语义与库内既有案例重叠不足被阈值过滤）。
- 因此本文件的「预期召回」是**按风险维度人工编排的 gold oracle**，不是当前系统输出。
- 要让线上行为对齐预期，团队需二选一或同时做：
  1. 调优检索：放宽 `CASE_ENGINE_MIN_SEMANTIC_SCORE`（0.62 → 0.5 左右）或默认启用 hybrid；
  2. 补库：为未成年人保护、版号/防沉迷、平台规则类、游戏收益/提现等新增案例。
- 校验脚本建议：检索结果与 `expected_rag_case_ids` 做 top3 命中比对（命中即算过），空预期条目不参与比对。

## 输出文件（data/evaluation/）
- beauty_ad_copy_test_set_20260908_expected_rag.json
- health_food_ad_copy_test_set_20260906_expected_rag.json
- game_ad_copy_eval_set_v1_expected_rag.json
- 游戏广告合规评测案例集_v1_expected.xlsx（原表 + “含预期召回”工作表）
