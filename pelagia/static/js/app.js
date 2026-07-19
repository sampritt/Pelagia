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
        if (!form) {
            return;
        }
        event.preventDefault();
        const input = form.querySelector("input[name='body']");
        const body = input.value.trim();
        if (!body) {
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
    return `
        <div class="modal-content">
            <div class="modal-title">
                <h2>${escapeHtml(dive.site_name)}</h2>
                <p>${escapeHtml(dive.date)} | ${escapeHtml(dive.username)} | ${escapeHtml(dive.country_or_area || "")}</p>
            </div>
            ${photos}
            <div class="modal-stats">
                <div><span>${escapeHtml(dive.depth_ft)}</span><small>feet</small></div>
                <div><span>${escapeHtml(dive.duration_min)}</span><small>minutes</small></div>
                <div><span>${escapeHtml(dive.weight_lbs)}</span><small>pounds</small></div>
                <div><span>${escapeHtml(dive.exposure)}</span><small>exposure</small></div>
            </div>
            <div class="mini-map" style="--pin-x: ${coordinateToPoint(dive.latitude, dive.longitude).x}%; --pin-y: ${coordinateToPoint(dive.latitude, dive.longitude).y}%;">
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
    const siteId = document.getElementById("diveSiteId");
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
            step: 1,
            unit: "ft",
        },
        duration: {
            range: form.querySelector("[data-range='duration']"),
            number: form.querySelector("[data-number='duration']"),
            output: document.getElementById("durationOutput"),
            min: 0,
            max: 120,
            step: 10,
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
    };

    const setPair = (name, value, fromUser = false) => {
        const pair = pairs[name];
        let next = clamp(Math.round(Number(value) / pair.step) * pair.step, pair.min, pair.max);
        pair.range.value = next;
        pair.number.value = next;
        pair.output.textContent = `${next} ${pair.unit}`;
        if (name === "duration" && fromUser) {
            durationTouched = true;
        }
        if (name === "depth" && !durationTouched) {
            setPair("duration", suggestedDuration(next), false);
        }
    };

    Object.entries(pairs).forEach(([name, pair]) => {
        pair.range.addEventListener("input", () => setPair(name, pair.range.value, true));
        pair.number.addEventListener("input", () => setPair(name, pair.number.value, true));
        setPair(name, pair.number.value, false);
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

    initSpeciesPicker(form, () => country.value.trim());
    initPhotoPreview(form);
    initArrowNavigation(form);
}

function suggestedDuration(depthFt) {
    return clamp(Math.round((120 - Number(depthFt)) / 10) * 10, 0, 120);
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
    const selected = [];

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
            addSpecies(input.value.trim());
            input.value = "";
            hideMenu(results);
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

function initProfileMap() {
    const map = document.querySelector("[data-profile-map]");
    if (!map) {
        return;
    }
    const world = map.querySelector(".profile-map-world");
    const pins = JSON.parse(map.dataset.pins || "[]");
    pins.forEach((pin) => {
        if (pin.latitude === null || pin.longitude === null) {
            return;
        }
        const point = coordinateToPoint(pin.latitude, pin.longitude);
        const dot = document.createElement("span");
        dot.className = "profile-pin";
        dot.style.setProperty("--pin-x", `${point.x}%`);
        dot.style.setProperty("--pin-y", `${point.y}%`);
        world.appendChild(dot);
    });
    map.addEventListener("click", () => {
        window.location.href = "/map";
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initDiveInteractions();
    initDiveForm();
    initProfileMap();
});

window.openDive = openDive;
window.coordinateToPoint = coordinateToPoint;
