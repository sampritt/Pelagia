/* Shared loading states for server navigation, async regions, and media. */
(() => {
    const DELAY = 160;
    const block = (kind = "line") => `<span class="skeleton skeleton-${kind}"></span>`;
    const identity = () => `<div class="skeleton-identity">${block("avatar")}<div>${block("title")}${block()}</div></div>`;
    const metrics = () => `<div class="skeleton-metrics">${Array.from({ length: 3 }, () => `<div>${block()}${block("title")}</div>`).join("")}</div>`;
    const card = () => `<div class="skeleton-card">${identity()}${block("title")}${block()}${block("media")}${metrics()}</div>`;
    const rows = () => Array.from({ length: 3 }, () => `<div class="skeleton-result">${block("title")}${block()}</div>`).join("");

    function pageKind(path) {
        if (path === "/home") return "feed";
        if (/^\/(you|users\/\d+)$/.test(path)) return "profile";
        if (path === "/you/settings" || /^\/dive\/(new|\d+\/edit)$/.test(path)) return "form";
        if (/^\/(dive\/\d+|share\/dive\/\d+|dive-sites\/\d+|dive-centers\/\d+)$/.test(path)) return "detail";
        if (/^\/(login|signup|auth\/(email|google))/.test(path)) return "auth";
        return "page";
    }

    function pageMarkup(kind) {
        if (kind === "feed") return `<div class="skeleton-feed"><div>${card()}${card()}</div><aside>${identity()}${metrics()}</aside></div>`;
        if (kind === "profile") return `${identity()}${metrics()}${block("chart")}${card()}`;
        if (kind === "form") return `${block("title")}<div class="skeleton-card skeleton-fields">${Array.from({ length: 8 }, () => `<div>${block()}${block("field")}</div>`).join("")}</div>`;
        if (kind === "detail") return `${identity()}${block("title")}${block("media")}${metrics()}<div class="skeleton-card">${rows()}</div>`;
        if (kind === "auth") return `<div class="skeleton-auth skeleton-card">${block("title")}${block()}${block("field")}${block("field")}</div>`;
        return `<div class="skeleton-card">${block("title")}${rows()}${rows()}</div>`;
    }

    const regionStates = new WeakMap();

    // A region owns its timer. Ending a fast request never paints a placeholder.
    function begin(host, label = "Loading", markup = rows(), { reveal = false } = {}) {
        if (!host) return () => {};
        regionStates.get(host)?.();
        if (host.matches?.("button")) markup = block("action");
        const previousBusy = host.getAttribute("aria-busy");
        const previousInert = host.inert;
        host.setAttribute("aria-busy", "true");
        let overlay;
        let ended = false;
        const timer = window.setTimeout(() => {
            if (reveal) host.hidden = false;
            host.classList.add("is-skeleton-loading");
            host.inert = true;
            overlay = document.createElement("div");
            overlay.className = "component-skeleton";
            overlay.setAttribute("aria-hidden", "true");
            overlay.innerHTML = markup;
            host.appendChild(overlay);
            announce(label);
        }, DELAY);
        const end = () => {
            if (ended) return;
            ended = true;
            window.clearTimeout(timer);
            overlay?.remove();
            host.classList.remove("is-skeleton-loading");
            host.inert = previousInert;
            if (previousBusy === null) host.removeAttribute("aria-busy");
            else host.setAttribute("aria-busy", previousBusy);
            regionStates.delete(host);
            const status = document.querySelector("[data-loading-status]");
            if (status?.textContent === label) announce("");
        };
        regionStates.set(host, end);
        return end;
    }

    function announce(message, visible = false) {
        const status = document.querySelector("[data-loading-status]");
        if (!status) return;
        status.textContent = message;
        status.classList.toggle("loading-notice", visible);
        status.classList.toggle("sr-only", !visible);
    }

    let navigationTimer;
    let recoveryTimer;
    let previousMainInert = false;
    function resetNavigation() {
        window.clearTimeout(navigationTimer);
        window.clearTimeout(recoveryTimer);
        const shell = document.querySelector("[data-navigation-skeleton]");
        const main = document.getElementById("mainContent");
        if (shell && !shell.hidden) {
            shell.hidden = true;
            main.inert = previousMainInert;
            main.removeAttribute("aria-busy");
        }
        document.body.classList.remove("is-navigating");
        announce("");
    }

    function startNavigation(href) {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || /\.(png|jpe?g|pdf|csv)$/i.test(url.pathname)) return;
        resetNavigation();
        navigationTimer = window.setTimeout(() => {
            const shell = document.querySelector("[data-navigation-skeleton]");
            const main = document.getElementById("mainContent");
            if (!shell || !main) return;
            const kind = pageKind(url.pathname);
            shell.dataset.layout = kind;
            shell.innerHTML = pageMarkup(kind);
            shell.hidden = false;
            previousMainInert = main.inert;
            main.inert = true;
            main.setAttribute("aria-busy", "true");
            document.body.classList.add("is-navigating");
            window.scrollTo({ top: 0, behavior: "instant" });
            announce("Loading page");
        }, DELAY);
        // A cancelled navigation or stalled connection must not trap the page.
        recoveryTimer = window.setTimeout(() => {
            resetNavigation();
            announce("This is taking longer than expected. You can try again.", true);
        }, 15000);
    }

    const imageStates = new WeakMap();
    function trackImage(img) {
        if (!img.getAttribute("src") || img.closest(".brand, .brand-mark, .welcome-wordmark, .auth-brand")) return;
        imageStates.get(img)?.();
        const host = img.closest("[data-share-carousel]") || img;
        if (img.complete) return;
        let timer;
        let timeout;
        const clear = () => {
            window.clearTimeout(timer);
            window.clearTimeout(timeout);
            host.classList.remove("is-media-loading");
            host.removeAttribute("aria-busy");
            img.removeEventListener("load", clear);
            img.removeEventListener("error", clear);
            imageStates.delete(img);
        };
        timer = window.setTimeout(() => {
            host.classList.add("is-media-loading");
            host.setAttribute("aria-busy", "true");
        }, DELAY);
        timeout = window.setTimeout(clear, 15000);
        img.addEventListener("load", clear);
        img.addEventListener("error", clear);
        imageStates.set(img, clear);
    }

    window.PelagiaLoading = { begin, announce, startNavigation, resetNavigation, pageKind,
        navigate(href) { startNavigation(href); window.location.assign(href); } };

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("img").forEach(trackImage);
        new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === "attributes") trackImage(mutation.target);
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType !== 1) return;
                    if (node.matches("img")) trackImage(node);
                    node.querySelectorAll("img").forEach(trackImage);
                });
                mutation.removedNodes.forEach((node) => {
                    if (node.nodeType !== 1) return;
                    if (node.matches("img")) imageStates.get(node)?.();
                    node.querySelectorAll("img").forEach((img) => imageStates.get(img)?.());
                });
            });
        }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src", "srcset"] });
        // Window listeners run after component handlers, including offline guards.
        window.addEventListener("click", (event) => {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            const link = event.target.closest("a[href]");
            if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
            const url = new URL(link.href, window.location.href);
            if (url.protocol !== "http:" && url.protocol !== "https:") return;
            if (url.pathname === window.location.pathname && url.search === window.location.search) return;
            startNavigation(url.href);
        });
        window.addEventListener("submit", (event) => {
            const form = event.target;
            if (event.defaultPrevented || form.method === "dialog" || (form.target && form.target !== "_self")) return;
            const submitter = event.submitter;
            if (submitter?.formTarget && submitter.formTarget !== "_self") return;
            // Keep the current form visible while its native submission is pending.
            const end = begin(submitter || form.querySelector("button[type='submit']"), "Saving", block("field"));
            window.setTimeout(end, 15000);
            window.addEventListener("pageshow", end, { once: true });
        });
        window.addEventListener("pageshow", resetNavigation);
        window.addEventListener("pagehide", resetNavigation);
        window.addEventListener("keydown", (event) => { if (event.key === "Escape") resetNavigation(); });
    });
})();
