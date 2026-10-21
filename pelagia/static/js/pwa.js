(() => {
    const displayMode = window.matchMedia("(display-mode: standalone)");
    const isStandalone = () => displayMode.matches || navigator.standalone === true;
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    const installButtons = [...document.querySelectorAll("[data-pwa-install]")];
    const dialog = document.querySelector("[data-pwa-install-dialog]");
    const offlineNotice = document.querySelector("[data-pwa-offline-notice]");
    const updateNotice = document.querySelector("[data-pwa-update-notice]");
    let installPrompt = null;
    let dialogTrigger = null;
    let registration = null;
    let updateRequested = false;

    function syncInstallation() {
        const installed = isStandalone();
        document.documentElement.classList.toggle("pwa-standalone", installed);
        installButtons.forEach((button) => {
            button.hidden = installed || !window.isSecureContext || (!installPrompt && !isIOS);
            button.textContent = isIOS ? "Add Pelagia to Home Screen" : "Install Pelagia";
        });
    }

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        installPrompt = event;
        syncInstallation();
    });
    window.addEventListener("appinstalled", () => {
        installPrompt = null;
        installButtons.forEach((button) => { button.hidden = true; });
        if (dialog?.open) dialog.close();
    });
    displayMode.addEventListener?.("change", syncInstallation);

    installButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (isIOS) {
                dialogTrigger = button;
                dialog?.showModal();
                return;
            }
            if (!installPrompt) return;
            const prompt = installPrompt;
            installPrompt = null;
            button.disabled = true;
            try {
                // Call synchronously inside the click to preserve user activation.
                await prompt.prompt();
                await prompt.userChoice;
            } catch {
                const notice = document.querySelector("[data-pwa-install-notice]");
                if (notice) notice.hidden = false;
            } finally {
                button.disabled = false;
                syncInstallation();
            }
        });
    });
    dialog?.querySelector("[data-pwa-install-close]")?.addEventListener("click", () => dialog.close());
    dialog?.addEventListener("close", () => dialogTrigger?.focus());
    dialog?.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    document.querySelectorAll("[data-pwa-guide]").forEach((button) => {
        button.addEventListener("click", () => {
            dialogTrigger = button;
            dialog?.showModal();
        });
    });
    syncInstallation();

    function syncConnection() {
        if (offlineNotice) offlineNotice.hidden = navigator.onLine !== false;
    }
    window.addEventListener("online", syncConnection);
    window.addEventListener("offline", syncConnection);
    syncConnection();
    document.addEventListener("submit", (event) => {
        if (navigator.onLine !== false) return;
        const method = event.submitter?.getAttribute("formmethod") || event.target.getAttribute("method") || "get";
        if (method.toLowerCase() === "get" || method.toLowerCase() === "dialog") return;
        event.preventDefault();
        event.stopImmediatePropagation();
        syncConnection();
    }, true);
    document.querySelector("[data-pwa-retry]")?.addEventListener("click", () => window.location.reload());

    function syncKeyboard() {
        const editing = document.activeElement?.matches("input:not([type=range]):not([type=checkbox]):not([type=radio]), textarea, [contenteditable=true]");
        const covered = window.visualViewport && window.innerHeight - window.visualViewport.height > 150;
        document.documentElement.classList.toggle("pwa-keyboard-open", Boolean(editing && covered));
        if (window.visualViewport) document.documentElement.style.setProperty("--pwa-viewport-height", `${window.visualViewport.height}px`);
    }
    window.visualViewport?.addEventListener("resize", syncKeyboard);
    document.addEventListener("focusin", syncKeyboard);
    document.addEventListener("focusout", syncKeyboard);
    syncKeyboard();

    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (!updateRequested) return;
        updateRequested = false;
        window.location.reload();
    });
    document.querySelector("[data-pwa-update]")?.addEventListener("click", () => {
        if (navigator.onLine === false) return;
        if (!registration?.waiting) {
            window.location.reload();
            return;
        }
        updateRequested = true;
        registration.waiting.postMessage({type: "SKIP_WAITING"});
    });
    navigator.serviceWorker.register("/service-worker.js", {scope: "/", updateViaCache: "none"}).then((next) => {
        registration = next;
        const showUpdate = () => {
            if (registration.waiting && navigator.serviceWorker.controller && updateNotice) updateNotice.hidden = false;
        };
        const watchWorker = (worker) => {
            worker?.addEventListener("statechange", showUpdate);
        };
        showUpdate();
        watchWorker(registration.installing);
        registration.addEventListener("updatefound", () => watchWorker(registration.installing));
        // Recheck when returning from the background, without forcing a reload.
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible" && navigator.onLine !== false) registration.update().catch(() => {});
        });
    }).catch((error) => console.warn("Pelagia offline support is unavailable.", error));
})();
