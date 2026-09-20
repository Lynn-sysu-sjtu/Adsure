(function attachMemoryCenter(root) {
    "use strict";

    const SETTINGS_URL = "/api/memory-center/settings";
    const LOAD_FAILED = "暂时未能加载设置";
    const SWITCH_FAILED = "暂时未能切换，请稍后再试";

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function build(container) {
        container.textContent = "";
        const shell = element("div", "memory-center");
        const line = element("div", "memory-center-line");
        const label = element("span", "memory-center-label", "合规记忆中心");
        const button = element("button", "memory-center-switch");
        button.type = "button";
        button.setAttribute("role", "switch");
        button.setAttribute("aria-label", "合规记忆中心");
        const stateText = element("span", "memory-center-state", "OFF");
        button.appendChild(stateText);
        line.appendChild(label);
        line.appendChild(button);
        shell.appendChild(line);
        const description = element("div", "memory-center-description");
        const message = element("div", "memory-center-message");
        message.setAttribute("role", "status");
        message.setAttribute("aria-live", "polite");
        shell.appendChild(description);
        shell.appendChild(message);
        container.appendChild(shell);
        return { button, stateText, description, message };
    }

    function render(refs, state) {
        refs.button.className = state.enabled
            ? "memory-center-switch is-on"
            : "memory-center-switch";
        refs.button.setAttribute("aria-checked", state.enabled ? "true" : "false");
        refs.button.disabled = !state.ready || state.pending;
        refs.stateText.textContent = state.enabled ? "ON" : "OFF";
        refs.description.textContent = state.enabled
            ? "已开启：审核会参考同一行业的有效纠正记录。"
            : "已关闭：审核不会参考历史纠正，新的法务纠正仍会继续沉淀。";
        refs.message.textContent = state.message;
    }

    async function readSetting() {
        const response = await fetch(SETTINGS_URL, {
            headers: { Accept: "application/json" },
        });
        const data = await response.json();
        if (!response.ok || !data || typeof data.enabled !== "boolean") {
            throw new Error("unavailable");
        }
        return data.enabled;
    }

    async function toggle(container, token, refs, state, onStateChange) {
        if (!state.ready || state.pending) return;
        const original = state.enabled;
        const requested = !original;
        state.pending = true;
        state.message = "";
        render(refs, state);

        let confirmed = null;
        try {
            const response = await fetch(SETTINGS_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: requested }),
            });
            const data = await response.json();
            if (response.ok && data && typeof data.enabled === "boolean") {
                confirmed = data.enabled;
            }
        } catch (_error) {
            confirmed = null;
        }

        if (confirmed !== requested) {
            try {
                confirmed = await readSetting();
            } catch (_error) {
                confirmed = null;
            }
        }
        if (container.__adsureMemoryToken !== token) return;

        state.pending = false;
        if (confirmed === requested) {
            state.enabled = requested;
            state.message = "";
        } else {
            state.enabled = original;
            state.message = SWITCH_FAILED;
        }
        render(refs, state);
        if (typeof onStateChange === "function") onStateChange(state.enabled);
    }

    async function initialize(container, options) {
        if (!container) return;
        const onStateChange = options && typeof options.onStateChange === "function"
            ? options.onStateChange : null;
        const token = {};
        container.__adsureMemoryToken = token;
        const refs = build(container);
        const state = { enabled: false, ready: false, pending: false, message: "" };
        refs.button.addEventListener("click", () => toggle(container, token, refs, state, onStateChange));
        render(refs, state);
        try {
            state.enabled = await readSetting();
            state.ready = true;
        } catch (_error) {
            state.ready = false;
            state.message = LOAD_FAILED;
        }
        if (container.__adsureMemoryToken !== token) return;
        render(refs, state);
        if (onStateChange && state.ready) onStateChange(state.enabled);
    }

    root.AdsureMemoryCenter = { initialize };
})(typeof window !== "undefined" ? window : globalThis);
