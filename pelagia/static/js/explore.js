function initExplore() {
    const root = document.querySelector("[data-explore]");
    if (!root) return;
    const results = root.querySelector("[data-explore-results]");
    const count = root.querySelector("[data-explore-count]");
    const more = root.querySelector("[data-explore-more]");
    const distance = root.querySelector("[data-explore-distance]");
    const slider = root.querySelector("[data-explore-radius-slider]");
    const number = root.querySelector("[data-explore-radius-number]");
    const units = Array.from(root.querySelectorAll("[data-explore-unit]"));
    let nearby = JSON.parse(root.querySelector("[data-explore-initial-nearby]").textContent);
    let feedRequest;
    let pendingPreference;
    let savingPreference = false;
    const selectedUnit = () => units.find(option => option.checked)?.value || "mi";
    let previousUnit = selectedUnit();
    const radiusLimit = unit => unit === "mi" ? 100 : 160;

    async function rememberNearby(value) {
        pendingPreference = value;
        if (savingPreference) return;
        savingPreference = true;
        try {
            // Serialize writes so an older radius cannot overwrite a newer choice.
            while (pendingPreference) {
                const selected = pendingPreference;
                pendingPreference = null;
                try {
                    await fetchJson("/api/explore/nearby/preference", {
                        method: "POST", keepalive: true,
                        headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                        body: JSON.stringify(selected),
                    });
                } catch (_error) {
                    window.PelagiaLoading?.announce("Couldn't remember this distance. Your results are still available.", true);
                }
            }
        } finally {
            savingPreference = false;
        }
    }

    function writeHistory() {
        const url = new URL(window.location.href);
        url.search = new URLSearchParams({
            nearby: nearby.query, display: nearby.displayName,
            latitude: nearby.latitude, longitude: nearby.longitude,
            radius: nearby.radius, unit: nearby.unit,
        }).toString();
        window.history.replaceState(null, "", url);
    }

    function setRadius(value, unit = selectedUnit()) {
        const radius = Math.min(radiusLimit(unit), Math.max(1, Math.round(Number(value) || 1)));
        slider.max = number.max = radiusLimit(unit);
        slider.value = number.value = String(radius);
        return radius;
    }

    function paintControls() {
        distance.hidden = !nearby;
        if (!nearby) return;
        units.forEach(option => { option.checked = option.value === nearby.unit; });
        previousUnit = nearby.unit;
        setRadius(nearby.radius, nearby.unit);
    }

    function summary(total, selected) {
        const label = `${total} ${total === 1 ? "result" : "results"}`;
        if (!selected) return root.dataset.location ? `${label} in ${root.dataset.location}` : "";
        const unit = selected.unit === "mi" ? (selected.radius === 1 ? "mile" : "miles") : "km";
        return `${label} within ${selected.radius} ${unit} of ${selected.displayName}`;
    }

    function paintFeed(data, page, selected) {
        if (page > 1) results.insertAdjacentHTML("beforeend", data.html);
        else results.innerHTML = data.html;
        count.textContent = summary(data.total, selected);
        more.textContent = "Show more";
        more.dataset.nextPage = data.next_page || "";
        more.hidden = !data.next_page;
        initStaticMaps(results);
    }

    function offerRetry(message, page) {
        count.textContent = message;
        more.textContent = "Try again";
        more.dataset.nextPage = page;
        more.hidden = false;
    }

    async function loadFeed(page = 1, remember = false) {
        feedRequest?.abort();
        const controller = new AbortController();
        feedRequest = controller;
        const selected = nearby ? { ...nearby } : null;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
        more.hidden = true;
        if (page === 1) { results.replaceChildren(); count.textContent = ""; }
        const end = window.PelagiaLoading?.begin(results, "Loading dive sites") || (() => {});
        try {
            const params = new URLSearchParams(selected ? {
                query: selected.query, display_name: selected.displayName,
                latitude: selected.latitude, longitude: selected.longitude,
                radius: selected.radius, unit: selected.unit, page,
            } : { location: root.dataset.location, page });
            const endpoint = selected ? "/api/explore/nearby" : "/api/explore";
            const data = await fetchJson(`${endpoint}?${params}`, { signal: controller.signal });
            if (feedRequest !== controller) return;
            end();
            paintFeed(data, page, selected);
            if (remember && selected) rememberNearby(selected);
        } catch (error) {
            if (feedRequest !== controller || (error.name === "AbortError" && !timedOut)) return;
            offerRetry("Couldn't load dive sites. Please try again.", page);
        } finally {
            window.clearTimeout(timeout);
            end();
            if (feedRequest === controller) feedRequest = null;
        }
    }

    async function searchPlace() {
        const query = root.dataset.query;
        const unit = selectedUnit();
        const radius = Number(number.value);
        results.replaceChildren();
        more.hidden = true;
        count.textContent = "";
        const end = window.PelagiaLoading?.begin(results, "Searching for a place") || (() => {});
        try {
            const data = await fetchJson("/api/explore/nearby", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                body: JSON.stringify({ query, radius, unit }),
            });
            if (data.error === "no_results") {
                count.textContent = `No search results for ${query}. Try another place in Search Pelagia above.`;
                return;
            }
            nearby = {
                query: data.query, displayName: data.place.display_name,
                latitude: data.place.latitude, longitude: data.place.longitude,
                radius: data.radius, unit: data.unit,
            };
            root.dataset.query = "";
            root.dataset.location = "";
            paintControls();
            end();
            paintFeed(data, 1, nearby);
            writeHistory();
        } catch (_error) {
            offerRetry("Location search is temporarily unavailable. Please try again.", 1);
        } finally {
            end();
        }
    }

    const updateFeed = debounce(() => loadFeed(1, true), 180);
    function changeRadius(raw, unit = selectedUnit()) {
        const radius = setRadius(raw, unit);
        if (!nearby || (radius === nearby.radius && unit === nearby.unit)) return;
        nearby = { ...nearby, radius, unit };
        feedRequest?.abort();
        feedRequest = null;
        more.hidden = true;
        count.textContent = "Updating results…";
        writeHistory();
        updateFeed();
    }
    slider.addEventListener("input", () => changeRadius(slider.value));
    number.addEventListener("input", () => {
        if (number.value !== "" && Number.isInteger(Number(number.value))) changeRadius(number.value);
    });
    number.addEventListener("blur", () => changeRadius(number.value));
    units.forEach(option => option.addEventListener("change", () => {
        if (!option.checked) return;
        const current = Number(number.value) || 1;
        const converted = previousUnit === option.value ? current
            : previousUnit === "mi" ? current * 1.609344 : current / 1.609344;
        previousUnit = option.value;
        changeRadius(converted, option.value);
    }));
    more.addEventListener("click", () => {
        if (root.dataset.query) searchPlace();
        else loadFeed(Number(more.dataset.nextPage) || 1, Boolean(nearby));
    });
    // Each history entry is independently server-renderable, including its coordinates.
    window.addEventListener("popstate", () => window.location.reload());
    window.addEventListener("pagehide", () => { updateFeed.cancel(); feedRequest?.abort(); });
    paintControls();
    if (root.dataset.query) searchPlace();
}

document.addEventListener("DOMContentLoaded", initExplore);
