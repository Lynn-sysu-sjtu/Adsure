let currentRecord = null;
let allRecords = [];

document.addEventListener("DOMContentLoaded", () => {
    loadRecords();
    setupTabs();
});

// Tab切换
function setupTabs() {
    document.querySelectorAll(".sidebar-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".sidebar-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            const type = tab.dataset.tab;
            if (type === "pending") {
                renderSidebar(allRecords.filter(r => r["审核状态"] === "待人工复核"));
            } else {
                renderSidebar(allRecords.filter(r => r["审核状态"] !== "待人工复核"));
            }
        });
    });
}

// 加载待复核记录
async function loadRecords() {
    const res = await fetch("/api/records");
    allRecords = await res.json();
    const pending = allRecords.filter(r => r["审核状态"] === "待人工复核");
    document.getElementById("pending-count").textContent = pending.length;
    renderSidebar(pending);
}

// 渲染左侧列表
function renderSidebar(records) {
    const list = document.getElementById("record-list");
    list.innerHTML = "";

    if (records.length === 0) {
        list.innerHTML = '<div style="padding:24px 16px;color:var(--text-muted);text-align:center;">暂无记录</div>';
        return;
    }

    records.forEach(record => {
        const item = document.createElement("div");
        item.className = "record-item" + (currentRecord && currentRecord.id === record.id ? " active" : "");
        item.dataset.id = record.id;

        const riskClass = record["风险等级"] === "高风险" ? "high" : record["风险等级"] === "中风险" ? "medium" : "low";
        const preview = record["物料内容"].substring(0, 50) + (record["物料内容"].length > 50 ? "..." : "");

        item.innerHTML = `
            <div class="record-item-header">
                <span class="risk-badge ${riskClass}"><span class="risk-dot"></span>${record["风险等级"]}</span>
                <span style="font-size:12px;color:var(--text-muted);">${record["行业领域"]}</span>
            </div>
            <div class="content-preview">${preview}</div>
            <div class="meta">
                <span>${record["提交人"]}</span>
                <span>${record["提交时间"].split(" ")[1] || record["提交时间"]}</span>
            </div>
        `;

        item.addEventListener("click", () => {
            document.querySelectorAll(".record-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            showDetail(record);
        });

        list.appendChild(item);
    });
}

// 显示右侧详情
function showDetail(record) {
    currentRecord = record;
    const detail = document.getElementById("detail-area");

    const violationTags = (record["违规类型"] || [])
        .map(v => `<span class="violation-tag">${v}</span>`)
        .join("");

    const riskClass = record["风险等级"] === "高风险" ? "high" : record["风险等级"] === "中风险" ? "medium" : "low";

    detail.innerHTML = `
        <!-- 物料内容卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">📄</span>物料内容</div>
            <div class="content-full">${record["物料内容"]}</div>
        </div>

        <!-- AI审核意见卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">🤖</span>AI审核意见</div>
            <div class="ai-opinion-box">${record["AI审核意见"]}</div>
        </div>

        <!-- 风险信息卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">⚠️</span>风险信息</div>
            <div class="risk-tags" style="margin-bottom:12px;">
                <span class="risk-badge ${riskClass}"><span class="risk-dot"></span>${record["风险等级"]}</span>
                ${violationTags}
            </div>
            ${record["AI抽取-高风险词命中"] && record["AI抽取-高风险词命中"] !== "无" ? `
            <div class="highlight-box" style="margin-bottom:10px;">
                <strong>高风险词命中：</strong>${record["AI抽取-高风险词命中"]}
            </div>` : ""}
            ${record["AI抽取-备案核查结果"] ? `
            <div class="highlight-box">
                <strong>备案核查：</strong>${record["AI抽取-备案核查结果"]}
            </div>` : ""}
        </div>

        <!-- 法务操作区 -->
        <div class="review-card">
            <div class="review-card-title">✍️ 法务裁决</div>

            <div class="form-group">
                <label class="form-label">AI意见评价<span class="required">*</span></label>
                <select class="form-select" id="ai-opinion">
                    <option value="">请选择对AI审核意见的评价...</option>
                    <option value="同意无补充">同意无补充 — AI判断完全正确</option>
                    <option value="同意有补充">同意有补充 — AI方向正确但需补充</option>
                    <option value="驳回">驳回 — AI判断有误</option>
                </select>
            </div>

            <div class="form-group">
                <label class="form-label">物料裁决<span class="required">*</span></label>
                <select class="form-select" id="verdict">
                    <option value="">请选择物料最终裁决...</option>
                    <option value="通过">通过 — 物料合规可发布</option>
                    <option value="不通过">不通过 — 需修改后重新提交</option>
                </select>
            </div>

            <!-- 驳回+通过 提示 -->
            <div class="tip-banner hidden" id="reject-pass-tip">
                💡 你选择了驳回AI意见但通过物料，系统会将此反馈作为 override 类型沉淀到规则库，帮助AI学习正确判断。
            </div>

            <!-- 异议字段 -->
            <div class="form-group hidden" id="objection-group">
                <label class="form-label">异议字段<span class="required">*</span><span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（针对AI哪些输出有异议）</span></label>
                <div class="checkbox-group" id="objection-checkboxes">
                    <label class="checkbox-item"><input type="checkbox" value="风险等级">风险等级</label>
                    <label class="checkbox-item"><input type="checkbox" value="违规位置">违规位置</label>
                    <label class="checkbox-item"><input type="checkbox" value="违规类型">违规类型</label>
                    <label class="checkbox-item"><input type="checkbox" value="法条依据">法条依据</label>
                    <label class="checkbox-item"><input type="checkbox" value="修改建议">修改建议</label>
                    <label class="checkbox-item"><input type="checkbox" value="风险说明">风险说明</label>
                    <label class="checkbox-item"><input type="checkbox" value="整体推理逻辑">整体推理逻辑</label>
                </div>
            </div>

            <!-- 补充意见（同意有补充时） -->
            <div class="form-group hidden" id="supplement-group">
                <label class="form-label">补充意见</label>
                <textarea class="form-textarea" id="supplement-reason" placeholder="请简要说明您的补充意见..."></textarea>
            </div>

            <!-- 驳回理由 -->
            <div class="form-group hidden" id="reject-reason-group">
                <label class="form-label">驳回理由<span class="required">*</span></label>
                <textarea class="form-textarea" id="reject-reason" placeholder="请说明为什么AI的判定有误..."></textarea>
            </div>

            <!-- 正确判定 -->
            <div class="form-group hidden" id="correct-judgment-group">
                <label class="form-label">正确判定<span class="required">*</span></label>
                <textarea class="form-textarea" id="correct-judgment" placeholder="您认为正确的判定应该是什么..."></textarea>
            </div>

            <!-- 最终修改意见（不通过时） -->
            <div class="form-group hidden" id="final-suggestion-group">
                <label class="form-label">最终修改意见<span class="required">*</span><span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（将发送给运营）</span></label>
                <textarea class="form-textarea" id="final-suggestion" placeholder="请告诉运营具体需要修改哪些内容..."></textarea>
            </div>

            <!-- 法务批注 -->
            <div class="form-group">
                <label class="form-label">法务批注<span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（仅内部可见，不参与规则沉淀）</span></label>
                <textarea class="form-textarea" id="note" placeholder="可选，内部备忘..." style="min-height:60px;"></textarea>
            </div>

            <button class="btn-submit" id="btn-submit" onclick="submitReview()">提交裁决</button>
        </div>
    `;

    setupFormLogic();
}

// 条件显隐 + checkbox美化
function setupFormLogic() {
    const opinionSelect = document.getElementById("ai-opinion");
    const verdictSelect = document.getElementById("verdict");
    if (!opinionSelect || !verdictSelect) return;

    opinionSelect.addEventListener("change", updateFormVisibility);
    verdictSelect.addEventListener("change", updateFormVisibility);

    // checkbox点击样式
    document.querySelectorAll(".checkbox-item").forEach(item => {
        const cb = item.querySelector("input[type=checkbox]");
        if (!cb) return;
        item.addEventListener("click", (e) => {
            if (e.target === cb) return; // 让checkbox自己处理
            cb.checked = !cb.checked;
            item.classList.toggle("checked", cb.checked);
        });
        cb.addEventListener("change", () => {
            item.classList.toggle("checked", cb.checked);
        });
    });
}

/**
 * 6种组合的条件显隐逻辑：
 *
 * | AI意见评价  | 物料裁决 | 显示字段                            | 反馈类型    |
 * |------------|---------|-------------------------------------|------------|
 * | 同意无补充  | 通过    | （无额外字段）                       | 无         |
 * | 同意无补充  | 不通过  | 最终修改意见                         | 无         |
 * | 同意有补充  | 通过    | 异议字段(非必填) + 补充意见          | refine     |
 * | 同意有补充  | 不通过  | 异议字段(非必填) + 补充意见 + 最终修改意见 | refine |
 * | 驳回       | 通过    | 异议字段(必选) + 驳回理由 + 正确判定 | override   |
 * | 驳回       | 不通过  | 异议字段(必选) + 驳回理由 + 正确判定 + 最终修改意见 | override |
 */
function updateFormVisibility() {
    const opinion = document.getElementById("ai-opinion")?.value;
    const verdict = document.getElementById("verdict")?.value;

    const groups = {
        objection: document.getElementById("objection-group"),
        supplement: document.getElementById("supplement-group"),
        rejectReason: document.getElementById("reject-reason-group"),
        correctJudgment: document.getElementById("correct-judgment-group"),
        finalSuggestion: document.getElementById("final-suggestion-group"),
        rejectPassTip: document.getElementById("reject-pass-tip"),
    };

    if (!groups.objection) return;

    // 全部隐藏
    Object.values(groups).forEach(el => el.classList.add("hidden"));

    // 同意有补充
    if (opinion === "同意有补充") {
        groups.objection.classList.remove("hidden");
        groups.supplement.classList.remove("hidden");
    }

    // 驳回
    if (opinion === "驳回") {
        groups.objection.classList.remove("hidden");
        groups.rejectReason.classList.remove("hidden");
        groups.correctJudgment.classList.remove("hidden");
    }

    // 驳回 + 通过 → 特殊提示
    if (opinion === "驳回" && verdict === "通过") {
        groups.rejectPassTip.classList.remove("hidden");
    }

    // 不通过 → 显示最终修改意见
    if (verdict === "不通过") {
        groups.finalSuggestion.classList.remove("hidden");
    }
}

// 提交裁决
async function submitReview() {
    if (!currentRecord) return;

    const opinion = document.getElementById("ai-opinion").value;
    const verdict = document.getElementById("verdict").value;

    // 基础校验
    if (!opinion) { alert("请选择AI意见评价"); return; }
    if (!verdict) { alert("请选择物料裁决"); return; }

    // 驳回校验
    if (opinion === "驳回") {
        const checked = document.querySelectorAll("#objection-checkboxes input:checked");
        if (checked.length === 0) {
            alert("驳回时请至少选择一项异议字段，以便系统精准学习");
            return;
        }
        const reason = document.getElementById("reject-reason").value.trim();
        if (!reason) { alert("请填写驳回理由"); return; }
        const judgment = document.getElementById("correct-judgment").value.trim();
        if (!judgment) { alert("请填写正确判定"); return; }
    }

    // 不通过时校验修改意见
    if (verdict === "不通过") {
        const suggestion = document.getElementById("final-suggestion").value.trim();
        if (!suggestion) { alert("物料不通过时请填写最终修改意见"); return; }
    }

    // 收集异议字段
    const objectionFields = [];
    document.querySelectorAll("#objection-checkboxes input:checked").forEach(cb => {
        objectionFields.push(cb.value);
    });

    const data = {
        ai_opinion: opinion,
        verdict: verdict,
        objection_fields: objectionFields,
        supplement_reason: document.getElementById("supplement-reason")?.value || "",
        reject_reason: document.getElementById("reject-reason")?.value || "",
        correct_judgment: document.getElementById("correct-judgment")?.value || "",
        final_suggestion: document.getElementById("final-suggestion")?.value || "",
        note: document.getElementById("note")?.value || "",
    };

    const btn = document.getElementById("btn-submit");
    btn.disabled = true;
    btn.textContent = "提交中...";

    try {
        const res = await fetch(`/api/records/${currentRecord.id}/review`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });

        const result = await res.json();

        if (result.success) {
            showSuccess(verdict);
            loadRecords();
        } else {
            alert("提交失败：" + result.message);
            btn.disabled = false;
            btn.textContent = "提交裁决";
        }
    } catch (e) {
        alert("网络错误，请重试");
        btn.disabled = false;
        btn.textContent = "提交裁决";
    }
}

// 提交成功页面
function showSuccess(verdict) {
    const detail = document.getElementById("detail-area");
    detail.innerHTML = `
        <div class="success-view">
            <div class="success-icon">✓</div>
            <div class="success-title">裁决已提交</div>
            <div class="success-desc">
                ${verdict === "通过" ? "已标记物料为通过，运营将收到通知" : "已标记物料需修改，修改意见已发送给运营"}
            </div>
        </div>
    `;
    currentRecord = null;
}

// 刷新
function refreshRecords() {
    loadRecords();
    document.getElementById("detail-area").innerHTML = `
        <div class="detail-empty">
            <div class="detail-empty-icon">📋</div>
            <p>选择左侧物料查看详情</p>
        </div>
    `;
    currentRecord = null;
}
