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
                renderSidebar(allRecords.filter(r => r["审核状态"] === "待法务复核"), "pending");
            } else if (type === "done") {
                renderSidebar(allRecords.filter(r => r["审核状态"] === "已通过" || r["审核状态"] === "需修改"), "done");
            } else if (type === "rules") {
                renderSidebar([], "pending");
                loadRulesView();
            }
        });
    });
}

// 加载待复核记录
async function loadRecords() {
    const res = await fetch("/api/records");
    allRecords = await res.json();
    const pending = allRecords.filter(r => r["审核状态"] === "待法务复核");
    document.getElementById("pending-count").textContent = pending.length;
    renderSidebar(pending);
}

// 渲染左侧列表
// mode: "pending"（待处理，显示运营提交人）| "done"（已处理，显示法务审核人）
function renderSidebar(records, mode = "pending") {
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

        // 待处理显示运营提交人，已处理显示法务审核人
        const personLabel = mode === "done" ? "法务" : "提交";
        const personName  = mode === "done"
            ? (record["法务审核人"] || "—")
            : (record["提交人"] || "—");

        item.innerHTML = `
            <div class="record-item-header">
                <span class="risk-badge ${riskClass}"><span class="risk-dot"></span>${record["风险等级"]}</span>
                <span style="font-size:12px;color:var(--text-muted);">${record["行业领域"]}</span>
            </div>
            <div class="content-preview">${preview}</div>
            <div class="meta">
                <span style="color:var(--text-muted);">${personLabel}：</span><span>${personName}</span>
                <span>${record["提交时间"] || "—"}</span>
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

// 行业专属信息卡片
function buildIndustryCard(record) {
    const industry = record["行业领域"];
    if (!industry) return "";

    function val(v) {
        if (!v || (Array.isArray(v) && v.length === 0)) return "—";
        return Array.isArray(v) ? v.join("、") : v;
    }
    function row(label, value) {
        return `<tr>
            <td style="color:var(--text-muted);width:100px;padding:4px 0;vertical-align:top;white-space:nowrap;">${label}</td>
            <td style="padding:4px 0;">${val(value)}</td>
        </tr>`;
    }

    let rows = "";
    let icon = "🏷️";

    if (industry === "美妆") {
        icon = "💄";
        rows = [
            row("物料类型",     record["美妆_物料类型"]),
            row("产品品类",     record["美妆_产品品类"]),
            row("涉及场景",     record["美妆_物料涉及场景"]),
            row("核心宣称功效", record["美妆_核心宣称功效"]),
            row("产品备案名称", record["美妆_产品备案名称"]),
            row("补充背景资料", record["补充背景资料"]),
        ].join("");
    } else if (industry === "游戏") {
        icon = "🎮";
        rows = [
            row("物料类型",     record["游戏_物料类型"]),
            row("产品品类",     record["游戏_产品品类"]),
            row("游戏名称",     record["游戏_游戏名称"]),
            row("IP名称",       record["游戏_IP名称"]),
            row("涉及场景",     record["游戏_物料涉及场景"]),
            row("补充背景资料", record["补充背景资料"]),
        ].join("");
    } else if (industry === "保健食品") {
        icon = "💊";
        rows = [
            row("物料类型",     record["保健食品_物料类型"]),
            row("产品品类",     record["保健食品_产品品类"]),
            row("涉及场景",     record["保健食品_物料涉及场景"]),
            row("核心宣称功效", record["保健食品_核心宣称功效"]),
            row("产品备案名称", record["保健食品_产品备案名称"]),
            row("批准文号",     record["保健食品_批准文号"]),
            row("补充背景资料", record["补充背景资料"]),
        ].join("");
    } else {
        // 其他行业只显示补充背景资料
        if (!record["补充背景资料"]) return "";
        rows = row("补充背景资料", record["补充背景资料"]);
    }

    return `
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">${icon}</span>${industry}专属信息</div>
            <table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.8;">
                ${rows}
            </table>
        </div>`;
}

// 显示右侧详情
function showDetail(record) {
    currentRecord = record;
    const detail = document.getElementById("detail-area");

    const violationTags = (record["违规类型"] || [])
        .map(v => `<span class="violation-tag">${v}</span>`)
        .join("");

    const riskClass = record["风险等级"] === "高风险" ? "high" : record["风险等级"] === "中风险" ? "medium" : "low";

    const isReviewed = record["审核状态"] === "已通过" || record["审核状态"] === "需修改";

    // 紧急程度标签
    const urgencyHtml = record["紧急程度"] && record["紧急程度"] !== "普通"
        ? `<span style="background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;">⚡ ${record["紧急程度"]}</span>`
        : "";

    detail.innerHTML = `
        <!-- 基本信息卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">📋</span>基本信息</div>
            <table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.8;table-layout:fixed;">
                <colgroup>
                    <col style="width:80px;"><col><col style="width:80px;"><col>
                </colgroup>
                <tr>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">物料编号</td>
                    <td style="padding:3px 0;">${record["物料编号"] || "—"}</td>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">行业领域</td>
                    <td style="padding:3px 0;">${record["行业领域"] || "—"}</td>
                </tr>
                <tr>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">投放平台</td>
                    <td style="padding:3px 0;">${record["投放平台"] || "—"}</td>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">紧急程度</td>
                    <td style="padding:3px 0;">${urgencyHtml || record["紧急程度"] || "普通"}</td>
                </tr>
                <tr>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">运营提交人</td>
                    <td style="padding:3px 0;">${record["提交人"] || "—"}</td>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">提交时间</td>
                    <td style="padding:3px 0;">${record["提交时间"] || "—"}</td>
                </tr>
                <tr>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">法务审核人</td>
                    <td style="padding:3px 0;">${record["法务审核人"] || "—"}</td>
                    <td style="color:var(--text-muted);padding:3px 0;vertical-align:top;">法务复核时间</td>
                    <td style="padding:3px 0;">${record["法务复核时间"] || "—"}</td>
                </tr>
            </table>
        </div>

        <!-- 物料内容卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">📄</span>物料内容</div>
            ${(record["物料附件"] || []).length > 0 ? `
            <div style="margin-bottom:${record["物料内容"] ? "10px" : "0"};">
                ${(record["物料附件"] || []).map(a => `
                <img src="/api/attachment/${a.file_token}"
                     alt="${a.name}"
                     loading="lazy"
                     style="max-width:100%;max-height:260px;object-fit:contain;border-radius:6px;display:block;margin-bottom:6px;"
                     onerror="this.style.display='none'">
                `).join("")}
            </div>` : ""}
            ${record["物料内容"] ? `<div class="content-full">${record["物料内容"]}</div>` : ""}
        </div>

        ${buildIndustryCard(record)}

        <!-- AI审核意见卡片 -->
        <div class="detail-card">
            <div class="detail-card-title"><span class="icon">🤖</span>AI审核意见</div>
            <div class="ai-opinion-box">${record["AI审核意见"]}</div>
            ${record["关键实体抽取"] ? `
            <div style="margin-top:10px;">
                <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px;">关键实体抽取</div>
                <div class="highlight-box">${record["关键实体抽取"]}</div>
            </div>` : ""}
            ${record["平台规则预检"] ? `
            <div style="margin-top:10px;">
                <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px;">平台规则预检</div>
                <div class="highlight-box">${record["平台规则预检"]}</div>
            </div>` : ""}
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

        <!-- 相关案例卡片（异步加载） -->
        <div class="detail-card" id="cases-card">
            <div class="detail-card-title"><span class="icon">📚</span>相关案例参考</div>
            <div id="cases-content" style="color:var(--text-muted);font-size:13px;">加载中…</div>
        </div>

        <!-- 法务操作区 -->
        <div class="review-card">
            <div class="review-card-title">✍️ 法务裁决${isReviewed ? ' <span style="font-size:13px;font-weight:normal;color:var(--text-muted);">（已裁决）</span>' : ''}</div>
            ${isReviewed ? renderReviewHistory(record) : renderReviewForm()}
        </div>
    `;

    if (isReviewed) {
        setupReEditLogic();
    } else {
        setupFormLogic();
    }

    // 异步加载相关案例
    loadCases(record.id);
}

// 已裁决：渲染历史记录视图
function renderReviewHistory(record) {
    const verdictColor = record["物料裁决"] === "通过" ? "color:#27a745;font-weight:600;" : "color:#e6720a;font-weight:600;";
    const rows = [
        ["AI意见评价", record["AI意见评价"]],
        ["物料裁决", `<span style="${verdictColor}">${record["物料裁决"]}</span>`],
        ["反馈类型", record["反馈类型"]],
        ["驳回次数", record["驳回次数"] || 0],
    ].filter(([, v]) => v !== "" && v !== null && v !== undefined);

    const extras = [
        ["异议字段", (record["异议字段"] || []).join("、")],
        ["补充或驳回理由", record["法务补充或驳回理由"]],
        ["驳回正确判定", record["驳回正确判定"]],
        ["最终修改意见", record["最终修改意见"]],
        ["法务批注", record["法务批注"]],
    ].filter(([, v]) => v);

    const allRows = [...rows, ...extras];
    const tableRows = allRows.map(([k, v]) =>
        `<tr><td style="color:var(--text-muted);width:110px;padding:6px 8px;vertical-align:top;">${k}</td><td style="padding:6px 8px;">${v}</td></tr>`
    ).join("");

    return `
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:16px;">
            ${tableRows}
        </table>
        <button class="btn-submit" style="background:var(--bg-hover);color:var(--text-primary);border:1px solid var(--border);"
            onclick="switchToReEditMode()">修改裁决并重新通知运营</button>
    `;
}

// 渲染空白裁决表单（抽取为函数，供初次裁决和重新裁决共用）
function renderReviewForm(prefill = null) {
    const p = prefill || {};
    const opinionVal  = p["AI意见评价"] || "";
    const verdictVal  = p["物料裁决"]   || "";
    const objList     = p["异议字段"]   || [];

    function sel(opt)  { return opinionVal === opt || verdictVal === opt ? 'selected' : ''; }
    function selO(opt) { return opinionVal === opt ? 'selected' : ''; }
    function selV(opt) { return verdictVal === opt ? 'selected' : ''; }
    function chk(val)  { return objList.includes(val) ? 'checked' : ''; }
    function pre(key, fallback = '') {
        const v = p[key] || fallback;
        return v.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    return `
            <div class="form-group">
                <label class="form-label">法务审核人<span class="required">*</span></label>
                <input type="text" class="form-select" id="reviewer-name" placeholder="请输入您的姓名（用于记录法务审核人）" value="${(p["法务审核人"] || "").replace(/</g,'&lt;').replace(/>/g,'&gt;')}" style="height:38px;">
            </div>

            <div class="form-group">
                <label class="form-label">AI意见评价<span class="required">*</span></label>
                <select class="form-select" id="ai-opinion">
                    <option value="">请选择对AI审核意见的评价...</option>
                    <option value="同意无补充" ${selO("同意无补充")}>同意无补充 — AI判断完全正确</option>
                    <option value="同意有补充" ${selO("同意有补充")}>同意有补充 — AI方向正确但需补充</option>
                    <option value="驳回" ${selO("驳回")}>驳回 — AI判断有误</option>
                </select>
            </div>

            <div class="form-group">
                <label class="form-label">物料裁决<span class="required">*</span></label>
                <select class="form-select" id="verdict">
                    <option value="">请选择物料最终裁决...</option>
                    <option value="通过" ${selV("通过")}>通过 — 物料合规可发布</option>
                    <option value="不通过" ${selV("不通过")}>不通过 — 需修改后重新提交</option>
                </select>
            </div>

            <div class="tip-banner hidden" id="combo-tip"></div>

            <div class="form-group hidden" id="objection-group">
                <label class="form-label">异议字段<span class="required">*</span><span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（针对AI哪些输出有异议）</span></label>
                <div class="checkbox-group" id="objection-checkboxes">
                    <label class="checkbox-item ${chk('风险等级') ? 'checked' : ''}"><input type="checkbox" value="风险等级" ${chk('风险等级')}>风险等级</label>
                    <label class="checkbox-item ${chk('违规位置') ? 'checked' : ''}"><input type="checkbox" value="违规位置" ${chk('违规位置')}>违规位置</label>
                    <label class="checkbox-item ${chk('违规类型') ? 'checked' : ''}"><input type="checkbox" value="违规类型" ${chk('违规类型')}>违规类型</label>
                    <label class="checkbox-item ${chk('法条依据') ? 'checked' : ''}"><input type="checkbox" value="法条依据" ${chk('法条依据')}>法条依据</label>
                    <label class="checkbox-item ${chk('修改建议') ? 'checked' : ''}"><input type="checkbox" value="修改建议" ${chk('修改建议')}>修改建议</label>
                    <label class="checkbox-item ${chk('风险说明') ? 'checked' : ''}"><input type="checkbox" value="风险说明" ${chk('风险说明')}>风险说明</label>
                    <label class="checkbox-item ${chk('整体推理逻辑') ? 'checked' : ''}"><input type="checkbox" value="整体推理逻辑" ${chk('整体推理逻辑')}>整体推理逻辑</label>
                </div>
            </div>

            <div class="form-group hidden" id="supplement-group">
                <label class="form-label">补充意见<span class="required">*</span><span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（将发送给运营，并参与规则沉淀）</span></label>
                <textarea class="form-textarea" id="supplement-reason" placeholder="请简要说明您的补充意见...">${pre("法务补充或驳回理由")}</textarea>
            </div>

            <div class="form-group hidden" id="reject-reason-group">
                <label class="form-label">驳回理由<span class="required">*</span></label>
                <textarea class="form-textarea" id="reject-reason" placeholder="请说明为什么AI的判定有误...">${pre("法务补充或驳回理由")}</textarea>
                <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">💡 建议格式：【内容类型】不违反【法规名称】，因为【具体理由】</div>
            </div>

            <div class="form-group hidden" id="correct-judgment-group">
                <label class="form-label">正确判定<span class="required">*</span></label>
                <textarea class="form-textarea" id="correct-judgment" placeholder="您认为正确的判定应该是什么...">${pre("驳回正确判定")}</textarea>
            </div>

            <div class="form-group hidden" id="final-suggestion-group">
                <label class="form-label">最终修改意见<span class="required">*</span><span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（将发送给运营）</span></label>
                <textarea class="form-textarea" id="final-suggestion" placeholder="请告诉运营具体需要修改哪些内容...">${pre("最终修改意见")}</textarea>
            </div>

            <div class="form-group">
                <label class="form-label">法务批注<span style="font-weight:normal;color:var(--text-muted);margin-left:4px;font-size:12px;">（仅内部可见，不参与规则沉淀）</span></label>
                <textarea class="form-textarea" id="note" placeholder="可选，内部备忘..." style="min-height:60px;">${pre("法务批注")}</textarea>
            </div>

            <button class="btn-submit" id="btn-submit" onclick="submitReview()">提交裁决</button>
    `;
}

// 已裁决记录点「修改裁决」→ 切换为预填充表单，带返回按钮和条件通知
function switchToReEditMode() {
    if (!currentRecord) return;
    const reviewCard = document.querySelector(".review-card");
    if (!reviewCard) return;

    reviewCard.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
            <button onclick="showDetail(currentRecord)"
                style="background:none;border:none;cursor:pointer;font-size:14px;color:var(--text-muted);padding:0;">
                ← 返回
            </button>
            <span class="review-card-title" style="margin:0;">✍️ 修改裁决</span>
        </div>
        <div id="re-edit-form">${renderReviewForm(currentRecord)}</div>
    `;

    setupFormLogic();
    updateFormVisibility();

    // 在提交按钮前插入「是否通知运营」勾选框
    const btn = reviewCard.querySelector("#btn-submit");
    if (btn) {
        const notifyWrap = document.createElement("div");
        notifyWrap.style.cssText = "margin-bottom:12px;display:flex;align-items:center;gap:8px;";
        // 裁决结果或修改意见有变化时默认勾选，否则默认不勾选
        const prevVerdict    = currentRecord["物料裁决"]    || "";
        const prevOpinion    = currentRecord["AI意见评价"]  || "";
        const prevSuggestion = currentRecord["最终修改意见"] || "";
        const defaultChecked = (
            (document.getElementById("verdict")?.value     || "") !== prevVerdict    ||
            (document.getElementById("ai-opinion")?.value  || "") !== prevOpinion    ||
            (document.getElementById("final-suggestion")?.value?.trim() || "") !== prevSuggestion
        );
        notifyWrap.innerHTML = `
            <input type="checkbox" id="notify-operator-cb" ${defaultChecked ? 'checked' : ''}
                style="width:16px;height:16px;cursor:pointer;">
            <label for="notify-operator-cb" style="font-size:14px;cursor:pointer;">
                提交后通知运营
                <span style="color:var(--text-muted);font-size:12px;margin-left:4px;">
                    （裁决结果或修改意见有变化时建议勾选）
                </span>
            </label>
        `;
        btn.parentNode.insertBefore(notifyWrap, btn);

        btn.onclick = function() {
            const needNotify = document.getElementById("notify-operator-cb")?.checked ?? true;
            submitReview(needNotify);
        };
    }
}

// 已裁决记录的重新编辑按钮绑定
function setupReEditLogic() {
    // 按钮已在 renderReviewHistory 里用 onclick 绑定，无需额外操作
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
            if (e.target === cb) return; // 让checkbox原生处理自身点击
            // label内有input时浏览器默认会联动checkbox，需preventDefault阻止双触发
            e.preventDefault();
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
        comboTip: document.getElementById("combo-tip"),
    };

    if (!groups.objection) return;

    // 全部隐藏
    Object.values(groups).forEach(el => el && el.classList.add("hidden"));

    // 6 种组合说明文字
    const tips = {
        "同意无补充_通过":  "💡 AI判断正确，物料合规。此次反馈将作为正样本加强规则库。",
        "同意无补充_不通过":"💡 AI判断方向正确，物料仍需修改。请填写修改意见告知运营。",
        "同意有补充_通过":  "💡 AI方向正确但有遗漏。你的补充意见将参与规则沉淀，帮助AI补全此类分析。",
        "同意有补充_不通过":"💡 AI方向正确但有遗漏，且物料需修改。补充意见将沉淀为规则，修改意见将发送给运营。",
        "驳回_通过":        "💡 AI误判违规，物料实际合规。此次驳回将作为 override 案例沉淀，帮助AI纠正同类误判。",
        "驳回_不通过":      "💡 AI判断类型或程度有误，但物料确实需修改。驳回记录将沉淀，修改意见将发送给运营。",
    };

    if (opinion && verdict) {
        const key = `${opinion}_${verdict}`;
        const tip = tips[key];
        if (tip && groups.comboTip) {
            groups.comboTip.textContent = tip;
            groups.comboTip.classList.remove("hidden");
        }
    }

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

    // 不通过 → 显示最终修改意见
    if (verdict === "不通过") {
        groups.finalSuggestion.classList.remove("hidden");
    }
}

// 提交裁决
async function submitReview(notifyOperator = true) {
    if (!currentRecord) return;

    const opinion = document.getElementById("ai-opinion").value;
    const verdict = document.getElementById("verdict").value;
    const reviewerName = (document.getElementById("reviewer-name")?.value || "").trim();

    // 基础校验
    if (!reviewerName) { alert("请填写法务审核人姓名"); return; }
    if (!opinion) { alert("请选择AI意见评价"); return; }
    if (!verdict) { alert("请选择物料裁决"); return; }

    // 同意有补充校验
    if (opinion === "同意有补充") {
        const supplement = document.getElementById("supplement-reason").value.trim();
        if (!supplement) { alert("请填写补充意见"); return; }
    }

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
        reviewer_name: reviewerName,
        objection_fields: objectionFields,
        supplement_reason: document.getElementById("supplement-reason")?.value || "",
        reject_reason: document.getElementById("reject-reason")?.value || "",
        correct_judgment: document.getElementById("correct-judgment")?.value || "",
        final_suggestion: document.getElementById("final-suggestion")?.value || "",
        note: document.getElementById("note")?.value || "",
        notify_operator: notifyOperator,
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
            showSuccess(verdict, notifyOperator);
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
function showSuccess(verdict, notifyOperator = true) {
    const detail = document.getElementById("detail-area");
    const notifyMsg = notifyOperator
        ? (verdict === "通过" ? "运营将收到通知" : "修改意见已发送给运营")
        : "本次修改仅更新记录，未重新通知运营";
    detail.innerHTML = `
        <div class="success-view">
            <div class="success-icon">✓</div>
            <div class="success-title">裁决已提交</div>
            <div class="success-desc">
                ${verdict === "通过" ? "已标记物料为通过，" : "已标记物料需修改，"}${notifyMsg}
            </div>
        </div>
    `;
    currentRecord = null;
}

// ===== 相关案例 =====

async function loadCases(record_id) {
    const container = document.getElementById("cases-content");
    if (!container) return;

    try {
        const res = await fetch(`/api/records/${record_id}/cases`);
        const data = await res.json();
        const cases = data.cases || [];

        if (cases.length === 0) {
            container.innerHTML = '<span style="color:var(--text-muted);">暂无相关案例</span>';
            return;
        }

        const riskColor = { "高": "var(--danger)", "中": "var(--warning,#e6720a)", "低": "var(--success)" };

        const html = cases.map(c => {
            const legalBasis = Array.isArray(c.legal_basis)
                ? c.legal_basis.join("；")
                : (c.legal_basis || "");
            const riskDims = Array.isArray(c.risk_dimensions) && c.risk_dimensions.length
                ? `<span style="color:var(--text-muted);font-size:12px;">${c.risk_dimensions.join("·")}</span>`
                : "";
            const riskLevelHtml = c.risk_level
                ? `<span style="color:${riskColor[c.risk_level] || '#333'};font-weight:600;">${c.risk_level}风险</span> · `
                : "";
            const scoreHtml = typeof c.score === "number"
                ? `<span style="color:var(--text-muted);font-size:11px;">BM25: ${c.score.toFixed(2)}</span>`
                : "";
            const sourceHtml = c.source_url
                ? `<a href="${c.source_url}" target="_blank" rel="noopener noreferrer"
                      style="font-size:11px;color:var(--primary);text-decoration:none;"
                   >${c.source_name || "来源"}</a>`
                : (c.source_name ? `<span style="font-size:11px;color:var(--text-muted);">${c.source_name}</span>` : "");
            const candidateBadge = c.candidate_data
                ? `<span style="font-size:10px;background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:3px;padding:1px 5px;margin-left:4px;">候选数据</span>`
                : "";

            return `
            <div style="border:1px solid var(--border);border-radius:6px;padding:12px 14px;margin-bottom:10px;">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:6px;">
                    <div style="font-weight:600;font-size:13px;line-height:1.4;">
                        ${c.title || "（无标题）"}${candidateBadge}
                    </div>
                    <div style="white-space:nowrap;display:flex;align-items:center;gap:6px;">
                        ${scoreHtml}
                        ${sourceHtml}
                    </div>
                </div>
                <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">
                    ${riskLevelHtml}${c.violation_type || ""}${c.violation_type && riskDims ? " · " : ""}${riskDims}
                </div>
                ${c.content_snippet ? `
                <div class="highlight-box" style="margin-bottom:6px;font-size:12px;">
                    <strong>原案例宣称：</strong>${c.content_snippet}
                </div>` : ""}
                ${c.ruling ? `
                <div style="font-size:12px;margin-bottom:4px;">
                    <strong>处理结果：</strong>${c.ruling}
                </div>` : ""}
                ${c.regulatory_logic ? `
                <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px;">
                    <strong>监管逻辑：</strong>${c.regulatory_logic}
                </div>` : ""}
                ${legalBasis ? `
                <div style="font-size:11px;color:var(--text-muted);border-top:1px solid var(--border);padding-top:6px;margin-top:6px;">
                    <strong>法律依据：</strong>${legalBasis}
                </div>` : ""}
            </div>`;
        }).join("");

        container.innerHTML = `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">共 ${cases.length} 条相关案例</div>${html}`;

    } catch (e) {
        container.innerHTML = '<span style="color:var(--text-muted);">暂无相关案例</span>';
    }
}


// ===== 规则库 =====

async function loadRulesView() {
    const detail = document.getElementById("detail-area");
    detail.innerHTML = '<div style="padding:32px;color:var(--text-muted);text-align:center;">加载中…</div>';
    currentRecord = null;

    let corrections = [];
    try {
        const res = await fetch("/api/corrections");
        corrections = await res.json();
    } catch (e) {
        detail.innerHTML = '<div style="padding:32px;color:var(--danger);">加载失败，请刷新重试</div>';
        return;
    }

    if (corrections.length === 0) {
        detail.innerHTML = `
            <div class="detail-empty">
                <div class="detail-empty-icon">📚</div>
                <p>暂无规则沉淀记录</p>
                <p style="font-size:12px;color:var(--text-muted);margin-top:8px;">法务提交「同意有补充」或「驳回」裁决后，纠正案例将自动出现在这里</p>
            </div>`;
        return;
    }

    const fbLabel = { override: "驳回纠正", refine: "补充完善" };
    const fbColor = { override: "var(--danger)", refine: "var(--primary)" };

    const rows = corrections.slice().reverse().map(c => {
        const isPaused = c.status === "paused";
        const statusBtn = isPaused
            ? `<button onclick="setCorrectionStatus('${c.id}','active')" style="font-size:11px;padding:2px 8px;border:1px solid var(--success);color:var(--success);background:#fff;border-radius:4px;cursor:pointer;">启用</button>`
            : `<button onclick="setCorrectionStatus('${c.id}','paused')" style="font-size:11px;padding:2px 8px;border:1px solid var(--border);color:var(--text-muted);background:#fff;border-radius:4px;cursor:pointer;">停用</button>`;
        return `<tr style="${isPaused ? 'opacity:0.45;' : ''}">
            <td style="padding:8px;white-space:nowrap;color:var(--text-muted);font-size:12px;">${c.created_at}</td>
            <td style="padding:8px;"><span style="font-weight:600;color:${fbColor[c.feedback_type] || '#333'};">${fbLabel[c.feedback_type] || c.feedback_type}</span></td>
            <td style="padding:8px;">${c.industry || '—'}</td>
            <td style="padding:8px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${c.content_snippet}">${c.content_snippet}</td>
            <td style="padding:8px;color:var(--text-muted);font-size:12px;">${c.ai_risk_level} · ${(c.ai_violation_types || []).join('、') || '—'}</td>
            <td style="padding:8px;max-width:200px;">${c.correct_judgment}</td>
            <td style="padding:8px;max-width:160px;color:var(--text-secondary);font-size:12px;">${c.reason}</td>
            <td style="padding:8px;white-space:nowrap;">
                ${statusBtn}
                <button onclick="deleteCorrection('${c.id}')" style="font-size:11px;padding:2px 8px;border:1px solid var(--danger);color:var(--danger);background:#fff;border-radius:4px;cursor:pointer;margin-left:4px;">删除</button>
            </td>
        </tr>`;
    }).join("");

    detail.innerHTML = `
        <div style="padding:20px 24px;">
            <div style="font-size:15px;font-weight:600;margin-bottom:4px;">规则沉淀库</div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:16px;">
                共 ${corrections.length} 条纠正记录（active: ${corrections.filter(c=>c.status==='active').length}）·
                AI审核时自动召回 top-3 相关案例注入 prompt
            </div>
            <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <thead>
                    <tr style="background:var(--bg-page);">
                        <th style="padding:8px;text-align:left;font-weight:600;white-space:nowrap;">时间</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">类型</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">行业</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">物料片段</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">AI原判定</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">法务纠正</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">理由</th>
                        <th style="padding:8px;text-align:left;font-weight:600;">操作</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            </div>
        </div>`;
}

async function setCorrectionStatus(id, status) {
    await fetch(`/api/corrections/${id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
    });
    loadRulesView();
}

async function deleteCorrection(id) {
    if (!confirm("确定删除这条纠正记录？删除后不可恢复，且 AI 将不再参考该案例。")) return;
    await fetch(`/api/corrections/${id}`, { method: "DELETE" });
    loadRulesView();
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
