(function attachDeliveryOperations(root) {
    "use strict";

    let page = 1;
    let totalPages = 1;
    let loading = false;

    function textCell(row, value) {
        const cell = document.createElement("td");
        cell.textContent = String(value ?? "—");
        row.appendChild(cell);
    }

    async function load(targetPage = 1, successMessage = "") {
        if (loading) return;
        loading = true;
        setMessage("加载中…");
        const params = new URLSearchParams({
            page: String(targetPage),
            page_size: "20",
        });
        const status = document.getElementById("ops-status").value;
        const cardType = document.getElementById("ops-card-type").value;
        const record = document.getElementById("ops-record").value.trim();
        if (status) params.set("status", status);
        if (cardType) params.set("card_type", cardType);
        if (record) params.set("record", record);
        try {
            const response = await fetch(`/api/ops/deliveries?${params.toString()}`);
            const data = await response.json();
            if (!response.ok || !Array.isArray(data.items)) throw new Error("unavailable");
            page = data.page;
            totalPages = data.total_pages;
            renderRows(data.items);
            document.getElementById("ops-page-label").textContent = `第 ${page} / ${totalPages} 页，共 ${data.total} 条`;
            document.getElementById("ops-prev").disabled = page <= 1;
            document.getElementById("ops-next").disabled = page >= totalPages;
            setMessage(successMessage || (data.items.length ? "" : "暂无投递记录"));
        } catch (_error) {
            renderRows([]);
            setMessage("暂时无法处理");
        } finally {
            loading = false;
        }
    }

    function renderRows(items) {
        const body = document.getElementById("ops-delivery-rows");
        body.textContent = "";
        items.forEach(item => {
            const row = document.createElement("tr");
            [
                item.record_id,
                item.business_type,
                item.card_type,
                item.recipient,
                item.status,
                `${item.attempts}/${item.max_attempts}`,
                item.issue,
                item.message,
                item.created_at,
                item.updated_at,
            ].forEach(value => textCell(row, value));
            const actionCell = document.createElement("td");
            if (item.can_replay) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "adsure-ops-replay";
                button.textContent = "重新发送";
                button.addEventListener("click", () => replay(item.delivery_id, button));
                actionCell.appendChild(button);
            } else {
                actionCell.textContent = "—";
            }
            row.appendChild(actionCell);
            body.appendChild(row);
        });
    }

    async function replay(deliveryId, button) {
        button.disabled = true;
        try {
            const response = await fetch(`/api/ops/deliveries/${encodeURIComponent(deliveryId)}/replay`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: "{}",
            });
            const data = await response.json();
            const copy = {
                replayed: "已重新安排发送",
                updated: "状态已更新，请刷新查看",
                unavailable: "暂时无法处理",
            };
            const resultMessage = copy[data.result] || "暂时无法处理";
            if (response.ok) {
                await load(page, resultMessage);
            } else {
                setMessage(resultMessage);
            }
        } catch (_error) {
            setMessage("暂时无法处理");
        } finally {
            button.disabled = false;
        }
    }

    function setMessage(message) {
        document.getElementById("ops-status-message").textContent = message;
    }

    function initialize() {
        document.getElementById("ops-refresh").addEventListener("click", () => load(page));
        document.getElementById("ops-filter").addEventListener("click", () => load(1));
        document.getElementById("ops-prev").addEventListener("click", () => load(page - 1));
        document.getElementById("ops-next").addEventListener("click", () => load(page + 1));
        load(1);
    }

    root.AdsureDeliveryOperations = { initialize };
    document.addEventListener("DOMContentLoaded", initialize);
})(typeof window !== "undefined" ? window : globalThis);
