const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.className = "";
        this.textContent = "";
        this.disabled = false;
        this.hidden = false;
    }
    appendChild(child) {
        this.children.push(child);
        return child;
    }
    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }
    addEventListener(name, callback) {
        this.listeners[name] = callback;
    }
    set innerHTML(_value) {
        throw new Error("memory center must not use innerHTML");
    }
}

function response(enabled, ok = true) {
    return { ok, json: async () => ({ enabled }) };
}

function refs(container) {
    const shell = container.children[0];
    return {
        button: shell.children[0].children[1],
        description: shell.children[1],
        message: shell.children[2],
    };
}

(async () => {
    const requests = [];
    const replies = [];
    const context = {
        window: {},
        globalThis: {},
        document: { createElement: tag => new Element(tag) },
        fetch: async (url, options = {}) => {
            requests.push({ url, options });
            const reply = replies.shift();
            if (reply instanceof Error) throw reply;
            return reply;
        },
        Error,
        JSON,
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync("static/memory_center.js", "utf8"), context);
    const center = context.window.AdsureMemoryCenter;

    replies.push(response(false));
    const first = new Element("div");
    await center.initialize(first);
    let ui = refs(first);
    assert.strictEqual(ui.button.attributes.role, "switch");
    assert.strictEqual(ui.button.attributes["aria-checked"], "false");
    assert.strictEqual(ui.button.disabled, false);
    assert.strictEqual(ui.button.children[0].textContent, "OFF");
    assert(ui.description.textContent.includes("新的法务纠正仍会继续沉淀"));

    replies.push(response(true));
    await ui.button.listeners.click();
    assert.strictEqual(requests.length, 2, "confirmed POST must not add a GET");
    assert.strictEqual(ui.button.attributes["aria-checked"], "true");
    assert.strictEqual(ui.button.children[0].textContent, "ON");
    assert(ui.description.textContent.includes("同一行业的有效纠正记录"));

    let releasePost;
    replies.push(new Promise(resolve => { releasePost = resolve; }));
    const pendingToggle = ui.button.listeners.click();
    await Promise.resolve();
    assert.strictEqual(ui.button.disabled, true, "switch must be disabled while saving");
    releasePost(response(false));
    await pendingToggle;
    assert.strictEqual(ui.button.attributes["aria-checked"], "false");

    replies.push(response(false));
    const uncertain = new Element("div");
    await center.initialize(uncertain);
    ui = refs(uncertain);
    const beforeUncertain = requests.length;
    replies.push(new Error("ambiguous"), response(false));
    await ui.button.listeners.click();
    assert.strictEqual(
        requests.length,
        beforeUncertain + 2,
        "uncertain POST must use exactly one confirming GET",
    );
    assert.strictEqual(ui.button.attributes["aria-checked"], "false");
    assert.strictEqual(ui.button.disabled, false);
    assert.strictEqual(ui.message.textContent, "暂时未能切换，请稍后再试");

    replies.push(new Error("settings unavailable"));
    const failed = new Element("div");
    await center.initialize(failed);
    ui = refs(failed);
    assert.strictEqual(ui.button.disabled, true);
    assert.strictEqual(ui.message.textContent, "暂时未能加载设置");

    const source = fs.readFileSync("static/memory_center.js", "utf8");
    const mainSource = fs.readFileSync("static/main.js", "utf8");
    assert(!source.includes("innerHTML"));
    assert(!source.includes("alert("));
    assert(mainSource.includes('const emptyState = corrections.length === 0'));
    assert(mainSource.includes('id="memory-center-mount"'));
    assert(mainSource.includes("共 ${corrections.length} 条纠正记录，其中"));
    assert(!mainSource.includes("active: ${corrections"));

    console.log("memory center frontend tests passed");
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
