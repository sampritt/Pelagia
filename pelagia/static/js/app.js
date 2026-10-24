const clamp = (value, min, max) => Math.max(min, Math.min(max, Number(value) || 0));

const escapeHtml = (value) =>
    String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

const CURRENT_STRENGTHS = [
    { value: "none", label: "None" },
    { value: "light", label: "Light" },
    { value: "moderate", label: "Moderate" },
    { value: "strong", label: "Strong" },
    { value: "very strong", label: "Very Strong" },
];

const MAP_TILE_SIZE = 256;
const MAP_MIN_ZOOM = 2;
const MAP_MAX_ZOOM = 16;
const MAP_STATIC_ZOOM = 10;

const isValidLatLng = (lat, lng) => {
    const nextLat = Number(lat);
    const nextLng = Number(lng);
    return Number.isFinite(nextLat) && Number.isFinite(nextLng) && nextLat >= -85 && nextLat <= 85 && nextLng >= -180 && nextLng <= 180;
};

const normalizeLng = (lng) => {
    let next = Number(lng);
    while (next < -180) {
        next += 360;
    }
    while (next > 180) {
        next -= 360;
    }
    return next;
};

const worldSizeAtZoom = (zoom) => MAP_TILE_SIZE * 2 ** zoom;

function latLngToWorldPoint(lat, lng, zoom) {
    const worldSize = worldSizeAtZoom(zoom);
    const boundedLat = clamp(lat, -85, 85);
    const normalizedLng = normalizeLng(lng);
    const sinLat = Math.sin((boundedLat * Math.PI) / 180);
    return {
        x: ((normalizedLng + 180) / 360) * worldSize,
        y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * worldSize,
    };
}

function wrapTileX(tileX, zoom) {
    const count = 2 ** zoom;
    return ((tileX % count) + count) % count;
}

function mapTileUrl(zoom, tileX, tileY) {
    return `https://tile.openstreetmap.org/${zoom}/${wrapTileX(tileX, zoom)}/${tileY}.png`;
}

function ensureTileLayer(container, className = "map-tile-layer") {
    let layer = container.querySelector(`.${className}`);
    if (!layer) {
        layer = document.createElement("div");
        layer.className = className;
        layer.setAttribute("aria-hidden", "true");
        container.prepend(layer);
    }
    return layer;
}

function renderTileGrid(layer, { centerPoint, zoom, width, height }) {
    const originX = centerPoint.x - width / 2;
    const originY = centerPoint.y - height / 2;
    const maxTileY = 2 ** zoom - 1;
    const startX = Math.floor(originX / MAP_TILE_SIZE);
    const endX = Math.floor((originX + width) / MAP_TILE_SIZE);
    const startY = Math.max(0, Math.floor(originY / MAP_TILE_SIZE));
    const endY = Math.min(maxTileY, Math.floor((originY + height) / MAP_TILE_SIZE));
    const fragment = document.createDocumentFragment();

    for (let tileY = startY; tileY <= endY; tileY += 1) {
        for (let tileX = startX; tileX <= endX; tileX += 1) {
            const img = document.createElement("img");
            img.className = "map-tile";
            img.alt = "";
            img.decoding = "async";
            img.draggable = false;
            img.loading = "lazy";
            img.src = mapTileUrl(zoom, tileX, tileY);
            img.addEventListener("error", () => {
                img.classList.add("tile-error");
            });
            img.style.left = `${Math.round(tileX * MAP_TILE_SIZE - originX)}px`;
            img.style.top = `${Math.round(tileY * MAP_TILE_SIZE - originY)}px`;
            fragment.appendChild(img);
        }
    }

    layer.replaceChildren(fragment);
    return { originX, originY };
}

function renderMiniTileMap(map) {
    const lat = Number(map.dataset.mapLat);
    const lng = Number(map.dataset.mapLng);
    if (!isValidLatLng(lat, lng)) {
        map.classList.add("map-pending");
        return;
    }
    map.classList.remove("map-pending");
    map.classList.add("is-tiled");

    const width = Math.max(220, map.clientWidth);
    const height = Math.max(160, map.clientHeight);
    const zoom = clamp(map.dataset.mapZoom || MAP_STATIC_ZOOM, MAP_MIN_ZOOM, MAP_MAX_ZOOM);
    const layer = ensureTileLayer(map);
    renderTileGrid(layer, {
        centerPoint: latLngToWorldPoint(lat, lng, zoom),
        zoom,
        width,
        height,
    });
    const pin = map.querySelector(".map-pin");
    if (pin) {
        pin.style.left = "50%";
        pin.style.top = "50%";
    }
}

function initStaticMaps(root = document) {
    root.querySelectorAll("[data-static-map]").forEach(renderMiniTileMap);
}

const debounce = (fn, wait = 180) => {
    let timeout;
    return (...args) => {
        window.clearTimeout(timeout);
        timeout = window.setTimeout(() => fn(...args), wait);
    };
};

async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        ...(typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? { signal: AbortSignal.timeout(15000) } : {}),
        ...options,
    });
    if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
}

const suggestionRequests = new WeakMap();

function cancelSuggestionLoad(menu) {
    const pending = suggestionRequests.get(menu);
    if (!pending) return;
    suggestionRequests.delete(menu);
    pending.end();
    pending.controller?.abort();
}

function createSuggestionLoader(input, menu) {
    let dismissed = false;
    input.addEventListener("input", () => { dismissed = false; hideMenu(menu); });
    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { dismissed = true; hideMenu(menu); }
    });
    input.addEventListener("blur", () => {
        window.setTimeout(() => {
            if (!input.closest(".autocomplete-field")?.contains(document.activeElement)) {
                dismissed = true;
                hideMenu(menu);
            }
        }, 0);
    });
    document.addEventListener("click", (event) => {
        if (!input.closest(".autocomplete-field")?.contains(event.target)) { dismissed = true; hideMenu(menu); }
    });
    return (url, render) => {
        if (dismissed || document.activeElement !== input) return;
        return loadSuggestionRegion(menu, url, render, () => !dismissed && document.activeElement === input);
    };
}

async function loadSuggestionRegion(menu, url, render, isCurrent = () => true) {
    cancelSuggestionLoad(menu);
    menu.innerHTML = "";
    menu.hidden = true;
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const end = window.PelagiaLoading?.begin(menu, "Loading suggestions", undefined, { reveal: true }) || (() => {});
    const timeout = controller ? window.setTimeout(() => controller.abort(), 15000) : null;
    const pending = { end, controller };
    suggestionRequests.set(menu, pending);
    try {
        const items = await fetchJson(url, controller ? { signal: controller.signal } : {});
        if (suggestionRequests.get(menu) !== pending || !isCurrent()) return;
        end();
        suggestionRequests.delete(menu);
        render(items);
        if (!items.length) {
            menu.innerHTML = '<p class="suggestion-message" role="status">No matches found. Try another search.</p>';
            menu.hidden = false;
        }
    } catch (error) {
        if (suggestionRequests.get(menu) !== pending || !isCurrent()) return;
        menu.innerHTML = '<p class="suggestion-message" role="status">Couldn’t load suggestions. Type to try again.</p>';
        menu.hidden = false;
    } finally {
        if (timeout !== null) window.clearTimeout(timeout);
        if (suggestionRequests.get(menu) === pending) {
            end();
            suggestionRequests.delete(menu);
        }
    }
}

async function withPendingAction(elements, task) {
    const targets = Array.from(elements).filter(Boolean);
    if (targets.some((target) => target.disabled)) return;
    const finish = targets.map((target) => {
        target.disabled = true;
        return window.PelagiaLoading?.begin(target, "Saving") || (() => {});
    });
    try {
        await task();
    } catch (error) {
        window.PelagiaLoading?.announce("Couldn’t save that change. Please try again.", true);
    } finally {
        targets.forEach((target, index) => { finish[index](); target.disabled = false; });
    }
}

function initDiveInteractions() {
    document.addEventListener("click", async (event) => {
        const likeButton = event.target.closest("[data-like]");
        if (likeButton) {
            event.preventDefault();
            event.stopPropagation();
            await toggleLike(likeButton.dataset.diveId);
            return;
        }

        const openButton = event.target.closest("[data-open-dive]");
        if (openButton) {
            event.preventDefault();
            event.stopPropagation();
            openDive(openButton.dataset.openDive);
            return;
        }

        const card = event.target.closest("[data-dive-card]");
        if (card && !event.target.closest("a, button, input, select, textarea")) {
            openDive(card.dataset.diveId);
        }

        const centerLikeButton = event.target.closest("[data-center-like]");
        if (centerLikeButton) {
            event.preventDefault();
            await toggleCenterLike(centerLikeButton.dataset.centerId);
            return;
        }

        const siteLikeButton = event.target.closest("[data-site-like]");
        if (siteLikeButton) {
            event.preventDefault();
            await toggleSiteLike(siteLikeButton.dataset.siteId);
        }
    });

    document.addEventListener("keydown", (event) => {
        if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-dive-card]")) {
            event.preventDefault();
            openDive(event.target.dataset.diveId);
        }
    });

    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("[data-comment-form]");
        const centerForm = event.target.closest("[data-center-comment-form]");
        const siteForm = event.target.closest("[data-site-comment-form]");
        if (!form && !centerForm && !siteForm) {
            return;
        }
        event.preventDefault();
        const input = (form || centerForm || siteForm).querySelector("input[name='body']");
        const body = input.value.trim();
        if (!body) {
            return;
        }
        const activeForm = form || centerForm || siteForm;
        await withPendingAction(activeForm.querySelectorAll("button[type='submit']"), async () => {
            if (siteForm) {
                const data = await fetchJson(`/api/dive-sites/${siteForm.dataset.siteId}/comments`, {
                    method: "POST",
                    body: new FormData(siteForm),
                });
                if (input.value.trim() === body) input.value = "";
                renderComments(document.querySelector("[data-site-comments]"), data.comments);
                return;
            }
            if (centerForm) {
                const data = await fetchJson(`/api/dive-centers/${centerForm.dataset.centerId}/comments`, {
                    method: "POST",
                    body: new FormData(centerForm),
                });
                if (input.value.trim() === body) input.value = "";
                renderComments(document.querySelector("[data-center-comments]"), data.comments);
                return;
            }
            const data = await fetchJson(`/api/dives/${form.dataset.diveId}/comments`, {
                method: "POST",
                body: new FormData(form),
            });
            if (input.value.trim() === body) input.value = "";
            const commentsContainer = form.closest("[data-dive-detail]")?.querySelector("[data-comments]");
            renderComments(commentsContainer, data.comments);
            document.querySelectorAll(`[data-open-dive='${form.dataset.diveId}'] [data-comment-count], [data-dive-detail] [data-comment-count]`).forEach((span) => {
                span.textContent = data.comments.length;
            });
        });
    });

    const params = new URLSearchParams(window.location.search);
    if (params.has("open")) {
        openDive(params.get("open"));
    }
}

function initDiveSharing() {
    const dialog = document.querySelector("[data-share-dialog]");
    if (!dialog) return;
    const link = dialog.querySelector("[data-share-link]");
    const copy = dialog.querySelector("[data-share-copy]");
    const copyLabel = dialog.querySelector("[data-share-copy-label]");
    const save = dialog.querySelector("[data-share-save]");
    const native = dialog.querySelector("[data-share-native]");
    const status = dialog.querySelector("[data-share-status]");
    const preview = dialog.querySelector("[data-share-preview]");
    const carousel = dialog.querySelector("[data-share-carousel]");
    const styleButtons = [...dialog.querySelectorAll("[data-share-style]")];
    const saveLabel = dialog.querySelector("[data-share-save-label]");
    let trigger;
    let shareData;
    let previewFile;
    let downloadUrl;
    let imageStyles = [];
    let selectedStyle = 0;
    let swipeStart;
    let generation = 0;

    const supportsNativeSharing = () => window.isSecureContext && typeof navigator.share === "function";
    const downloadImage = () => {
        const anchor = document.createElement("a");
        anchor.href = downloadUrl;
        anchor.download = imageStyles[selectedStyle].filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        status.textContent = "Image download started.";
    };

    const prepareMobileImage = async (style, version) => {
        // Load before the Save click so sharing the file retains user activation.
        save.disabled = true;
        try {
            const response = await fetch(style.imageUrl, { credentials: "same-origin", signal: AbortSignal.timeout(10000) });
            if (!response.ok) throw new Error("Image unavailable");
            const file = new File([await response.blob()], style.filename, { type: style.mimeType });
            if (version === generation && navigator.canShare({ files: [file] })) previewFile = file;
        } catch {
            // The server's attachment download remains available.
        } finally {
            if (version === generation) save.disabled = false;
        }
    };

    const selectStyle = (index) => {
        if (!imageStyles.length) return;
        selectedStyle = (index + imageStyles.length) % imageStyles.length;
        const style = imageStyles[selectedStyle];
        const version = ++generation;
        previewFile = null;
        save.disabled = false;
        status.textContent = "";
        downloadUrl = style.downloadUrl;
        preview.src = style.imageUrl;
        preview.alt = style.alt;
        preview.dataset.transparent = String(selectedStyle === 1);
        saveLabel.textContent = "Save image";
        dialog.querySelector("[data-share-counter]").textContent = `Image ${selectedStyle + 1} of ${imageStyles.length}`;
        styleButtons.forEach((button, buttonIndex) => button.setAttribute("aria-pressed", String(buttonIndex === selectedStyle)));
        if (supportsNativeSharing() && typeof navigator.canShare === "function" && window.matchMedia("(pointer: coarse)").matches) {
            prepareMobileImage(style, version);
        }
    };

    styleButtons.forEach((button, index) => button.addEventListener("click", () => selectStyle(index)));
    dialog.querySelector("[data-share-previous]").addEventListener("click", () => selectStyle(selectedStyle - 1));
    dialog.querySelector("[data-share-next]").addEventListener("click", () => selectStyle(selectedStyle + 1));
    carousel.addEventListener("keydown", (event) => {
        const index = { ArrowLeft: selectedStyle - 1, ArrowRight: selectedStyle + 1, Home: 0, End: imageStyles.length - 1 }[event.key];
        if (index === undefined || event.altKey || event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        selectStyle(index);
    });
    carousel.addEventListener("pointerdown", (event) => {
        swipeStart = null;
        if (event.pointerType === "mouse" || !event.isPrimary || event.target.closest("button")) return;
        swipeStart = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
        carousel.setPointerCapture(event.pointerId);
    });
    carousel.addEventListener("pointerup", (event) => {
        const start = swipeStart;
        swipeStart = null;
        if (!start || start.pointerId !== event.pointerId) return;
        const dx = event.clientX - start.x;
        const dy = event.clientY - start.y;
        if (Math.abs(dx) >= 40 && Math.abs(dx) > Math.abs(dy) * 1.25) selectStyle(selectedStyle + (dx < 0 ? 1 : -1));
    });
    carousel.addEventListener("pointercancel", () => { swipeStart = null; });

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-share-dive]");
        if (!button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        trigger = button;
        link.value = button.dataset.shareUrl;
        const message = `Check out my logged dive at ${button.dataset.shareTitle}`;
        shareData = { title: message, text: message, url: link.value };
        imageStyles = [
            { imageUrl: button.dataset.shareImage, downloadUrl: button.dataset.shareDownload,
                filename: "pelagia-dive.jpg", mimeType: "image/jpeg",
                alt: "Branded dive image with a photo or map" },
            { imageUrl: button.dataset.shareTransparentImage, downloadUrl: button.dataset.shareTransparentDownload,
                filename: "pelagia-dive-transparent.png", mimeType: "image/png",
                alt: "Transparent overlay with the dive site, max depth, dive time and Pelagia logo" },
        ];
        swipeStart = null;
        link.hidden = true;
        status.textContent = "";
        copyLabel.textContent = "Copy link";
        dialog.showModal();
        selectStyle(0);
    });
    dialog.querySelector("[data-share-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => {
        generation += 1;
        previewFile = null;
        swipeStart = null;
        trigger?.focus();
    });
    copy.addEventListener("click", async () => {
        try {
            if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
            await navigator.clipboard.writeText(link.value);
            copyLabel.textContent = "Copied";
            status.textContent = "Link copied. Ready to send.";
        } catch {
            copyLabel.textContent = "Copy link";
            link.hidden = false;
            link.focus();
            link.select();
            link.setSelectionRange(0, link.value.length);
            status.textContent = "Select and copy this link to share your dive.";
        }
    });
    save.addEventListener("click", async () => {
        status.textContent = "";
        if (!previewFile) {
            downloadImage();
            return;
        }
        try {
            status.textContent = "Choose Save Image or a destination in the share sheet.";
            await navigator.share({ files: [previewFile] });
            status.textContent = "Image shared.";
        } catch (error) {
            if (error.name === "AbortError") status.textContent = "";
            else downloadImage();
        }
    });
    native.addEventListener("click", async () => {
        status.textContent = "";
        if (!supportsNativeSharing()) {
            status.textContent = "App sharing is unavailable in this browser. Use Copy link instead.";
            return;
        }
        // Keep this call directly inside a click: native sharing requires
        // user activation, which can be lost after asynchronous preparation.
        try {
            await navigator.share(shareData);
            status.textContent = "Your dive link was shared.";
        } catch (error) {
            if (error.name !== "AbortError") status.textContent = "App sharing is unavailable. You can copy the link instead.";
        }
    });
}

async function toggleLike(diveId) {
    await withPendingAction(document.querySelectorAll(`[data-like][data-dive-id='${diveId}']`), async () => {
        const data = await fetchJson(`/api/dives/${diveId}/like`, { method: "POST" });
        document.querySelectorAll(`[data-like][data-dive-id='${diveId}']`).forEach((button) => {
            button.classList.toggle("liked", data.liked);
            const count = button.querySelector("[data-like-count]");
            if (count) {
                count.textContent = data.count;
            }
        });
    });
}

async function toggleCenterLike(centerId) {
    await withPendingAction(document.querySelectorAll(`[data-center-like][data-center-id='${centerId}']`), async () => {
        const data = await fetchJson(`/api/dive-centers/${centerId}/like`, { method: "POST" });
        document.querySelectorAll(`[data-center-like][data-center-id='${centerId}']`).forEach((button) => {
            button.classList.toggle("liked", data.liked);
            const count = button.querySelector("[data-center-like-count]");
            if (count) {
                count.textContent = data.count;
            }
        });
    });
}

async function toggleSiteLike(siteId) {
    await withPendingAction(document.querySelectorAll(`[data-site-like][data-site-id='${siteId}']`), async () => {
        const data = await fetchJson(`/api/dive-sites/${siteId}/like`, { method: "POST" });
        document.querySelectorAll(`[data-site-like][data-site-id='${siteId}']`).forEach((button) => {
            button.classList.toggle("liked", data.liked);
            const count = button.querySelector("[data-site-like-count]");
            if (count) {
                count.textContent = data.count;
            }
        });
    });
}

async function openDive(diveId) {
    const url = `/dive/${encodeURIComponent(diveId)}`;
    if (window.PelagiaLoading) window.PelagiaLoading.navigate(url);
    else window.location.assign(url);
}

function commentsMarkup(comments) {
    if (!comments.length) {
        return '<p class="muted">No comments yet.</p>';
    }
    return comments
        .map(
            (comment) => {
                const username = escapeHtml(comment.username);
                const author = comment.user_id
                    ? `<a class="username-link" href="/users/${encodeURIComponent(comment.user_id)}">${username}</a>`
                    : username;
                return `
                <div class="comment">
                    <strong>${author}</strong>
                    <p>${escapeHtml(comment.body)}</p>
                </div>
            `;
            },
        )
        .join("");
}

function renderComments(container, comments) {
    if (container) {
        container.innerHTML = commentsMarkup(comments);
    }
}

function initGlobalSearch() {
    const search = document.querySelector("[data-global-search]");
    if (!search) {
        return;
    }
    const input = search.querySelector("[data-global-search-input]");
    const results = search.querySelector("[data-global-search-results]");
    if (!input || !results) {
        return;
    }

    const searchSuggestions = createSuggestionLoader(input, results);
    const selectResult = (item) => {
        if (item?.url) {
            if (window.PelagiaLoading) window.PelagiaLoading.navigate(item.url);
            else window.location.assign(item.url);
        }
    };

    const renderResults = (items) => {
        results.innerHTML = "";
        items.forEach((item) => {
            const button = document.createElement("button");
            button.type = "button";
            button.innerHTML = `<strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail || item.type || "")}</small>`;
            button.addEventListener("click", () => selectResult(item));
            results.appendChild(button);
        });
        results.hidden = !items.length;
    };

    search.addEventListener("submit", (event) => {
        event.preventDefault();
        const firstResult = results.hidden ? null : results.querySelector("button");
        if (firstResult) {
            firstResult.click();
        }
    });

    input.addEventListener(
        "input",
        debounce(async () => {
            const query = input.value.trim();
            if (query.length < 1) {
                hideMenu(results);
                return;
            }
            await searchSuggestions(`/api/search?q=${encodeURIComponent(query)}`, renderResults);
        }, 160),
    );

    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            hideMenu(results);
        }
    });

    document.addEventListener("click", (event) => {
        if (!search.contains(event.target)) {
            hideMenu(results);
        }
    });
}

const formatSacRate = (pressureRate, tankSize = 12) =>
    pressureRate === null || !Number.isFinite(pressureRate)
        ? "-"
        : `${Math.round(pressureRate * tankSize)} L/min`;

function renderSacRate(calculator, pressureRate) {
    const tankSize = Number(calculator.querySelector("[data-tank-size]:checked")?.value || 12);
    calculator.querySelector("[data-sac-output]").textContent = formatSacRate(pressureRate, tankSize);
    calculator.querySelector(".sac-rate-summary")?.classList.toggle("is-unset", pressureRate === null);
}

const FORM_UNITS = {
    length: { metric: "m", alternate: "ft", factor: 1 / 0.3048, offset: 0, step: 1 },
    weight: { metric: "kg", alternate: "lb", factor: 1 / 0.45359237, offset: 0, step: 0.5 },
    pressure: { metric: "bar", alternate: "psi", factor: 1 / (0.45359237 * 9.80665 / 0.0254 ** 2 / 100000), offset: 0, step: 100 },
    temperature: { metric: "c", alternate: "f", factor: 9 / 5, offset: 32, step: 1 },
};

function initGasMix(form) {
    const controls = form.querySelector("[data-gas-mix]");
    if (!controls) return;
    const gases = Object.fromEntries(["oxygen", "helium", "nitrogen"].map((gas) => [gas, {
        range: controls.querySelector(`[data-gas-range='${gas}']`),
        number: controls.querySelector(`[data-gas-number='${gas}']`),
    }]));
    const updateLabel = () => {
        const oxygen = Number(gases.oxygen.number.value);
        const helium = Number(gases.helium.number.value);
        controls.querySelector("[data-gas-mix-label]").textContent = helium > 0
            ? `Trimix ${oxygen}/${helium}` : oxygen === 21 ? "Air" : `EANx ${oxygen}%`;
    };
    updateLabel();
    const render = (gas, value) => {
        gases[gas].range.value = gases[gas].number.value = String(value);
    };
    for (const gas of ["oxygen", "helium"]) {
        const other = gas === "oxygen" ? "helium" : "oxygen";
        const update = (raw) => {
            const value = Number(raw);
            const entered = Math.max(0, Math.min(100, Number.isFinite(value) ? Math.round(value) : 0));
            if (gas === "oxygen" && entered < 21) {
                // Hypoxic oxygen edits replace helium, keeping nitrogen fixed.
                const oxygen = Math.min(entered, Math.max(0, 99 - Number(gases.nitrogen.number.value)));
                render("oxygen", oxygen);
                render("helium", 100 - oxygen - Number(gases.nitrogen.number.value));
            } else {
                const minimum = gas === "helium" && Number(gases.oxygen.number.value) < 21 ? 1 : 0;
                render(gas, Math.max(minimum, Math.min(100 - Number(gases[other].number.value), entered)));
                render("nitrogen", 100 - Number(gases.oxygen.number.value) - Number(gases.helium.number.value));
            }
            updateLabel();
        };
        gases[gas].range.addEventListener("input", () => update(gases[gas].range.value));
        gases[gas].number.addEventListener("input", () => update(gases[gas].number.value));
        gases[gas].number.addEventListener("blur", () => update(gases[gas].number.value));
    }
}

function initDiveForm() {
    const form = document.querySelector("[data-dive-form]");
    if (!form) {
        return;
    }

    const exposureLabel = form.querySelector("[data-exposure-label]");
    form.querySelectorAll("[data-exposure-option]").forEach((input) => {
        input.addEventListener("change", () => {
            if (exposureLabel) exposureLabel.textContent = input.value;
        });
    });

    const waterTypeLabel = form.querySelector("[data-water-type-label]");
    form.querySelectorAll("[data-water-type-option]").forEach((input) => {
        input.addEventListener("change", () => {
            if (waterTypeLabel) waterTypeLabel.textContent = input.dataset.optionLabel;
        });
    });

    const siteInput = form.querySelector("[data-site-input]");
    const siteResults = form.querySelector("[data-site-results]");
    const centerInput = form.querySelector("[data-center-input]");
    const centerResults = form.querySelector("[data-center-results]");
    const buddyInput = form.querySelector("[data-buddy-input]");
    const buddyResults = form.querySelector("[data-buddy-results]");
    const siteId = document.getElementById("diveSiteId");
    const centerId = document.getElementById("diveCenterId");
    const buddyId = document.getElementById("buddyUserId");
    const country = document.getElementById("country");
    const latitude = document.getElementById("latitude");
    const longitude = document.getElementById("longitude");
    const searchSites = createSuggestionLoader(siteInput, siteResults);
    const searchCenters = createSuggestionLoader(centerInput, centerResults);
    let durationTouched = form.dataset.isEdit === "true";

    const pairs = {
        depth: {
            range: form.querySelector("[data-range='depth']"),
            number: form.querySelector("[data-number='depth']"),
            output: document.getElementById("depthOutput"),
            min: 0,
            max: 45,
            step: 1,
            unit: "m",
        },
        averageDepth: {
            range: form.querySelector("[data-range='averageDepth']"),
            number: form.querySelector("[data-number='averageDepth']"),
            output: document.getElementById("averageDepthOutput"),
            min: 0,
            max: 45,
            step: 1,
            unit: "m",
            optional: true,
        },
        duration: {
            range: form.querySelector("[data-range='duration']"),
            number: form.querySelector("[data-number='duration']"),
            output: document.getElementById("durationOutput"),
            min: 0,
            max: 120,
            step: 1,
            unit: "min",
        },
        weight: {
            range: form.querySelector("[data-range='weight']"),
            number: form.querySelector("[data-number='weight']"),
            output: document.getElementById("weightOutput"),
            min: 0,
            max: 10,
            step: 0.5,
            unit: "kg",
            optional: true,
        },
        startingPressure: {
            range: form.querySelector("[data-range='startingPressure']"),
            number: form.querySelector("[data-number='startingPressure']"),
            output: document.getElementById("startingPressureOutput"),
            min: 0,
            max: 300,
            rangeMax: 200,
            step: 10,
            unit: "bar",
            optional: true,
        },
        endingPressure: {
            range: form.querySelector("[data-range='endingPressure']"),
            number: form.querySelector("[data-number='endingPressure']"),
            output: document.getElementById("endingPressureOutput"),
            min: 0,
            max: 300,
            rangeMax: 200,
            step: 10,
            unit: "bar",
            optional: true,
        },
        visibility: {
            range: form.querySelector("[data-range='visibility']"),
            number: form.querySelector("[data-number='visibility']"),
            output: document.getElementById("visibilityOutput"),
            min: 0,
            max: Infinity,
            rangeMax: 30,
            step: 1,
            unit: "m",
            optional: true,
        },
        airTemp: {
            range: form.querySelector("[data-range='airTemp']"),
            number: form.querySelector("[data-number='airTemp']"),
            output: document.getElementById("airTempOutput"),
            min: -20,
            max: 40,
            step: 1,
            unit: "°C",
            compactUnit: true,
            optional: true,
        },
        waterTemp: {
            range: form.querySelector("[data-range='waterTemp']"),
            number: form.querySelector("[data-number='waterTemp']"),
            output: document.getElementById("waterTempOutput"),
            min: -20,
            max: 40,
            step: 1,
            unit: "°C",
            compactUnit: true,
            optional: true,
        },
    };

    const unitGroups = { depth: "length", averageDepth: "length", visibility: "length", weight: "weight",
        startingPressure: "pressure", endingPressure: "pressure", airTemp: "temperature", waterTemp: "temperature" };
    const titles = { depth: "Max depth", averageDepth: "Average depth", visibility: "Visibility", weight: "Weight",
        startingPressure: "Starting pressure", endingPressure: "Ending pressure", airTemp: "Air temperature", waterTemp: "Water temperature" };
    const selectedUnits = Object.fromEntries(Object.entries(FORM_UNITS).map(([group, config]) => [group, config.metric]));
    Object.entries(pairs).forEach(([name, pair]) => {
        pair.name = name;
        pair.group = unitGroups[name];
        pair.title = titles[name];
        pair.metricMin = pair.min;
        pair.metricMax = pair.max;
        pair.metricRangeMax = pair.rangeMax ?? pair.max;
        pair.rangeMax = pair.metricRangeMax;
        pair.metricStep = pair.step;
        pair.metricUnit = pair.unit;
        pair.rangeMetric = Number(pair.range.value);
        pair.label = form.querySelector(`[data-unit-label='${name}']`);
        if (name === "averageDepth") pair.disclosure = form.querySelector("[data-average-depth]");
    });
    const usesAlternate = (pair) => pair.group && selectedUnits[pair.group] === FORM_UNITS[pair.group].alternate;
    const toDisplay = (metric, pair) => usesAlternate(pair) ? metric * FORM_UNITS[pair.group].factor + FORM_UNITS[pair.group].offset : metric;
    const toMetric = (display, pair) => usesAlternate(pair)
        ? Number(((display - FORM_UNITS[pair.group].offset) / FORM_UNITS[pair.group].factor).toFixed(10)) : display;
    const formatMetricValue = (value) => String(Number(value));
    const formatPairOutput = (value, pair) => `${formatMetricValue(value)}${pair.compactUnit ? "" : " "}${pair.unit}`;
    const snapToStep = (value, pair) => clamp(pair.min + Math.round((Number(value) - pair.min) / pair.step) * pair.step, pair.min, pair.rangeMax);
    const displayDigits = (pair) => pair.name === "weight" ? 1 : 0;
    const roundedDisplay = (value, pair) => {
        if (pair.name === "visibility" && usesAlternate(pair)) return Math.round(value / 5) * 5;
        if (pair.group === "pressure") {
            const psiPerBar = FORM_UNITS.pressure.factor;
            if (usesAlternate(pair) && Math.abs(value - 200 * psiPerBar) < 1e-5) return 3000;
            if (!usesAlternate(pair) && Math.abs(value - 3000 / psiPerBar) < 1e-5) return 200;
        }
        const scale = pair.name === "weight" ? 2 : 1;
        return Math.round(value * scale) / scale;
    };

    const renderPair = (pair, normalizeNumber = true) => {
        const alternate = usesAlternate(pair);
        const config = FORM_UNITS[pair.group];
        pair.unit = alternate ? (pair.group === "temperature" ? "°F" : config.alternate) : pair.metricUnit;
        const scale = 10 ** displayDigits(pair);
        pair.min = alternate ? Math.round(toDisplay(pair.metricMin, pair)) : Math.floor(pair.metricMin * scale) / scale;
        pair.max = alternate ? Math.round(toDisplay(pair.metricMax, pair)) : Math.ceil(pair.metricMax * scale) / scale;
        pair.rangeMax = pair.group === "pressure" ? (alternate ? 3000 : pair.metricRangeMax)
            : pair.name === "visibility" ? (alternate ? 100 : pair.metricRangeMax) : pair.max;
        pair.step = pair.name === "visibility" && alternate ? 5 : (alternate ? config.step : pair.metricStep);
        pair.range.min = pair.number.min = String(pair.min);
        pair.range.max = String(pair.rangeMax);
        pair.number.max = Number.isFinite(pair.max) ? String(pair.max) : "";
        pair.range.step = String(pair.step);
        if (pair.group) {
            pair.number.step = pair.group === "pressure" && (alternate || Number.isInteger(pair.metricValue)) ? "1" : "any";
            pair.range.setAttribute("aria-label", `${pair.title}${pair.group === "pressure" ? "" : " slider"} (${pair.unit})`);
            if (pair.label) pair.label.textContent = `${pair.title} (${pair.unit})`;
        }
        const metric = pair.metricValue ?? pair.rangeMetric;
        const display = toDisplay(metric, pair);
        pair.range.value = snapToStep(roundedDisplay(display, pair), pair);
        if (pair.metricValue === null) {
            pair.number.value = "";
            pair.output.textContent = "-";
        } else {
            const visible = normalizeNumber ? roundedDisplay(display, pair) : Number(pair.number.value);
            if (normalizeNumber) pair.number.value = formatMetricValue(visible);
            pair.output.textContent = formatPairOutput(roundedDisplay(visible, pair), pair);
        }
        pair.displayRaw = pair.number.value;
        pair.disclosure?.classList.toggle("is-unset", pair.metricValue === null);
    };

    const updateSacRate = () => {
        const values = ["depth", "averageDepth", "duration", "startingPressure", "endingPressure"].map((name) => pairs[name].metricValue ?? null);
        const [maxDepth, averageDepth, duration, start, end] = values;
        const depth = averageDepth ?? maxDepth;
        // Keep the pressure track and calculated-value styling in sync with inputs.
        const pressureTrack = form.querySelector(".pressure-slider");
        const positions = [pairs.startingPressure, pairs.endingPressure].map((pair) =>
            (1 - Number(pair.range.value) / pair.rangeMax) * 100,
        );
        pressureTrack?.style.setProperty("--pressure-low", `${Math.min(...positions)}%`);
        pressureTrack?.style.setProperty("--pressure-high", `${Math.max(...positions)}%`);
        pressureTrack?.classList.toggle("has-pressure-values", start !== null && end !== null);
        const pressureRate = [depth, duration, start, end].includes(null) || duration <= 0
            ? null
            : (start - end) / duration / (depth / 10 + 1);
        renderSacRate(form.querySelector("[data-sac-calculator]"), pressureRate);
    };

    const setPair = (name, value, fromUser = false, options = {}) => {
        const pair = pairs[name];
        const source = options.source || "auto";
        const commit = Boolean(options.commit);
        const rawValue = String(value ?? "").trim();
        if (!rawValue && pair.optional) {
            pair.metricValue = null;
            pair.number.value = "";
            pair.output.textContent = "-";
            pair.displayRaw = "";
            pair.disclosure?.classList.toggle("is-unset", true);
            updateSacRate();
            return null;
        }
        const parsed = Number(rawValue);
        if (!Number.isFinite(parsed)) {
            if (commit) {
                const fallback = clamp(pair.range.value, pair.min, pair.max);
                pair.metricValue = clamp(toMetric(fallback, pair), pair.metricMin, pair.metricMax);
                renderPair(pair);
            }
            updateSacRate();
            return null;
        }

        const exact = source === "auto" ? parsed : clamp(parsed, pair.min, pair.max);
        const displayValue = source === "slider" ? snapToStep(exact, pair) : exact;
        // Preserve the exact measurement when blur or a unit switch follows a
        // rounded display. User edits replace it with the newly entered value.
        const metric = source === "number" && commit && rawValue === pair.displayRaw && pair.metricValue !== null
            ? pair.metricValue : source === "auto" ? parsed : toMetric(displayValue, pair);
        pair.metricValue = clamp(metric, pair.metricMin, pair.metricMax);
        pair.rangeMetric = pair.metricValue;
        if (source === "number" && (commit || exact !== parsed)) pair.number.value = formatMetricValue(displayValue);
        renderPair(pair, source !== "number" || commit);
        if (name === "duration" && fromUser) {
            durationTouched = true;
        }
        if (name === "depth" && !durationTouched) {
            setPair("duration", suggestedDuration(pair.metricValue), false, { commit: true });
        }
        updateSacRate();
        return pair.metricValue;
    };

    Object.entries(pairs).forEach(([name, pair]) => {
        pair.range.addEventListener("input", () => setPair(name, pair.range.value, true, { source: "slider", commit: true }));
        pair.number.addEventListener("input", () => setPair(name, pair.number.value, true, { source: "number" }));
        pair.number.addEventListener("blur", () => setPair(name, pair.number.value, true, { source: "number", commit: true }));
        setPair(name, pair.number.dataset.metricValue || pair.number.value, false, { commit: true });
    });
    const applyUnit = (input) => {
        if (!input.checked) return;
        const group = input.dataset.unitToggle;
        if (selectedUnits[group] === input.value) return;
        selectedUnits[group] = input.value;
        Object.values(pairs).filter((pair) => pair.group === group).forEach((pair) => renderPair(pair));
        if (group === "pressure") {
            form.querySelectorAll("[data-pressure-unit]").forEach((label) => { label.textContent = input.value; });
        }
        updateSacRate();
    };
    form.querySelectorAll("[data-unit-toggle]").forEach((input) => {
        input.addEventListener("change", () => applyUnit(input));
        applyUnit(input);
    });
    // Serialize full precision in the chosen units after browser validation,
    // leaving the visible inputs unchanged. The server converts these on save.
    form.addEventListener("formdata", (event) => {
        Object.values(pairs).filter((pair) => pair.group).forEach((pair) => {
            event.formData.set(pair.number.name, pair.metricValue === null ? "" : formatMetricValue(toDisplay(pair.metricValue, pair)));
        });
    });
    form.querySelectorAll("[data-tank-size]").forEach((input) => input.addEventListener("change", updateSacRate));
    initMultiSelects(form);
    initCurrentStrengthSlider(form);

    siteInput.addEventListener(
        "input",
        debounce(async () => {
            siteId.value = "";
            const query = siteInput.value.trim();
            if (query.length < 2) {
                hideMenu(siteResults);
                return;
            }
            await searchSites(`/api/sites?q=${encodeURIComponent(query)}`, renderSiteResults);
        }, 160),
    );

    centerInput.addEventListener(
        "input",
        debounce(async () => {
            centerId.value = "";
            const query = centerInput.value.trim();
            if (query.length < 2) {
                hideMenu(centerResults);
                return;
            }
            await searchCenters(`/api/dive-centers?q=${encodeURIComponent(query)}`, renderCenterResults);
        }, 160),
    );

    country.addEventListener(
        "input",
        debounce(() => loadSpeciesSuggestions({ country: country.value.trim() }), 260),
    );

    function renderSiteResults(sites) {
        if (!sites.length) {
            hideMenu(siteResults);
            return;
        }
        siteResults.innerHTML = "";
        sites.forEach((site) => {
            const button = document.createElement("button");
            button.type = "button";
            button.innerHTML = `<strong>${escapeHtml(site.name)}</strong><small>${escapeHtml(site.country_or_area || "")}</small>`;
            button.addEventListener("click", () => selectSite(site));
            siteResults.appendChild(button);
        });
        siteResults.hidden = false;
    }

    function selectSite(site) {
        siteInput.value = site.name;
        siteId.value = site.id;
        country.value = site.country_or_area || "";
        latitude.value = site.latitude ?? "";
        longitude.value = site.longitude ?? "";
        if (site.max_depth_m !== null && site.max_depth_m !== undefined) {
            setPair("depth", site.max_depth_m, false);
            setPair("duration", suggestedDuration(site.max_depth_m), false);
        }
        hideMenu(siteResults);
        loadSpeciesSuggestions({ siteId: site.id, country: site.country_or_area });
    }

    function renderCenterResults(centers) {
        if (!centers.length) {
            hideMenu(centerResults);
            return;
        }
        centerResults.innerHTML = "";
        centers.forEach((center) => {
            const button = document.createElement("button");
            button.type = "button";
            button.innerHTML = `<strong>${escapeHtml(center.name)}</strong><small>${escapeHtml(center.location || center.physical_address || "")}</small>`;
            button.addEventListener("click", () => selectCenter(center));
            centerResults.appendChild(button);
        });
        centerResults.hidden = false;
    }

    function selectCenter(center) {
        centerInput.value = center.name;
        centerId.value = center.id;
        hideMenu(centerResults);
    }

    initSpeciesPicker(form, () => country.value.trim());
    initBuddyAutocomplete({ input: buddyInput, results: buddyResults, hidden: buddyId });
    initPhotoPreview(form);
    initPhotoRemoval(form);
    initArrowNavigation(form);
}

function suggestedDuration(depthM) {
    return clamp(Math.round((120 - Number(depthM) * 3.28084) / 5) * 5, 0, 120);
}

function initBuddyAutocomplete({ input, results, hidden }) {
    if (!input || !results || !hidden) {
        return;
    }
    const searchUsers = createSuggestionLoader(input, results);

    hidden.dataset.selectedUsername = hidden.value ? input.value.trim() : "";

    const setValidity = () => {
        const query = input.value.trim();
        const selectedUsername = hidden.dataset.selectedUsername || "";
        const valid = !query || (hidden.value && selectedUsername.toLowerCase() === query.toLowerCase());
        input.setCustomValidity(valid ? "" : "Choose a buddy from autocomplete.");
        return valid;
    };

    const selectUser = (user) => {
        input.value = user.username;
        hidden.value = user.id;
        hidden.dataset.selectedUsername = user.username;
        setValidity();
        hideMenu(results);
    };

    const renderUsers = (users) => {
        results.innerHTML = "";
        users.forEach((user) => {
            const button = document.createElement("button");
            button.type = "button";
            button.innerHTML = `<strong>${escapeHtml(user.username)}</strong><small>Account</small>`;
            button.addEventListener("click", () => selectUser(user));
            results.appendChild(button);
        });
        results.hidden = !users.length;
    };

    input.addEventListener("input", () => {
        hidden.value = "";
        hidden.dataset.selectedUsername = "";
        setValidity();
    });

    input.addEventListener(
        "input",
        debounce(async () => {
            const query = input.value.trim();
            if (query.length < 1) {
                hideMenu(results);
                return;
            }
            await searchUsers(`/api/users?q=${encodeURIComponent(query)}`, renderUsers);
        }, 160),
    );

    input.addEventListener("blur", setValidity);

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && input.value.trim()) {
            const firstResult = results.hidden ? null : results.querySelector("button");
            if (firstResult) {
                event.preventDefault();
                firstResult.click();
            }
        } else if (event.key === "Escape") {
            hideMenu(results);
        }
    });

    input.form?.addEventListener("submit", (event) => {
        if (event.submitter?.formNoValidate) {
            return;
        }
        if (!setValidity()) {
            event.preventDefault();
            input.reportValidity();
        }
    });

    document.addEventListener("click", (event) => {
        if (!input.closest(".autocomplete-field")?.contains(event.target)) {
            hideMenu(results);
        }
    });

    setValidity();
}

function initMultiSelects(form) {
    const controls = Array.from(form.querySelectorAll("[data-multi-select]"));
    controls.forEach((control) => {
        const inputs = Array.from(control.querySelectorAll("input[type='checkbox']"));
        const summary = control.querySelector("[data-multi-select-summary]");
        const refresh = (changed) => {
            const exclusive = inputs.find((input) => input.value === control.dataset.exclusive);
            if (exclusive) {
                if (changed === exclusive && exclusive.checked) {
                    inputs.forEach((input) => { input.checked = input === exclusive; });
                } else if (inputs.some((input) => input !== exclusive && input.checked)) {
                    exclusive.checked = false;
                }
            }
            if (!inputs.some((input) => input.checked)) {
                const fallback = inputs.find((input) => input.value === control.dataset.default);
                if (fallback) fallback.checked = true;
            }
            summary.textContent = inputs.filter((input) => input.checked).map((input) => input.dataset.optionLabel).join(", ");
        };
        // Listen on the container so normalization precedes current-strength updates.
        control.addEventListener("change", (event) => refresh(event.target));
        control.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                control.open = false;
                control.querySelector("summary").focus();
            }
        });
        refresh();
    });
    document.addEventListener("click", (event) => {
        controls.forEach((control) => {
            if (!control.contains(event.target)) control.open = false;
        });
    });
}

function initCurrentStrengthSlider(form) {
    const currentType = form.querySelector("[data-current-type-select]");
    const range = form.querySelector("[data-current-strength-range]");
    const hidden = form.querySelector("[data-current-strength-value]");
    const output = document.getElementById("currentStrengthOutput");
    if (!range || !hidden || !output) {
        return;
    }

    const indexForValue = (value) => CURRENT_STRENGTHS.findIndex((item) => item.value === value);
    const setStrength = (rawIndex) => {
        const index = clamp(Math.round(Number(rawIndex)), 0, CURRENT_STRENGTHS.length - 1);
        const strength = CURRENT_STRENGTHS[index];
        range.value = index;
        hidden.value = strength.value;
        output.textContent = strength.label;
    };
    const setAvailability = () => {
        const isNone = !Array.from(currentType?.querySelectorAll("input[type='checkbox']:checked") || [])
            .some((input) => input.value !== "none");
        if (isNone) {
            setStrength(0);
        }
        range.disabled = isNone;
        range.closest(".current-strength-control")?.classList.toggle("is-disabled", isNone);
    };

    const initialIndex = indexForValue(hidden.value);
    setStrength(initialIndex >= 0 ? initialIndex : range.value);
    setAvailability();
    currentType?.addEventListener("change", setAvailability);
    range.addEventListener("input", () => {
        if (!range.disabled) {
            setStrength(range.value);
        }
    });
}

function hideMenu(menu) {
    if (!menu) {
        return;
    }
    cancelSuggestionLoad(menu);
    menu.hidden = true;
    menu.innerHTML = "";
}

function initSpeciesPicker(form, getCountry) {
    const input = form.querySelector("[data-species-input]");
    const results = form.querySelector("[data-species-results]");
    const suggestions = form.querySelector("[data-species-suggestions]");
    const tags = form.querySelector("[data-species-tags]");
    const hidden = document.getElementById("speciesJson");
    const searchSpecies = createSuggestionLoader(input, results);
    let selected = [];
    try {
        const preloaded = JSON.parse(hidden.value || "[]");
        selected = Array.isArray(preloaded) ? preloaded.map((name) => String(name).trim()).filter(Boolean) : [];
    } catch (_error) {
        selected = [];
    }

    window.loadSpeciesSuggestions = async ({ siteId, country }) => {
        const params = new URLSearchParams();
        if (siteId) {
            params.set("site_id", siteId);
        } else if (country) {
            params.set("country", country);
        } else {
            cancelSuggestionLoad(suggestions);
            suggestions.innerHTML = "";
            return;
        }
        await loadSuggestionRegion(suggestions, `/api/species-suggestions?${params.toString()}`, (names) => {
            suggestions.hidden = false;
            suggestions.innerHTML = "";
            names.forEach((name) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "suggestion-pill";
                button.textContent = name;
                button.addEventListener("click", () => {
                    addSpecies(name);
                    button.classList.add("is-selected");
                });
                suggestions.appendChild(button);
            });
        });
    };

    input.addEventListener(
        "input",
        debounce(async () => {
            const query = input.value.trim();
            if (query.length < 2) {
                hideMenu(results);
                return;
            }
            const params = new URLSearchParams({ q: query });
            const country = getCountry();
            if (country) {
                params.set("country", country);
            }
            await searchSpecies(`/api/species?${params.toString()}`, (species) => {
                results.innerHTML = "";
                species.forEach((item) => {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.innerHTML = `<strong>${escapeHtml(item.common_name)}</strong><small>${escapeHtml(item.country_or_area || "")}</small>`;
                    button.addEventListener("click", () => {
                        addSpecies(item.common_name);
                        input.value = "";
                        hideMenu(results);
                    });
                    results.appendChild(button);
                });
                results.hidden = !species.length;
            });
        }, 160),
    );

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && input.value.trim()) {
            event.preventDefault();
            const firstResult = results.hidden ? null : results.querySelector("button");
            if (firstResult) {
                firstResult.click();
            }
        }
    });

    function addSpecies(name) {
        const clean = String(name || "").trim();
        if (!clean || selected.some((item) => item.toLowerCase() === clean.toLowerCase())) {
            return;
        }
        selected.push(clean);
        renderTags();
    }

    function renderTags() {
        tags.innerHTML = "";
        selected.forEach((name, index) => {
            const tag = document.createElement("span");
            tag.className = "tag";
            tag.innerHTML = `${escapeHtml(name)} <button type="button" aria-label="Remove ${escapeHtml(name)}">&times;</button>`;
            tag.querySelector("button").addEventListener("click", () => {
                selected.splice(index, 1);
                renderTags();
            });
            tags.appendChild(tag);
        });
        hidden.value = JSON.stringify(selected);
    }

    renderTags();
    window.loadSpeciesSuggestions({
        siteId: document.getElementById("diveSiteId")?.value,
        country: getCountry(),
    });
}

function initPhotoPreview(form) {
    const input = form.querySelector("[data-photo-input]");
    const preview = form.querySelector("[data-photo-preview]");
    if (!input || !preview) {
        return;
    }
    input.addEventListener("change", () => {
        preview.innerHTML = "";
        Array.from(input.files || []).slice(0, 8).forEach((file) => {
            const img = document.createElement("img");
            img.src = URL.createObjectURL(file);
            img.alt = "";
            preview.appendChild(img);
        });
    });
}

function initPhotoRemoval(form) {
    form.querySelectorAll("[data-remove-photo-id]").forEach((button) => {
        button.addEventListener("click", () => {
            const photoId = button.dataset.removePhotoId;
            const alreadyRemoved = Array.from(form.querySelectorAll("input[name='remove_photo_ids']")).some((input) => input.value === photoId);
            if (!photoId || alreadyRemoved) {
                return;
            }
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = "remove_photo_ids";
            hidden.value = photoId;
            form.appendChild(hidden);
            button.closest("[data-existing-photo]")?.remove();
        });
    });
}

function initArrowNavigation(form) {
    const selector = "input:not([type='hidden']), select, textarea, button";
    form.addEventListener("keydown", (event) => {
        if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(event.key)) {
            return;
        }
        if (event.target.matches("input[type='range'], input[type='radio']")) {
            return;
        }
        const textLike = event.target.matches("input[type='text'], input[type='date'], textarea");
        if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && textLike) {
            return;
        }
        const fields = Array.from(form.querySelectorAll(selector)).filter((field) => !field.disabled && field.offsetParent !== null);
        const index = fields.indexOf(event.target);
        if (index === -1) {
            return;
        }
        const direction = event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1;
        const next = fields[index + direction];
        if (next) {
            event.preventDefault();
            next.focus();
        }
    });
}

function initCertificationPicker(picker) {
    const form = picker.querySelector("form");
    const input = picker.querySelector("[data-certification-input]");
    const hidden = picker.querySelector("[data-certification-value]");
    const results = picker.querySelector("[data-certification-results]");
    const status = picker.querySelector("[data-certification-status]");
    let options = [];
    let active = -1;
    let requestId = 0;
    let selected = false;
    let endLoading = () => {};
    const close = () => {
        endLoading();
        results.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    };
    const choose = (option) => {
        hidden.value = String(option.id);
        selected = true;
        close();
        form.requestSubmit();
    };
    const search = async () => {
        const id = ++requestId;
        endLoading();
        results.replaceChildren();
        results.hidden = true;
        input.setAttribute("aria-expanded", "false");
        const finish = window.PelagiaLoading?.begin(results, "Loading certifications", undefined, { reveal: true }) || (() => {});
        endLoading = finish;
        try {
            const matches = await fetchJson(`/api/certifications?${new URLSearchParams({ q: input.value.trim() })}`);
            if (id !== requestId || !picker.open) return;
            options = matches;
            active = -1;
            input.removeAttribute("aria-activedescendant");
            results.replaceChildren();
            options.forEach((option, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.id = `certification-option-${option.id}`;
                button.setAttribute("role", "option");
                button.setAttribute("aria-selected", "false");
                button.tabIndex = -1;
                button.textContent = option.name;
                button.addEventListener("click", () => choose(option));
                results.appendChild(button);
            });
            results.hidden = options.length === 0;
            input.setAttribute("aria-expanded", String(options.length > 0));
            status.textContent = options.length ? "Choose a certification from the suggestions." : "No matching certifications. Try another search.";
        } catch (_error) {
            if (id !== requestId) return;
            close();
            status.textContent = "Couldn’t load certifications. Type to try again.";
        } finally {
            finish();
        }
    };
    picker.addEventListener("toggle", () => {
        if (picker.open) input.focus();
        else { requestId += 1; close(); }
    });
    input.addEventListener("focus", search);
    input.addEventListener("input", () => {
        hidden.value = "";
        selected = false;
        requestId += 1;
        close();
        queueSearch();
    });
    const queueSearch = debounce(search, 120);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { event.preventDefault(); picker.open = false; picker.querySelector("summary").focus(); return; }
        if (event.key === "Enter") {
            event.preventDefault();
            if (!results.hidden && active >= 0) choose(options[active]);
            return;
        }
        if (!["ArrowDown", "ArrowUp"].includes(event.key) || results.hidden) return;
        event.preventDefault();
        active = event.key === "ArrowDown" ? (active + 1) % options.length : (active <= 0 ? options.length - 1 : active - 1);
        Array.from(results.children).forEach((button, index) => button.setAttribute("aria-selected", String(index === active)));
        input.setAttribute("aria-activedescendant", results.children[active].id);
        results.children[active].scrollIntoView({ block: "nearest" });
    });
    form.addEventListener("submit", (event) => {
        if (!selected) { event.preventDefault(); status.textContent = "Choose a certification from the suggestions."; }
    });
    document.addEventListener("click", (event) => {
        if (!picker.contains(event.target)) { picker.open = false; close(); }
    });
}

function initUserProfile() {
    document.querySelectorAll("[data-certification-picker]").forEach(initCertificationPicker);
    const bioForm = document.querySelector("[data-bio-form]");
    const edit = document.querySelector("[data-bio-edit]");
    if (bioForm && edit) {
        edit.setAttribute("aria-expanded", "false");
        edit.addEventListener("click", () => {
            bioForm.hidden = !bioForm.hidden;
            edit.setAttribute("aria-expanded", String(!bioForm.hidden));
            if (!bioForm.hidden) bioForm.querySelector("textarea").focus();
        });
        bioForm.querySelector("[data-bio-cancel]").addEventListener("click", () => {
            bioForm.reset();
            bioForm.hidden = true;
            edit.setAttribute("aria-expanded", "false");
            edit.focus();
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initInteractionFocus();
    initDiveBrief();
    initDiveBriefSharing();
    initDiveSharing();
    initDiveInteractions();
    initGlobalSearch();
    initDiveForm();
    const diveForm = document.querySelector("[data-dive-form]");
    if (diveForm) initGasMix(diveForm);
    initStaticMaps(document);
    initUserProfile();
    initProfileHistory();
    initSiteDescription();
});

window.openDive = openDive;

function initSiteDescription() {
    const host = document.querySelector("[data-site-description]");
    if (!host) return;
    const controller = new AbortController();
    const markup = '<span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span>';
    const finishLoading = window.PelagiaLoading?.begin(host, "Loading dive site description", markup, { reveal: true }) || (() => {});
    let stopped = false;
    let pollTimer;
    const stop = () => {
        if (stopped) return;
        stopped = true;
        controller.abort();
        window.clearTimeout(pollTimer);
        window.clearTimeout(deadline);
        window.removeEventListener("pagehide", stop);
        finishLoading();
        host.remove();
    };
    const deadline = window.setTimeout(stop, 35000);
    window.addEventListener("pagehide", stop, { once: true });

    async function load() {
        try {
            const response = await fetch(host.dataset.descriptionUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-Requested-With": "fetch" },
                cache: "no-store",
                signal: controller.signal,
            });
            if (stopped) return;
            if (response.status === 202) {
                pollTimer = window.setTimeout(load, 2000);
                return;
            }
            if (!response.ok) throw new Error("Description unavailable");
            const result = await response.json();
            if (stopped) return;
            if (result.status !== "complete" || typeof result.description !== "string" || !Array.isArray(result.fragments)) {
                stop();
                return;
            }
            const paragraph = document.createElement("p");
            result.fragments.forEach((fragment) => {
                if (typeof fragment.text !== "string") throw new Error("Invalid description");
                if (fragment.url) {
                    const source = new URL(fragment.url);
                    if (!["https:", "http:"].includes(source.protocol) || source.username || source.password) {
                        throw new Error("Invalid source");
                    }
                    const link = document.createElement("a");
                    link.className = "site-description-source";
                    link.href = source.href;
                    link.textContent = fragment.text;
                    link.title = fragment.title || "Source";
                    link.setAttribute("aria-label", `Source ${fragment.text}: ${link.title}`);
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    paragraph.appendChild(link);
                } else paragraph.appendChild(document.createTextNode(fragment.text));
            });
            stopped = true;
            window.clearTimeout(deadline);
            window.removeEventListener("pagehide", stop);
            finishLoading();
            host.replaceChildren(paragraph);
            host.hidden = false;
            host.removeAttribute("data-site-description");
        } catch (_error) {
            stop();
        }
    }
    load();
}

function initInteractionFocus() {
    const root = document.documentElement;
    root.dataset.inputModality = "pointer";
    const pointer = () => { root.dataset.inputModality = "pointer"; };
    document.addEventListener("pointerdown", pointer, true);
    document.addEventListener("touchstart", pointer, { capture: true, passive: true });
    document.addEventListener("keydown", (event) => {
        if (!event.metaKey && !event.ctrlKey && !event.altKey) root.dataset.inputModality = "keyboard";
    }, true);
}

function initDiveBrief() {
    const reader = document.querySelector("[data-brief-reader]");
    if (!reader || reader.dataset.briefPublic === "true") return;
    const dialog = document.querySelector("[data-brief-dialog]");
    const trigger = document.querySelector("[data-brief-open]");
    const disclosure = document.querySelector("[data-brief-disclosure]");
    const summary = document.querySelector("[data-brief-toggle]");
    const collapseCard = () => {
        if (disclosure) disclosure.open = false;
    };
    collapseCard();
    const scroller = reader.querySelector("[data-brief-scroll]");
    const heading = reader.querySelector("[data-brief-heading]");
    const feedTitle = document.title;
    let returnFocus;
    let feedUrl;
    let feedScroll;
    let previousBodyTop;
    let closing = false;
    const lockFeed = () => {
        if (feedScroll) return;
        feedScroll = { x: window.scrollX, y: window.scrollY };
        previousBodyTop = document.body.style.top;
        document.body.style.top = `-${feedScroll.y}px`;
        document.body.classList.add("brief-is-open");
    };
    const unlockFeed = () => {
        document.body.classList.remove("brief-is-open");
        if (!feedScroll) return;
        document.body.style.top = previousBodyTop;
        window.scrollTo({ left: feedScroll.x, top: feedScroll.y, behavior: "instant" });
        feedScroll = null;
    };
    const showReader = () => {
        lockFeed();
        dialog.showModal();
        trigger.setAttribute("aria-expanded", "true");
        document.title = `${heading.textContent} · Pelagia`;
        heading.focus({ preventScroll: true });
    };
    const restoreFeed = () => {
        if (!dialog?.open) return;
        dialog.close();
        // Change the card height while the feed is still fixed, so scroll
        // anchoring cannot move the page during focus and position restoration.
        collapseCard();
        unlockFeed();
        document.title = feedTitle;
        trigger?.setAttribute("aria-expanded", "false");
        (summary || returnFocus)?.focus({ preventScroll: true });
        closing = false;
    };
    const close = () => {
        if (closing) return;
        if (!dialog) {
            closing = true;
            collapseCard();
            if (window.history.state?.pelagiaBrief) window.history.back();
            else window.location.assign("/home");
            return;
        }
        if (!dialog.open) return;
        closing = true;
        // One history entry belongs to this reader. Back restores feed scroll.
        if (window.history.state?.pelagiaBrief) window.history.back();
        else restoreFeed();
    };
    if (!dialog) {
        // Reloading a pushed reader URL can leave the feed history entry bound
        // to this document. Fetch the feed when Back changes only its URL.
        window.addEventListener("popstate", () => {
            if (window.location.pathname === "/home") {
                collapseCard();
                window.location.replace("/home");
            }
        });
    }
    if (dialog && trigger && typeof dialog.showModal === "function") {
        trigger.setAttribute("aria-expanded", "false");
        trigger.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
            event.preventDefault();
            if (dialog.open) return;
            returnFocus = trigger;
            feedUrl = window.location.href;
            window.history.pushState({ pelagiaBrief: true }, "", trigger.href);
            showReader();
            scroller.scrollTop = 0;
        });
        dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            close();
        });
        window.addEventListener("popstate", () => {
            if (window.history.state?.pelagiaBrief) {
                if (!dialog.open) {
                    showReader();
                }
            } else restoreFeed();
        });
        // A restored bfcache snapshot must not leave a hidden feed scroll-locked.
        window.addEventListener("pageshow", () => {
            if (dialog.open && !window.history.state?.pelagiaBrief) restoreFeed();
            if (!dialog.open) {
                unlockFeed();
                collapseCard();
            }
        });
        dialog.addEventListener("close", () => {
            // Native close events are queued and can arrive after Forward has
            // reopened the reader. Ignore a stale event from the previous visit.
            if (dialog.open) return;
            unlockFeed();
            document.title = feedTitle;
            trigger.setAttribute("aria-expanded", "false");
            if (window.history.state?.pelagiaBrief && feedUrl) {
                window.history.replaceState(null, "", feedUrl);
            }
        });
    }
    reader.querySelectorAll("[data-brief-close]").forEach((link) => {
        link.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
            event.preventDefault();
            close();
        });
    });
    reader.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !dialog) close();
    });
}

function initDiveBriefSharing() {
    const reader = document.querySelector("[data-brief-reader]");
    const share = reader?.querySelector("[data-brief-share]");
    if (!share) return;
    const status = reader.querySelector("[data-brief-share-status]");
    const fallback = reader.querySelector("[data-brief-share-fallback]");
    const link = reader.querySelector("[data-brief-share-link]");
    let sharing = false;
    share.addEventListener("click", async (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
        event.preventDefault();
        if (sharing) return;
        sharing = true;
        share.setAttribute("aria-busy", "true");
        status.textContent = "";
        fallback.hidden = true;
        try {
            if (window.isSecureContext && typeof navigator.share === "function") {
                try {
                    await navigator.share({ title: share.dataset.shareTitle, url: share.href });
                    status.textContent = "Brief shared.";
                    return;
                } catch (error) {
                    if (error.name === "AbortError") return;
                }
            }
            try {
                if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
                await navigator.clipboard.writeText(share.href);
                status.textContent = "Link copied. Anyone can read this brief.";
            } catch (error) {
                fallback.hidden = false;
                link.focus();
                link.select();
                link.setSelectionRange(0, link.value.length);
                status.textContent = "Copy this link to share the brief. Anyone can read it.";
            }
        } finally {
            sharing = false;
            share.removeAttribute("aria-busy");
        }
    });
}

function initProfileHistory() {
    document.querySelectorAll("[data-profile-history]").forEach((section) => {
        section.querySelectorAll("[data-history-option]").forEach((button) => {
            button.addEventListener("click", () => {
                section.querySelectorAll("[data-history-option]").forEach((option) => {
                    option.setAttribute("aria-pressed", String(option === button));
                });
                section.querySelectorAll("[data-history-view]").forEach((view) => {
                    view.hidden = view.dataset.historyView !== button.dataset.historyOption;
                });
            });
        });
    });
}
