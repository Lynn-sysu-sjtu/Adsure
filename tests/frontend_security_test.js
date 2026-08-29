const fs = require("fs");
const vm = require("vm");

global.document = {
    addEventListener() {},
    querySelectorAll() { return []; },
    getElementById() { return null; },
};
global.window = { crypto: { randomUUID: () => "test-key" } };
global.fetch = async () => { throw new Error("not used"); };

const source = fs.readFileSync("static/main.js", "utf8");
vm.runInThisContext(source, { filename: "static/main.js" });

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

const attack = '<script>alert(1)</script><img src=x onerror="steal()">';
assert(escapeHtml(attack).includes("&lt;script&gt;"), "script tag must be escaped");
assert(!escapeHtml(attack).includes("<script>"), "raw script tag leaked");
assert(safeHttpsUrl("javascript:alert(1)") === "", "javascript URL must be rejected");
assert(safeHttpsUrl("http://example.com") === "", "non-HTTPS URL must be rejected");
assert(safeHttpsUrl("https://example.com/path").startsWith("https://"), "HTTPS URL should remain usable");

const industryHtml = buildIndustryCard({
    "行业领域": "美妆",
    "美妆_物料类型": attack,
    "补充背景资料": attack,
});
assert(!industryHtml.includes("<script>"), "industry data was not escaped");
assert(industryHtml.includes("&lt;script&gt;"), "escaped industry text missing");

const reviewHtml = renderAiReviewCard({
    "风险等级": "高风险",
    "审核状态": "待法务复核",
    "预审_命中要点": attack,
    "预审_修改建议": attack,
    "关键实体抽取": attack,
    "违规类型": [attack],
    "AI审核意见": attack,
});
assert(!reviewHtml.includes("<script>"), "review data was not escaped");

const formHtml = renderReviewForm({
    "法务审核人": '" autofocus onfocus="steal()',
    "法务批注": attack,
});
assert(!formHtml.includes("<script>"), "form data was not escaped");
assert(formHtml.includes("&quot;"), "attribute data was not escaped");

assert(!source.includes("alert("), "ordinary flow must not use alert dialogs");
assert(!source.includes("result.message"), "server messages must not be concatenated into UI");
assert(source.includes('setFormStatus("已收到，可稍后刷新查看结果")'), "long-running review needs an accurate refresh hint");
assert(!source.includes('setFormStatus("已收到，完成后会通知你")'), "page must not promise a notification to legal reviewers");
assert(!source.includes("BM25:"), "internal retrieval scores must not be rendered");

function element(value = "") {
    return {
        value,
        checked: false,
        disabled: false,
        textContent: "",
        innerHTML: "",
        style: {},
        classList: {
            contains() { return false; },
            add() {},
            remove() {},
        },
        closest() { return null; },
        addEventListener() {},
        appendChild() {},
        parentNode: { appendChild() {} },
    };
}

(async () => {
    const detail = element();
    document.getElementById = id => id === "detail-area" ? detail : null;
    showDetail({
        id: "rec-attachment",
        "审核状态": "已通过",
        "物料附件": [{ file_token: attack, name: attack }],
        "物料内容": attack,
        "违规类型": [attack],
        "法务批注": attack,
    });
    assert(!detail.innerHTML.includes("<script>"), "attachment or record text was not escaped");
    assert(detail.innerHTML.includes("&lt;script&gt;"), "escaped attachment text missing");
    assert(detail.innerHTML.includes(encodeURIComponent(attack)), "attachment token must be URL encoded");

    const casesContainer = element();
    document.getElementById = id => id === "cases-content" ? casesContainer : null;
    global.fetch = async () => ({ json: async () => ({ cases: [{
        title: attack,
        content_snippet: attack,
        ruling: attack,
        regulatory_logic: attack,
        legal_basis: [attack],
        risk_dimensions: [attack],
        violation_type: attack,
        source_name: attack,
        source_url: "javascript:alert(1)",
        score: 0.87,
    }] }) });
    await loadCases("rec-cases");
    assert(!casesContainer.innerHTML.includes("<script>"), "case data was not escaped");
    assert(casesContainer.innerHTML.includes("&lt;script&gt;"), "escaped case text missing");
    assert(!casesContainer.innerHTML.includes("href=\"javascript:"), "unsafe case link leaked");
    assert(!casesContainer.innerHTML.includes("BM25:"), "case score leaked into the page");

    const elements = {
        "ai-opinion": element("同意无补充"),
        verdict: element("通过"),
        "reviewer-name": element("法务测试"),
        "supplement-reason": element(""),
        "reject-reason": element(""),
        "correct-judgment": element(""),
        "final-suggestion": element("保留内容"),
        note: element("内部备注保持"),
        "btn-submit": element(""),
        "form-status": element(""),
        "detail-area": element(""),
        "record-list": element(""),
        "pending-count": element(""),
    };
    document.getElementById = id => elements[id] || null;
    document.querySelectorAll = () => [];
    vm.runInThisContext('currentRecord = {id: "rec-submit"}; reviewSubmissionKey = null;');
    let submittedHeaders = null;
    global.fetch = async (_url, options) => {
        submittedHeaders = options.headers;
        return { json: async () => ({ operation_status: "failed" }) };
    };
    await submitReview();
    assert(submittedHeaders["Idempotency-Key"] === "test-key", "review request needs an idempotency key");
    assert(elements.note.value === "内部备注保持", "failed submit must preserve form content");
    assert(elements["final-suggestion"].value === "保留内容", "failed submit must preserve selections");
    assert(elements["form-status"].textContent === "暂时未能提交，请稍后再试", "failure text must stay generic");

    vm.runInThisContext('currentRecord = {id: "rec-submit"}; reviewSubmissionKey = null; sleep = async () => {};');
    let postCount = 0;
    let operationCount = 0;
    global.fetch = async (url, options = {}) => {
        if (options.method === "POST") {
            postCount += 1;
            throw new Error("ambiguous transport failure");
        }
        if (String(url).startsWith("/api/review-operations/")) {
            operationCount += 1;
            return { json: async () => ({ operation_status: "succeeded" }) };
        }
        return { ok: true, json: async () => [] };
    };
    await submitReview();
    await Promise.resolve();
    assert(postCount === 1, "ambiguous response must not trigger a duplicate write");
    assert(operationCount === 1, "ambiguous response must query the existing operation");
    assert(elements["detail-area"].innerHTML.includes("裁决已提交"), "confirmed operation should show success");
    assert(elements["detail-area"].innerHTML.includes("运营会收到通知"), "success must not claim delivery already happened");
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
});
