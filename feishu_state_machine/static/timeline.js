(function attachTimeline(root) {
    "use strict";

    let latestRequest = 0;

    async function mount(recordId, detailArea) {
        const requestNumber = ++latestRequest;
        const casesCard = detailArea && detailArea.querySelector("#cases-card");
        if (!casesCard || !casesCard.parentNode) return;

        const card = document.createElement("div");
        card.className = "detail-card adsure-timeline";

        const title = document.createElement("div");
        title.className = "detail-card-title";
        const icon = document.createElement("span");
        icon.className = "icon";
        icon.textContent = "🕒";
        title.appendChild(icon);
        title.appendChild(document.createTextNode("审核时间线"));

        const content = document.createElement("div");
        content.className = "adsure-timeline-content";
        content.textContent = "加载中…";
        card.appendChild(title);
        card.appendChild(content);
        casesCard.parentNode.insertBefore(card, casesCard);

        try {
            const response = await fetch(`/api/records/${encodeURIComponent(recordId)}/timeline`);
            const data = await response.json();
            if (requestNumber !== latestRequest || !card.parentNode) return;
            if (!response.ok || !Array.isArray(data.events)) {
                throw new Error("timeline unavailable");
            }
            renderEvents(content, data.events);
        } catch (_error) {
            if (requestNumber === latestRequest && card.parentNode) {
                content.textContent = "暂未显示";
            }
        }
    }

    function renderEvents(container, events) {
        container.textContent = "";
        if (events.length === 0) {
            container.textContent = "暂无时间线记录";
            return;
        }
        events.forEach(event => {
            const row = document.createElement("div");
            row.className = "adsure-timeline-row";
            const marker = document.createElement("span");
            marker.className = "adsure-timeline-marker";
            marker.setAttribute("aria-hidden", "true");
            const body = document.createElement("div");
            body.className = "adsure-timeline-body";
            const heading = document.createElement("div");
            heading.className = "adsure-timeline-heading";
            heading.textContent = String(event.title || "审核进度已更新");
            const meta = document.createElement("div");
            meta.className = "adsure-timeline-meta";
            meta.textContent = [event.time, event.detail].filter(Boolean).join(" · ");
            body.appendChild(heading);
            if (meta.textContent) body.appendChild(meta);
            row.appendChild(marker);
            row.appendChild(body);
            container.appendChild(row);
        });
    }

    root.AdsureTimeline = { mount };
})(typeof window !== "undefined" ? window : globalThis);
