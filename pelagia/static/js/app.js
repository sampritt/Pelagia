const clamp = (value, min, max) => Math.max(min, Math.min(max, Number(value) || 0));

const escapeHtml = (value) =>
    String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

const coordinateToPoint = (lat, lon) => ({
    x: clamp(((Number(lon) + 180) / 360) * 100, 0, 100),
    y: clamp(((90 - Number(lat)) / 180) * 100, 0, 100),
});

const MAP_TILE_SIZE = 256;
const MAP_MIN_ZOOM = 2;
const MAP_MAX_ZOOM = 16;
const MAP_STATIC_ZOOM = 10;
const MAP_TILE_SUBDOMAINS = ["a", "b", "c", "d"];

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

function worldPointToLatLng(point, zoom) {
    const worldSize = worldSizeAtZoom(zoom);
    const lng = (point.x / worldSize) * 360 - 180;
    const n = Math.PI - (2 * Math.PI * point.y) / worldSize;
    const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
    return { lat, lng: normalizeLng(lng) };
}

function wrapTileX(tileX, zoom) {
    const count = 2 ** zoom;
    return ((tileX % count) + count) % count;
}

function mapTileUrl(zoom, tileX, tileY) {
    const subdomain = MAP_TILE_SUBDOMAINS[Math.abs(tileX + tileY) % MAP_TILE_SUBDOMAINS.length];
    return `https://${subdomain}.basemaps.cartocdn.com/dark_all/${zoom}/${wrapTileX(tileX, zoom)}/${tileY}.png`;
}

function fallbackMapTileUrl(zoom, tileX, tileY) {
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

function ensureAttribution(container) {
    if (container.querySelector(".map-attribution")) {
        return;
    }
    const attribution = document.createElement("span");
    attribution.className = "map-attribution";
    attribution.innerHTML = "&copy; OpenStreetMap &copy; CARTO";
    container.appendChild(attribution);
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
                if (img.dataset.fallbackTile) {
                    img.classList.add("tile-error");
                    return;
                }
                img.dataset.fallbackTile = "true";
                img.src = fallbackMapTileUrl(zoom, tileX, tileY);
            });
            img.style.left = `${Math.round(tileX * MAP_TILE_SIZE - originX)}px`;
            img.style.top = `${Math.round(tileY * MAP_TILE_SIZE - originY)}px`;
            fragment.appendChild(img);
        }
    }

    layer.replaceChildren(fragment);
    return { originX, originY };
}

function fitMarkers(markers, { width, height, padding = 40, maxZoom = MAP_MAX_ZOOM, singleZoom = MAP_STATIC_ZOOM } = {}) {
    const valid = markers.filter((marker) => isValidLatLng(marker.latitude, marker.longitude));
    if (!valid.length) {
        return { zoom: MAP_MIN_ZOOM, centerPoint: latLngToWorldPoint(15, 0, MAP_MIN_ZOOM) };
    }
    if (valid.length === 1) {
        const zoom = Math.min(maxZoom, singleZoom);
        return { zoom, centerPoint: latLngToWorldPoint(valid[0].latitude, valid[0].longitude, zoom) };
    }

    const availableWidth = Math.max(120, width - padding * 2);
    const availableHeight = Math.max(120, height - padding * 2);
    for (let zoom = maxZoom; zoom >= MAP_MIN_ZOOM; zoom -= 1) {
        const points = valid.map((marker) => latLngToWorldPoint(marker.latitude, marker.longitude, zoom));
        const xs = points.map((point) => point.x);
        const ys = points.map((point) => point.y);
        const bounds = {
            minX: Math.min(...xs),
            maxX: Math.max(...xs),
            minY: Math.min(...ys),
            maxY: Math.max(...ys),
        };
        if (bounds.maxX - bounds.minX <= availableWidth && bounds.maxY - bounds.minY <= availableHeight) {
            return {
                zoom,
                centerPoint: {
                    x: (bounds.minX + bounds.maxX) / 2,
                    y: (bounds.minY + bounds.maxY) / 2,
                },
            };
        }
    }

    const zoom = MAP_MIN_ZOOM;
    const points = valid.map((marker) => latLngToWorldPoint(marker.latitude, marker.longitude, zoom));
    return {
        zoom,
        centerPoint: {
            x: (Math.min(...points.map((point) => point.x)) + Math.max(...points.map((point) => point.x))) / 2,
            y: (Math.min(...points.map((point) => point.y)) + Math.max(...points.map((point) => point.y))) / 2,
        },
    };
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
    ensureAttribution(map);
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
        ...options,
    });
    if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
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

        if (event.target.closest("[data-close-modal]")) {
            closeDiveModal();
        }

        const centerLikeButton = event.target.closest("[data-center-like]");
        if (centerLikeButton) {
            event.preventDefault();
            await toggleCenterLike(centerLikeButton.dataset.centerId);
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeDiveModal();
        }
        if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-dive-card]")) {
            event.preventDefault();
            openDive(event.target.dataset.diveId);
        }
    });

    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("[data-comment-form]");
        const centerForm = event.target.closest("[data-center-comment-form]");
        if (!form && !centerForm) {
            return;
        }
        event.preventDefault();
        const input = (form || centerForm).querySelector("input[name='body']");
        const body = input.value.trim();
        if (!body) {
            return;
        }
        if (centerForm) {
            const data = await fetchJson(`/api/dive-centers/${centerForm.dataset.centerId}/comments`, {
                method: "POST",
                body: new FormData(centerForm),
            });
            input.value = "";
            renderComments(document.querySelector("[data-center-comments]"), data.comments);
            return;
        }
        const data = await fetchJson(`/api/dives/${form.dataset.diveId}/comments`, {
            method: "POST",
            body: new FormData(form),
        });
        input.value = "";
        renderComments(form.closest(".modal-content").querySelector("[data-comments]"), data.comments);
        document.querySelectorAll(`[data-open-dive='${form.dataset.diveId}'] span:last-child`).forEach((span) => {
            span.textContent = data.comments.length;
        });
    });

    const params = new URLSearchParams(window.location.search);
    if (params.has("open")) {
        openDive(params.get("open"));
    }
}

function initAuthToggle() {
    const panel = document.querySelector("[data-auth-panel]");
    if (!panel) {
        return;
    }
    const tabs = Array.from(panel.querySelectorAll("[data-auth-tab]"));
    const form = panel.querySelector("[data-auth-form]");
    const title = panel.querySelector(".auth-header h2");
    const submitButton = panel.querySelector("[data-auth-submit-button]");
    const username = form?.querySelector("input[name='username']");
    const password = form?.querySelector("input[name='password']");
    const setMode = (mode) => {
        const activeTab = tabs.find((tab) => tab.dataset.authTab === mode) || tabs[0];
        tabs.forEach((tab) => {
            const active = tab === activeTab;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", String(active));
        });
        form.action = activeTab.dataset.authAction;
        if (title) {
            title.textContent = activeTab.dataset.authTitle;
        }
        if (submitButton) {
            submitButton.textContent = activeTab.dataset.authSubmit;
        }
        if (username) {
            if (activeTab.dataset.authTab === "signup") {
                username.minLength = 3;
            } else {
                username.removeAttribute("minlength");
            }
        }
        if (password) {
            password.autocomplete = activeTab.dataset.authTab === "signup" ? "new-password" : "current-password";
            if (activeTab.dataset.authTab === "signup") {
                password.minLength = 6;
            } else {
                password.removeAttribute("minlength");
            }
        }
    };
    tabs.forEach((tab) => {
        tab.addEventListener("click", () => setMode(tab.dataset.authTab));
    });
    setMode("login");
}

async function toggleLike(diveId) {
    const data = await fetchJson(`/api/dives/${diveId}/like`, { method: "POST" });
    document.querySelectorAll(`[data-like][data-dive-id='${diveId}']`).forEach((button) => {
        button.classList.toggle("liked", data.liked);
        const count = button.querySelector("[data-like-count]");
        if (count) {
            count.textContent = data.count;
        }
    });
}

async function toggleCenterLike(centerId) {
    const data = await fetchJson(`/api/dive-centers/${centerId}/like`, { method: "POST" });
    document.querySelectorAll(`[data-center-like][data-center-id='${centerId}']`).forEach((button) => {
        button.classList.toggle("liked", data.liked);
        const count = button.querySelector("[data-center-like-count]");
        if (count) {
            count.textContent = data.count;
        }
    });
}

async function openDive(diveId) {
    const modal = document.getElementById("diveModal");
    const body = document.getElementById("diveModalBody");
    if (!modal || !body) {
        return;
    }
    body.innerHTML = '<div class="modal-content"><p>Loading...</p></div>';
    modal.hidden = false;
    const dive = await fetchJson(`/api/dives/${diveId}`);
    body.innerHTML = renderDiveModal(dive);
    initStaticMaps(body);
}

function closeDiveModal() {
    const modal = document.getElementById("diveModal");
    if (modal) {
        modal.hidden = true;
    }
}

function renderDiveModal(dive) {
    const photos = dive.photos.length
        ? `<div class="modal-photo-grid">${dive.photos.map((src) => `<img src="${escapeHtml(src)}" alt="">`).join("")}</div>`
        : "";
    const species = dive.species.length
        ? `<div class="species-row">${dive.species.map((name) => `<span>${escapeHtml(name)}</span>`).join("")}</div>`
        : "";
    const coords =
        dive.latitude !== null && dive.longitude !== null
            ? `${Number(dive.latitude).toFixed(4)}, ${Number(dive.longitude).toFixed(4)}`
            : "Coordinates pending";
    const notes = dive.notes
        ? `<div class="notes-block"><p>${escapeHtml(dive.notes)}</p></div>`
        : "";
    const center = dive.dive_center_name
        ? `<p class="modal-center">with ${dive.dive_center_id ? `<a href="/dive-centers/${escapeHtml(dive.dive_center_id)}">${escapeHtml(dive.dive_center_name)}</a>` : escapeHtml(dive.dive_center_name)}</p>`
        : "";
    const nextUrl = `${window.location.pathname}${window.location.search}`;
    const editButton = dive.is_owner
        ? `
            <a class="icon-button modal-edit" href="/dive/${encodeURIComponent(dive.id)}/edit?next=${encodeURIComponent(nextUrl)}" aria-label="Edit dive" title="Edit dive">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 20h9"></path>
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>
                </svg>
            </a>
        `
        : "";
    return `
        <div class="modal-content">
            <div class="modal-title-row">
                <div class="modal-title">
                    <h2>${escapeHtml(dive.site_name)}</h2>
                    <p>${escapeHtml(dive.date)} | ${escapeHtml(dive.username)} | ${escapeHtml(dive.country_or_area || "")}</p>
                    ${center}
                </div>
                ${editButton}
            </div>
            ${photos}
            <div class="modal-stats">
                <div><span>${escapeHtml(dive.depth_ft)}</span><small>feet</small></div>
                <div><span>${escapeHtml(dive.duration_min)}</span><small>minutes</small></div>
                <div><span>${escapeHtml(dive.weight_lbs)}</span><small>pounds</small></div>
                <div><span>${escapeHtml(dive.exposure)}</span><small>exposure</small></div>
                <div><span>${escapeHtml(dive.visibility_ft)}</span><small>visibility ft</small></div>
                <div><span>${escapeHtml(dive.air_temp_degrees)}</span><small>air degrees</small></div>
                <div><span>${escapeHtml(dive.water_temp_degrees)}</span><small>water degrees</small></div>
                <div><span>${escapeHtml(dive.dive_type)}</span><small>dive type</small></div>
                <div><span>${escapeHtml(dive.current)}</span><small>current</small></div>
            </div>
            <div class="mini-map ${dive.latitude === null || dive.longitude === null ? "map-pending" : ""}" ${dive.latitude === null || dive.longitude === null ? "" : `data-static-map data-map-lat="${escapeHtml(dive.latitude)}" data-map-lng="${escapeHtml(dive.longitude)}" data-map-zoom="10"`}>
                <span class="map-pin"></span>
                <span class="coordinate-label">${escapeHtml(coords)}</span>
            </div>
            ${species}
            ${notes}
            <div class="dive-actions">
                <button class="chip-button like-button ${dive.liked_by_me ? "liked" : ""}" type="button" data-like data-dive-id="${dive.id}">
                    <span class="heart-icon"></span>
                    <span data-like-count>${dive.like_count}</span>
                </button>
                <span class="chip-button">${dive.comment_count} comments</span>
            </div>
            <div class="comments-block" data-comments>${commentsMarkup(dive.comments)}</div>
            <form class="comment-form" data-comment-form data-dive-id="${dive.id}">
                <input name="body" maxlength="600" autocomplete="off" placeholder="Add a comment">
                <button class="primary-button compact" type="submit">Post</button>
            </form>
        </div>
    `;
}

function commentsMarkup(comments) {
    if (!comments.length) {
        return '<p class="muted">No comments yet.</p>';
    }
    return comments
        .map(
            (comment) => `
                <div class="comment">
                    <strong>${escapeHtml(comment.username)}</strong>
                    <p>${escapeHtml(comment.body)}</p>
                </div>
            `,
        )
        .join("");
}

function renderComments(container, comments) {
    if (container) {
        container.innerHTML = commentsMarkup(comments);
    }
}

function initDiveForm() {
    const form = document.querySelector("[data-dive-form]");
    if (!form) {
        return;
    }

    const siteInput = form.querySelector("[data-site-input]");
    const siteResults = form.querySelector("[data-site-results]");
    const centerInput = form.querySelector("[data-center-input]");
    const centerResults = form.querySelector("[data-center-results]");
    const siteId = document.getElementById("diveSiteId");
    const centerId = document.getElementById("diveCenterId");
    const country = document.getElementById("country");
    const latitude = document.getElementById("latitude");
    const longitude = document.getElementById("longitude");
    let durationTouched = false;

    const pairs = {
        depth: {
            range: form.querySelector("[data-range='depth']"),
            number: form.querySelector("[data-number='depth']"),
            output: document.getElementById("depthOutput"),
            min: 0,
            max: 140,
            step: 5,
            unit: "ft",
        },
        duration: {
            range: form.querySelector("[data-range='duration']"),
            number: form.querySelector("[data-number='duration']"),
            output: document.getElementById("durationOutput"),
            min: 0,
            max: 120,
            step: 5,
            unit: "min",
        },
        weight: {
            range: form.querySelector("[data-range='weight']"),
            number: form.querySelector("[data-number='weight']"),
            output: document.getElementById("weightOutput"),
            min: 0,
            max: 20,
            step: 1,
            unit: "lb",
        },
        visibility: {
            range: form.querySelector("[data-range='visibility']"),
            number: form.querySelector("[data-number='visibility']"),
            output: document.getElementById("visibilityOutput"),
            min: 0,
            max: 100,
            step: 5,
            unit: "ft",
        },
        airTemp: {
            range: form.querySelector("[data-range='airTemp']"),
            number: form.querySelector("[data-number='airTemp']"),
            output: document.getElementById("airTempOutput"),
            min: 0,
            max: 100,
            step: 1,
            unit: "degrees",
        },
        waterTemp: {
            range: form.querySelector("[data-range='waterTemp']"),
            number: form.querySelector("[data-number='waterTemp']"),
            output: document.getElementById("waterTempOutput"),
            min: 0,
            max: 100,
            step: 1,
            unit: "degrees",
        },
    };

    const formatMetricValue = (value) => {
        const rounded = Math.round(Number(value) * 100) / 100;
        return Number.isInteger(rounded) ? String(rounded) : String(rounded);
    };

    const snapToStep = (value, pair) => clamp(Math.round(Number(value) / pair.step) * pair.step, pair.min, pair.max);

    const setPair = (name, value, fromUser = false, options = {}) => {
        const pair = pairs[name];
        const source = options.source || "auto";
        const commit = Boolean(options.commit);
        const rawValue = String(value ?? "").trim();
        const parsed = Number(rawValue);
        if (!Number.isFinite(parsed)) {
            if (commit) {
                const fallback = clamp(pair.range.value, pair.min, pair.max);
                pair.number.value = formatMetricValue(fallback);
                pair.output.textContent = `${formatMetricValue(fallback)} ${pair.unit}`;
            }
            return null;
        }

        const exact = clamp(parsed, pair.min, pair.max);
        const snapped = snapToStep(exact, pair);
        const displayValue = source === "slider" ? snapped : exact;
        pair.range.value = snapped;
        if (source !== "number" || commit || exact !== parsed) {
            pair.number.value = formatMetricValue(displayValue);
        }
        pair.output.textContent = `${formatMetricValue(displayValue)} ${pair.unit}`;
        if (name === "duration" && fromUser) {
            durationTouched = true;
        }
        if (name === "depth" && !durationTouched) {
            setPair("duration", suggestedDuration(exact), false, { commit: true });
        }
        return exact;
    };

    Object.entries(pairs).forEach(([name, pair]) => {
        pair.range.addEventListener("input", () => setPair(name, pair.range.value, true, { source: "slider", commit: true }));
        pair.number.addEventListener("input", () => setPair(name, pair.number.value, true, { source: "number" }));
        pair.number.addEventListener("blur", () => setPair(name, pair.number.value, true, { source: "number", commit: true }));
        setPair(name, pair.number.value, false, { commit: true });
    });

    siteInput.addEventListener(
        "input",
        debounce(async () => {
            siteId.value = "";
            const query = siteInput.value.trim();
            if (query.length < 2) {
                hideMenu(siteResults);
                return;
            }
            const sites = await fetchJson(`/api/sites?q=${encodeURIComponent(query)}`);
            renderSiteResults(sites);
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
            const centers = await fetchJson(`/api/dive-centers?q=${encodeURIComponent(query)}`);
            renderCenterResults(centers);
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
        if (site.max_depth_ft !== null && site.max_depth_ft !== undefined) {
            setPair("depth", site.max_depth_ft, false);
            setPair("duration", suggestedDuration(site.max_depth_ft), false);
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
    initPhotoPreview(form);
    initArrowNavigation(form);
}

function suggestedDuration(depthFt) {
    return clamp(Math.round((120 - Number(depthFt)) / 5) * 5, 0, 120);
}

function hideMenu(menu) {
    menu.hidden = true;
    menu.innerHTML = "";
}

function initSpeciesPicker(form, getCountry) {
    const input = form.querySelector("[data-species-input]");
    const results = form.querySelector("[data-species-results]");
    const suggestions = form.querySelector("[data-species-suggestions]");
    const tags = form.querySelector("[data-species-tags]");
    const hidden = document.getElementById("speciesJson");
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
            suggestions.innerHTML = "";
            return;
        }
        const names = await fetchJson(`/api/species-suggestions?${params.toString()}`);
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
            const species = await fetchJson(`/api/species?${params.toString()}`);
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

function initArrowNavigation(form) {
    const selector = "input:not([type='hidden']), select, textarea, button";
    form.addEventListener("keydown", (event) => {
        if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(event.key)) {
            return;
        }
        if (event.target.matches("input[type='range']")) {
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

function createInteractiveMap(viewport, { markers = [], onMarkerClick } = {}) {
    const tileLayer = viewport.querySelector(".map-world") || ensureTileLayer(viewport, "map-world");
    const markerLayer = viewport.querySelector(".map-marker-layer") || (() => {
        const layer = document.createElement("div");
        layer.className = "map-marker-layer";
        viewport.appendChild(layer);
        return layer;
    })();
    const validMarkers = markers.filter((marker) => isValidLatLng(marker.latitude, marker.longitude));
    const state = {
        zoom: MAP_MIN_ZOOM,
        centerPoint: latLngToWorldPoint(15, 0, MAP_MIN_ZOOM),
        dragging: false,
        lastX: 0,
        lastY: 0,
        userMoved: false,
    };

    const dimensions = () => ({
        width: Math.max(320, viewport.clientWidth),
        height: Math.max(320, viewport.clientHeight),
    });

    const fitToMarkers = () => {
        const size = dimensions();
        const topPadding = size.width < 720 ? 190 : 210;
        const sidePadding = size.width < 720 ? 48 : 110;
        const bottomPadding = size.width < 720 ? 120 : 90;
        const fit = fitMarkers(validMarkers, {
            width: Math.max(160, size.width - sidePadding * 2),
            height: Math.max(160, size.height - topPadding - bottomPadding),
            padding: 0,
            maxZoom: 12,
            singleZoom: 10,
        });
        state.zoom = fit.zoom;
        state.centerPoint = {
            x: fit.centerPoint.x,
            y: fit.centerPoint.y - (topPadding - bottomPadding) / 2,
        };
        render();
    };

    const markerPointForZoom = (marker) => {
        const point = latLngToWorldPoint(marker.latitude, marker.longitude, state.zoom);
        const worldSize = worldSizeAtZoom(state.zoom);
        let nextX = point.x;
        const distanceFromCenter = nextX - state.centerPoint.x;
        if (distanceFromCenter > worldSize / 2) {
            nextX -= worldSize;
        } else if (distanceFromCenter < -worldSize / 2) {
            nextX += worldSize;
        }
        return { x: nextX, y: point.y };
    };

    function renderMarkers(originX, originY) {
        const fragment = document.createDocumentFragment();
        validMarkers.forEach((marker) => {
            const point = markerPointForZoom(marker);
            const pin = document.createElement("button");
            pin.type = "button";
            pin.className = "world-pin";
            pin.style.left = `${Math.round(point.x - originX)}px`;
            pin.style.top = `${Math.round(point.y - originY)}px`;
            pin.title = `${marker.site_name || "Dive site"} | ${marker.date || ""}`;
            pin.setAttribute("aria-label", `${marker.site_name || "Dive site"} ${marker.date || ""}`.trim());
            pin.addEventListener("click", (event) => {
                event.stopPropagation();
                onMarkerClick?.(marker);
            });
            fragment.appendChild(pin);
        });
        markerLayer.replaceChildren(fragment);
    }

    function render() {
        const size = dimensions();
        const worldSize = worldSizeAtZoom(state.zoom);
        state.centerPoint.x = ((state.centerPoint.x % worldSize) + worldSize) % worldSize;
        state.centerPoint.y = clamp(state.centerPoint.y, 0, worldSize);
        const origin = renderTileGrid(tileLayer, {
            centerPoint: state.centerPoint,
            zoom: state.zoom,
            width: size.width,
            height: size.height,
        });
        renderMarkers(origin.originX, origin.originY);
    }

    const zoomTo = (nextZoom, originX = viewport.clientWidth / 2, originY = viewport.clientHeight / 2) => {
        const zoom = clamp(Math.round(nextZoom), MAP_MIN_ZOOM, MAP_MAX_ZOOM);
        if (zoom === state.zoom) {
            return;
        }
        const screenCenter = { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 };
        const oldOrigin = {
            x: state.centerPoint.x - viewport.clientWidth / 2,
            y: state.centerPoint.y - viewport.clientHeight / 2,
        };
        const focalLatLng = worldPointToLatLng({ x: oldOrigin.x + originX, y: oldOrigin.y + originY }, state.zoom);
        const focalPoint = latLngToWorldPoint(focalLatLng.lat, focalLatLng.lng, zoom);
        state.zoom = zoom;
        state.centerPoint = {
            x: focalPoint.x - (originX - screenCenter.x),
            y: focalPoint.y - (originY - screenCenter.y),
        };
        state.userMoved = true;
        render();
    };

    viewport.addEventListener(
        "wheel",
        (event) => {
            event.preventDefault();
            zoomTo(state.zoom + (event.deltaY > 0 ? -1 : 1), event.clientX, event.clientY);
        },
        { passive: false },
    );

    viewport.addEventListener("pointerdown", (event) => {
        if (event.target.closest(".world-pin")) {
            return;
        }
        state.dragging = true;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        state.userMoved = true;
        viewport.classList.add("dragging");
        viewport.setPointerCapture(event.pointerId);
    });

    viewport.addEventListener("pointermove", (event) => {
        if (!state.dragging) {
            return;
        }
        state.centerPoint.x -= event.clientX - state.lastX;
        state.centerPoint.y -= event.clientY - state.lastY;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        render();
    });

    const stopDragging = (event) => {
        state.dragging = false;
        viewport.classList.remove("dragging");
        if (event.pointerId !== undefined && viewport.hasPointerCapture(event.pointerId)) {
            viewport.releasePointerCapture(event.pointerId);
        }
    };

    viewport.addEventListener("pointerup", stopDragging);
    viewport.addEventListener("pointercancel", stopDragging);
    window.addEventListener("resize", debounce(() => {
        if (state.userMoved) {
            render();
        } else {
            fitToMarkers();
        }
    }, 180));

    ensureAttribution(viewport);
    fitToMarkers();

    return {
        fitToMarkers,
        zoomIn: () => zoomTo(state.zoom + 1),
        zoomOut: () => zoomTo(state.zoom - 1),
    };
}

function initProfileMap() {
    const map = document.querySelector("[data-profile-map]");
    if (!map) {
        return;
    }
    const world = map.querySelector(".profile-map-world");
    const pins = JSON.parse(map.dataset.pins || "[]").filter((pin) => isValidLatLng(pin.latitude, pin.longitude));
    if (world && pins.length) {
        const size = {
            width: Math.max(320, map.clientWidth),
            height: Math.max(220, map.clientHeight),
        };
        const fit = fitMarkers(pins, {
            width: size.width,
            height: size.height,
            padding: 42,
            maxZoom: 8,
            singleZoom: 5,
        });
        const origin = renderTileGrid(world, {
            centerPoint: fit.centerPoint,
            zoom: fit.zoom,
            width: size.width,
            height: size.height,
        });
        pins.forEach((pin) => {
            const point = latLngToWorldPoint(pin.latitude, pin.longitude, fit.zoom);
            const dot = document.createElement("span");
            dot.className = "profile-pin";
            dot.style.left = `${Math.round(point.x - origin.originX)}px`;
            dot.style.top = `${Math.round(point.y - origin.originY)}px`;
            world.appendChild(dot);
        });
        ensureAttribution(map);
    } else {
        map.classList.add("map-pending");
    }
    if (!map.dataset.profileMapBound) {
        window.addEventListener("resize", debounce(initProfileMap, 260));
        map.addEventListener("click", () => {
            window.location.href = "/map";
        });
        map.dataset.profileMapBound = "true";
    }
}

async function initCenterMaps() {
    const maps = Array.from(document.querySelectorAll("[data-center-map]"));
    for (const map of maps) {
        if (map.dataset.staticMap) {
            continue;
        }
        const query = (map.dataset.geocodeLocation || "").trim();
        if (!query) {
            continue;
        }
        const cacheKey = `pelagia:center-geocode:${query.toLowerCase()}`;
        let coords = null;
        try {
            coords = JSON.parse(window.localStorage.getItem(cacheKey) || "null");
        } catch (_error) {
            coords = null;
        }
        if (!coords) {
            try {
                const params = new URLSearchParams({ q: query, format: "jsonv2", limit: "1" });
                const response = await fetch(`https://nominatim.openstreetmap.org/search?${params.toString()}`);
                if (!response.ok) {
                    throw new Error(`Geocode failed: ${response.status}`);
                }
                const results = await response.json();
                const first = Array.isArray(results) ? results[0] : null;
                if (first) {
                    coords = { latitude: Number(first.lat), longitude: Number(first.lon) };
                    window.localStorage.setItem(cacheKey, JSON.stringify(coords));
                }
            } catch (_error) {
                coords = null;
            }
        }
        if (coords && isValidLatLng(coords.latitude, coords.longitude)) {
            map.dataset.staticMap = "true";
            map.dataset.mapLat = coords.latitude;
            map.dataset.mapLng = coords.longitude;
            map.dataset.mapZoom = "11";
            map.classList.remove("map-pending");
            const label = map.querySelector(".coordinate-label");
            if (label) {
                label.textContent = `${Number(coords.latitude).toFixed(3)}, ${Number(coords.longitude).toFixed(3)}`;
            }
            renderMiniTileMap(map);
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initAuthToggle();
    initDiveInteractions();
    initDiveForm();
    initStaticMaps(document);
    initProfileMap();
    initCenterMaps();
});

window.openDive = openDive;
window.coordinateToPoint = coordinateToPoint;
window.PelagiaMaps = {
    createInteractiveMap,
    initStaticMaps,
    isValidLatLng,
};
