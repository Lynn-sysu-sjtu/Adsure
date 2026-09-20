const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.parentNode = null;
        this.attributes = {};
        this.className = "";
        this.textContent = "";
    }
    appendChild(child) {
        child.parentNode = this;
        this.children.push(child);
        return child;
    }
    insertBefore(child, anchor) {
        child.parentNode = this;
        const index = this.children.indexOf(anchor);
        this.children.splice(index < 0 ? this.children.length : index, 0, child);
        return child;
    }
    setAttribute(name, value) {
        this.attributes[name] = value;
    }
    set innerHTML(_value) {
        throw new Error("timeline must not use innerHTML");
    }
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => {
        resolve = yes;
        reject = no;
    });
    return { promise, resolve, reject };
}

function detailFixture() {
    const parent = new Element("section");
    const cases = new Element("div");
    cases.id = "cases-card";
    parent.appendChild(cases);
    return {
        parent,
        detail: { querySelector: selector => selector === "#cases-card" ? cases : null },
    };
}

async function flush() {
    await Promise.resolve();
    await Promise.resolve();
}

(async () => {
    const requests = [];
    const context = {
        window: {},
        globalThis: {},
        document: {
            createElement: tag => new Element(tag),
            createTextNode: text => {
                const node = new Element("#text");
                node.textContent = String(text);
                return node;
            },
        },
        encodeURIComponent,
        fetch: url => {
            const item = deferred();
            requests.push({ url, ...item });
            return item.promise;
        },
        Error,
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync("static/timeline.js", "utf8"), context);
    const timeline = context.window.AdsureTimeline;

    const first = detailFixture();
    const second = detailFixture();
    const firstMount = timeline.mount("rec-one", first.detail);
    const secondMount = timeline.mount("rec-two", second.detail);

    requests[1].resolve({
        ok: true,
        json: async () => ({
            events: [{
                time: "2026-09-02 10:00",
                title: "<img src=x onerror=alert(1)>",
                detail: "安全文本",
            }],
        }),
    });
    await flush();
    requests[0].resolve({
        ok: true,
        json: async () => ({
            events: [{ time: "旧", title: "旧响应", detail: "不应覆盖" }],
        }),
    });
    await Promise.all([firstMount, secondMount]);

    const secondContent = second.parent.children[0].children[1];
    const heading = secondContent.children[0].children[1].children[0];
    assert.strictEqual(heading.textContent, "<img src=x onerror=alert(1)>");
    assert.strictEqual(first.parent.children[0].children[1].textContent, "加载中…");

    const empty = detailFixture();
    const emptyMount = timeline.mount("rec-empty", empty.detail);
    requests[2].resolve({
        ok: true,
        json: async () => ({ events: [] }),
    });
    await emptyMount;
    assert.strictEqual(empty.parent.children[0].children[1].textContent, "暂无时间线记录");

    const failed = detailFixture();
    const failedMount = timeline.mount("rec-failed", failed.detail);
    requests[3].reject(new Error("network"));
    await failedMount;
    assert.strictEqual(failed.parent.children[0].children[1].textContent, "暂未显示");

    console.log("timeline frontend tests passed");
})().catch(error => {
    console.error(error);
    process.exit(1);
});
