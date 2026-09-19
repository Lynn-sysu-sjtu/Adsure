# 金标准标注手册 v0.1（讨论稿）

每条真实广告对应 `cases/<case_id>.yaml`。标注前通读全文。**拿不准的条目标 `uncertain: true` 并写理由，不要凭感觉定性。**

## 1. 视频级字段

- `case_id`：golden_####（从 0001 起顺序编号；归档后不复用）
- `video.sha256`：文件 SHA-256（评估脚本以此核身，防止版本串了）
- `video.path`：仓库内相对路径；包外素材统一放 `datasets/golden/videos/`（gitignore）
- `video.duration_seconds`：保留一位小数
- `video.source`：
  - `type=penalty_reverse_lookup`（市监处罚公示反查）必须填 `url`（处罚公告页）与 `penalty_case_id`
- `industry`：health_food / cosmetics / game / general
- `platform`：douyin / xiaohongshu / wechat / tv / other
- `background`：运营提交时填写的补充背景（已取得 XX 认证等），**按实际提交状态填，不按实际是否真实**——系统只能看到提交的背景
- `risk_level_overall`：你对整条片的风险判断（high/medium/low/clean），用于和系统输出的整体等级对比

## 2. 文本类标注（channel=asr 或 ocr）

每条 annotation 记一次「不该出现的表达」或「必须出现但有问题的要素」：

- `t_start/t_end`：该表述**实际出现**的时间区间。字级标注以该词第一个字到最后一个字为准。
- `text`：原文转写，按实际听到/看到的写，不要自行修正错别字。
- `bbox`：channel=ocr 时必填，归一化坐标 `[x, y, w, h]`（左上为 0,0，宽高 ≤1）；asr 不填。
- `layer`：
  - L1 绝对化用语（国家级/最高级/第一…，注意《绝对化用语执法指南》五类豁免，疑似豁免填 expected=not_applicable 并在 note 引用豁免类别）
  - L2 行业禁用语（疾病治疗宣称、医疗用语等，优先对应真实处罚案例）
  - L3 需资质/需授权（专利、认证、名人背书等，结论取决于材料）
  - L4 必备要素（提示语、风险警示、广告可识别性）
- `expected`：violation / needs_facts / not_applicable（对应系统三态）
- `law_ref`：尽量填到条款项（如 `广告法§18(1)(2)`），非广告法来源写全称
- `penalty_case_id`：该表述从哪个处罚案例反查而来（如有）
- `note`：判定理由，尤其要写清为什么不是豁免

## 3. 必备要素标注（mandatory_checks）

每个适用的必备要素（见 `backend/app/rules/lexicon/L4_mandatory.yaml` 的 id）填一段：

- `requirement_id`、`present: true/false`
- 若 present：填实际 span（`spans`：t_start/t_end/bbox/text）、你实测的三个显著性观察：
  - `observed_font_scale`：文字高/画面高（评估时与截图核对）
  - `observed_edge_margin`：文字外缘到最近画面边缘的最小距离比
  - 是否闪烁、是否与背景低对比，写入 note
- `expected=violation` 表示「应触发缺失/显著性复核」；present=true 且确实显著填 not_applicable
- 法律上「显著」无统一量化标准：标注的是**你认为监管实践中会不会被点名**，note 必须说明依据（如「字高约画面 1.8%、仅出现 0.4s、贴右下角」）

## 4. IP 标注（ip_ground_truth）

对**每个**出现的知名 IP 形象/品牌 logo/名人肖像记一条，同样标记无 IP 的片段用于计算误报：

- `ip_id`：高危库 id（法务清单发布前用提议 slug，如 `disney_mickey`，并在 note 写明判定特征）
- `t_start/t_end`、`bbox`
- `kinda`：character / logo / celebrity / artwork / font
- `authorization_status_known`：标注时是否确知有授权（多数填 false——不知道 ≠ 侵权）
- 普通卡通形象、通用元素**也**记一条 kind=character 并 `is_protected_ip=false`，这是 IP 误报率的负样本
- 注意三句话边界：① 出现受保护形象 ≠ 侵权；② 系统输出应是「需核验授权材料」；③ 只标视觉事实，标注意见不写侵权结论

## 5. 双标与分歧

- 双方独立完成后，A 的文件末尾 `label_status` 写 `dual_annotated`；核对后由裁决人写 `adjudicated`
- 每个 annotation 有 `source` 标记（a/b/both）与 `resolved_by`
- 达不成一致的条目：`resolved=false`，双方答案与理由都保留，**禁止删除少数意见**
