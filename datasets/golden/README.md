# 金标准集（datasets/golden）

对应实施方案 v2 第十四节「需要你推动的第①件事」与第十一节验收指标。
**这是所有效果指标（ASR 时间戳误差、OCR 花字召回、违规词召回、误报率、L4、IP 回归/误报）的唯一裁判。**

## 1. 规模与构成（方案硬要求）

| 维度 | 要求 |
|---|---|
| 总数 | 40–60 条真实广告视频 |
| IP 子集 | 至少 15 条含知名 IP 形象/logo |
| 违规文案类 | 优先从市监局行政处罚公示中**反查被罚广告同款/同款话术** |
| 标注 | 至少 2 人独立标注后逐条核对；分歧样本单独留档 |
| 负样本 | 必须包含「易误报但合规」的素材（白名单语境、法定保健功能、普通卡通形象≠米奇等），否则误报率无从算起 |

> `data/evaluation/video_claim_regression.json`（33 条文案）自述 `engineering_regression_not_legal_gold`，
> 只作工程回归，不能替代本集；`data/video_mvp/jobs/` 是工程跑批目录，不是金标准。

## 2. 目录规范

```
datasets/golden/
├── README.md                 # 本文件：总体规范
├── annotation_manual.md      # 字段级标注手册（判定边界与示例）
├── cases/                    # 每条视频一份 <case_id>.yaml，文件名即 case_id
│   └── golden_0001.yaml
├── inventory/
│   └── candidate_inventory.csv   # 候选素材清点（脚本生成，勿手改）
├── examples/
│   └── golden_example.yaml   # 标注示例（虚构素材，用于对齐口径）
└── scripts/
    ├── inventory_existing.py # 清点仓库现有视频（根目录 + video_mvp/jobs）
    └── validate_golden.py    # 校验 cases/*.yaml：结构、时间区间、双人标注、分歧处理
```

视频本体**不入 git**（太大且可能有版权）。cases YAML 里用 sha256 + 本地路径引用，
在 `.gitignore` 加 `datasets/golden/videos/`。团队通过内部渠道分发视频包，以 sha256 核身。

## 3. 工作流

1. **初筛**（机器辅助）：跑 `python datasets/golden/scripts/inventory_existing.py` 生成候选清单，人工挑选并补录外部素材。
2. **预标注草稿**（可选减负）：跑 `python backend/scripts/preannotate_golden.py 视频.mp4 --case-id golden_0001 --industry health_food --annotator 张三 --out datasets/golden/cases/golden_0001.yaml`——引擎自动填好时间区间/bbox/layer/expected，人工只需核对修正 + 补漏报。⚠️ 草稿不改变双标要求：标注人仍须独立判断，不能抄机器答案。
3. **独立双标**：两名标注人各自填一份 YAML（`annotator_a` / `annotator_b`），**不串口径**。
4. **核对**：跑 `python datasets/golden/scripts/validate_golden.py` 做机械校验后，两人逐条对差异。
5. **分歧留档**：意见不一致的条目保留双方答案、理由与裁决人结论，写入 `disagreements`，不许只留结论——分歧分布本身是词库/提示词校准的输入。
6. **状态流转**：`draft → dual_annotated → adjudicated`；只有 `adjudicated` 的条目可进指标计算。
7. **指标计算**（C2 任务）：对每条 adjudicated 案例跑完整链路，按层统计 §11 各指标。

## 4. 与方案指标的对应

| 标注字段 | 支撑的指标 |
|---|---|
| `annotations[].t_start/t_end` + `text`（asr/ocr） | ASR 字级时间戳误差 ≤0.5s、OCR 花字召回 ≥85% |
| annotations 中 layer=L1/L2 且 expected=violation | 粗筛召回 ≥95%、最终误报率 ≤15% |
| `mandatory_checks[]`（present + 三个显著性维度） | L4 缺失/显著性检出 ≥90% |
| `ip_ground_truth[]`（含「无 IP」负样本标记） | IP 召回 ≥90%、误报 ≤10%、时间区间误差 ≤1s |
| 全链路 wall time（评估脚本记录） | 端到端 ≤90s / OCR ≤20 次 / VLM ≤4 次 |
