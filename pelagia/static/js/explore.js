function initExplore() {
    const root = document.querySelector("[data-explore]");
    if (!root) return;
    const input = root.querySelector("[data-explore-input]");
    const suggestions = root.querySelector("[data-explore-suggestions]");
    const tag = root.querySelector("[data-explore-tag]");
    const label = root.querySelector("[data-explore-location]");
    const clear = root.querySelector("[data-explore-clear]");
    const results = root.querySelector("[data-explore-results]");
    const count = root.querySelector("[data-explore-count]");
    const more = root.querySelector("[data-explore-more]");
    const feedFrame = root.querySelector("[data-explore-feed-frame]");
    const advancedFrame = root.querySelector("[data-explore-advanced-frame]");
    const advancedOpen = root.querySelector("[data-explore-advanced-open]");
    const advancedBack = root.querySelector("[data-explore-advanced-back]");
    const nearbyForm = root.querySelector("[data-explore-nearby-form]");
    const radiusSlider = root.querySelector("[data-explore-radius-slider]");
    const radiusNumber = root.querySelector("[data-explore-radius-number]");
    const unitInputs = Array.from(root.querySelectorAll("[data-explore-unit]"));
    const placeInput = root.querySelector("[data-explore-place]");
    const nearbyError = root.querySelector("[data-explore-nearby-error]");
    const nearbySubmit = root.querySelector("[data-explore-nearby-submit]");
    const initialNearby = JSON.parse(root.querySelector("[data-explore-initial-nearby]").textContent);
    const initialLocation = root.dataset.location;
    let location = initialLocation;
    let nearby = initialNearby;
    let suggestionRequest;
    let feedRequest;
    let options = [];
    let active = -1;
    let pendingLocation;
    let savingLocation = false;
    let advancedOpenedHere = false;
    let previousUnit = "mi";

    async function rememberLocation(next) {
        pendingLocation = next;
        if (savingLocation) return;
        savingLocation = true;
        try {
            // Serialize writes so a slower earlier choice cannot replace the latest one.
            while (pendingLocation !== undefined) {
                const selected = pendingLocation;
                pendingLocation = undefined;
                try {
                    await fetchJson("/api/explore/location", {
                        method: "POST", keepalive: true,
                        headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                        body: JSON.stringify({ location: selected }),
                    });
                } catch (_error) {
                    window.PelagiaLoading?.announce("Couldn't remember this location. Choose it again when you're online.", true);
                }
            }
        } finally {
            savingLocation = false;
        }
    }

    function closeSuggestions() {
        suggestionRequest?.abort();
        suggestionRequest = null;
        suggestions.hidden = true;
        suggestions.replaceChildren();
        options = [];
        active = -1;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
    }

    function activeLabel() {
        return nearby?.displayName || location;
    }

    function paintLocation() {
        const selected = activeLabel();
        tag.hidden = !selected;
        label.textContent = selected;
        clear.setAttribute("aria-label", `Remove location ${selected}`);
        input.hidden = Boolean(selected);
        input.disabled = Boolean(selected);
        input.value = "";
    }

    function showFeedFrame() {
        feedFrame.hidden = false;
        advancedFrame.hidden = true;
    }

    function showAdvancedFrame(updateHistory = true) {
        search.cancel();
        closeSuggestions();
        feedRequest?.abort();
        feedFrame.hidden = true;
        advancedFrame.hidden = false;
        nearbyError.hidden = true;
        nearbyError.textContent = "";
        if (nearby) paintNearbyForm();
        if (updateHistory) {
            const url = new URL(window.location.href);
            url.searchParams.set("advanced", "1");
            window.history.pushState(null, "", url);
            advancedOpenedHere = true;
        }
    }

    function clearExploreParams(url) {
        ["advanced", "nearby", "display", "latitude", "longitude", "radius", "unit"]
            .forEach(name => url.searchParams.delete(name));
    }

    function writeNearbyHistory() {
        const url = new URL(window.location.href);
        clearExploreParams(url);
        url.searchParams.delete("location");
        url.searchParams.set("nearby", nearby.query);
        url.searchParams.set("display", nearby.displayName);
        url.searchParams.set("latitude", nearby.latitude);
        url.searchParams.set("longitude", nearby.longitude);
        url.searchParams.set("radius", nearby.radius);
        url.searchParams.set("unit", nearby.unit);
        window.history.replaceState(null, "", url);
    }

    function chooseLocation(next, updateHistory = true, remember = true) {
        search.cancel();
        closeSuggestions();
        nearby = null;
        location = next;
        paintLocation();
        showFeedFrame();
        if (updateHistory) {
            const url = new URL(window.location.href);
            clearExploreParams(url);
            url.searchParams.set("location", location);
            window.history.pushState(null, "", url);
            if (remember) rememberLocation(location);
        }
        if (location) loadFeed();
        else showEmptyFeed();
        if (location) clear.focus();
        else input.focus();
    }

    function showEmptyFeed() {
        feedRequest?.abort();
        feedRequest = null;
        count.textContent = "";
        more.hidden = true;
        more.dataset.nextPage = "";
        results.innerHTML = '<div class="explore-empty"><svg class="explore-empty-mark" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"></circle><path d="m16 16 4.5 4.5"></path></svg><h2>Where will you dive next?</h2><p>Choose a country or region to discover dive sites.</p></div>';
    }

    function nearbyCount(total) {
        const sites = `${total} ${total === 1 ? "dive site" : "dive sites"}`;
        const units = nearby.unit === "mi" ? (nearby.radius === 1 ? "mile" : "miles") : "km";
        return `${sites} within ${nearby.radius} ${units} of ${nearby.displayName}`;
    }

    function paintFeed(data, page, summary) {
        if (page > 1) results.insertAdjacentHTML("beforeend", data.html);
        else results.innerHTML = data.html;
        count.textContent = summary(data.total);
        more.dataset.nextPage = data.next_page || "";
        more.hidden = !data.next_page;
        initStaticMaps(results);
    }

    async function loadFeed(page = 1) {
        if (nearby) return loadNearbyFeed(page);
        feedRequest?.abort();
        const controller = new AbortController();
        feedRequest = controller;
        const selectedLocation = location;
        const append = page > 1;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
        more.hidden = true;
        if (!append) {
            results.replaceChildren();
            count.textContent = "";
        }
        const end = window.PelagiaLoading?.begin(results, "Loading dive sites") || (() => {});
        try {
            const params = new URLSearchParams({ location: selectedLocation, page });
            const data = await fetchJson(`/api/explore?${params}`, { signal: controller.signal });
            if (feedRequest !== controller) return;
            end();
            paintFeed(data, page, total => selectedLocation ? `${total} ${total === 1 ? "dive site" : "dive sites"} in ${selectedLocation}` : "");
        } catch (error) {
            if (feedRequest !== controller || (error.name === "AbortError" && !timedOut)) return;
            count.textContent = "Couldn't load dive sites. Please try again.";
            more.textContent = "Try again";
            more.dataset.nextPage = page;
            more.hidden = false;
        } finally {
            window.clearTimeout(timeout);
            end();
            if (feedRequest === controller) feedRequest = null;
        }
    }

    async function loadNearbyFeed(page = 1) {
        feedRequest?.abort();
        const controller = new AbortController();
        feedRequest = controller;
        const selected = { ...nearby };
        const append = page > 1;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
        more.hidden = true;
        if (!append) {
            results.replaceChildren();
            count.textContent = "";
        }
        const end = window.PelagiaLoading?.begin(results, "Loading nearby dive sites") || (() => {});
        try {
            const params = new URLSearchParams({
                query: selected.query, display_name: selected.displayName,
                latitude: selected.latitude, longitude: selected.longitude,
                radius: selected.radius, unit: selected.unit, page,
            });
            const data = await fetchJson(`/api/explore/nearby?${params}`, { signal: controller.signal });
            if (feedRequest !== controller || nearby?.query !== selected.query) return;
            end();
            paintFeed(data, page, nearbyCount);
        } catch (error) {
            if (feedRequest !== controller || (error.name === "AbortError" && !timedOut)) return;
            count.textContent = "Couldn't load nearby dive sites. Please try again.";
            more.textContent = "Try again";
            more.dataset.nextPage = page;
            more.hidden = false;
        } finally {
            window.clearTimeout(timeout);
            end();
            if (feedRequest === controller) feedRequest = null;
        }
    }

    const search = debounce(async () => {
        const query = input.value.trim();
        if (!query || activeLabel() || document.activeElement !== input) return;
        const controller = new AbortController();
        suggestionRequest = controller;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
        try {
            const names = await fetchJson(`/api/explore/locations?${new URLSearchParams({ q: query })}`, { signal: controller.signal });
            if (suggestionRequest !== controller || activeLabel()) return;
            options = names;
            active = -1;
            suggestions.replaceChildren();
            names.forEach((name, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.id = `exploreLocation-${index}`;
                button.tabIndex = -1;
                button.setAttribute("role", "option");
                button.setAttribute("aria-selected", "false");
                button.textContent = name;
                button.addEventListener("click", () => chooseLocation(name));
                suggestions.appendChild(button);
            });
            if (!names.length) suggestions.innerHTML = '<p class="suggestion-message" role="status">No locations found. Try another country or region.</p>';
            suggestions.hidden = false;
            input.setAttribute("aria-expanded", "true");
        } catch (error) {
            if (suggestionRequest !== controller || (error.name === "AbortError" && !timedOut)) return;
            suggestions.innerHTML = '<p class="suggestion-message" role="status">Couldn’t search locations. Please try again.</p>';
            suggestions.hidden = false;
            input.setAttribute("aria-expanded", "true");
        } finally {
            window.clearTimeout(timeout);
        }
    }, 160);

    function radiusLimit(unit) {
        return unit === "mi" ? 100 : 160;
    }

    function selectedUnit() {
        return unitInputs.find(option => option.checked)?.value || "mi";
    }

    function setRadius(value, unit = selectedUnit()) {
        const integer = Math.min(radiusLimit(unit), Math.max(1, Math.round(Number(value) || 1)));
        radiusSlider.max = radiusLimit(unit);
        radiusNumber.max = radiusLimit(unit);
        radiusSlider.value = integer;
        radiusNumber.value = integer;
    }

    function paintNearbyForm() {
        placeInput.value = nearby.query;
        unitInputs.forEach(option => { option.checked = option.value === nearby.unit; });
        previousUnit = nearby.unit;
        setRadius(nearby.radius, nearby.unit);
    }

    radiusSlider.addEventListener("input", () => { radiusNumber.value = radiusSlider.value; });
    radiusNumber.addEventListener("input", () => {
        if (radiusNumber.value !== "" && Number.isInteger(Number(radiusNumber.value))) setRadius(radiusNumber.value);
    });
    radiusNumber.addEventListener("blur", () => setRadius(radiusNumber.value));
    unitInputs.forEach(option => option.addEventListener("change", () => {
        if (!option.checked) return;
        const current = Number(radiusNumber.value) || 1;
        const converted = previousUnit === option.value
            ? current
            : previousUnit === "mi" ? current * 1.609344 : current / 1.609344;
        previousUnit = option.value;
        setRadius(converted, option.value);
    }));

    nearbyForm.addEventListener("submit", async event => {
        event.preventDefault();
        const query = placeInput.value.trim();
        const radius = Number(radiusNumber.value);
        const unit = selectedUnit();
        if (!query) {
            nearbyError.textContent = "Enter a place to search.";
            nearbyError.hidden = false;
            placeInput.focus();
            return;
        }
        if (!Number.isInteger(radius) || radius < 1 || radius > radiusLimit(unit)) {
            nearbyError.textContent = `Enter a whole-number radius from 1 to ${radiusLimit(unit)}.`;
            nearbyError.hidden = false;
            radiusNumber.focus();
            return;
        }
        nearbyError.hidden = true;
        nearbySubmit.disabled = true;
        nearbySubmit.textContent = "Searching…";
        try {
            const data = await fetchJson("/api/explore/nearby", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
                body: JSON.stringify({ query, radius, unit }),
            });
            if (data.error === "no_results") {
                nearbyError.textContent = `No search results for ${query}`;
                nearbyError.hidden = false;
                return;
            }
            nearby = {
                query: data.query,
                displayName: data.place.display_name,
                latitude: data.place.latitude,
                longitude: data.place.longitude,
                radius: data.radius,
                unit: data.unit,
            };
            location = "";
            paintLocation();
            showFeedFrame();
            paintFeed(data, 1, nearbyCount);
            writeNearbyHistory();
            clear.focus();
        } catch (_error) {
            nearbyError.textContent = "Location search is temporarily unavailable. Please try again.";
            nearbyError.hidden = false;
        } finally {
            nearbySubmit.disabled = false;
            nearbySubmit.textContent = "Search";
        }
    });

    function restoreFromUrl(initial = false) {
        const params = new URL(window.location.href).searchParams;
        if (params.get("advanced") === "1") {
            showAdvancedFrame(false);
            return;
        }
        const nearbyQuery = params.get("nearby");
        if (nearbyQuery) {
            const latitude = Number(params.get("latitude"));
            const longitude = Number(params.get("longitude"));
            const radius = Number(params.get("radius"));
            const unit = params.get("unit");
            const displayName = params.get("display") || nearbyQuery;
            if (Number.isFinite(latitude) && Number.isFinite(longitude) && Number.isInteger(radius) && ["mi", "km"].includes(unit)) {
                nearby = { query: nearbyQuery, displayName, latitude, longitude, radius, unit };
                location = "";
                paintLocation();
                showFeedFrame();
                loadNearbyFeed();
                return;
            }
        }
        if (initial && initialNearby && !params.has("location")) {
            nearby = initialNearby;
            location = "";
            paintLocation();
            showFeedFrame();
            return;
        }
        const nextLocation = params.has("location") ? params.get("location") : initialLocation;
        if (initial && nextLocation === initialLocation) {
            nearby = null;
            location = nextLocation;
            paintLocation();
            showFeedFrame();
            return;
        }
        chooseLocation(nextLocation, false, false);
    }

    input.addEventListener("input", () => { closeSuggestions(); search(); });
    input.addEventListener("focus", () => { if (input.value.trim()) search(); });
    input.addEventListener("blur", () => {
        window.setTimeout(() => {
            if (!root.querySelector(".explore-search").contains(document.activeElement)) closeSuggestions();
        }, 0);
    });
    input.addEventListener("keydown", event => {
        if (event.key === "Escape") { search.cancel(); closeSuggestions(); return; }
        if (suggestions.hidden || !options.length) return;
        if (event.key === "Enter") {
            event.preventDefault();
            chooseLocation(options[active < 0 ? 0 : active]);
        } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            active = event.key === "ArrowDown" ? (active + 1) % options.length : (active <= 0 ? options.length - 1 : active - 1);
            Array.from(suggestions.children).forEach((option, index) => option.setAttribute("aria-selected", String(index === active)));
            input.setAttribute("aria-activedescendant", suggestions.children[active].id);
            suggestions.children[active].scrollIntoView({ block: "nearest" });
        }
    });
    document.addEventListener("click", event => {
        if (!root.querySelector(".explore-search").contains(event.target)) { search.cancel(); closeSuggestions(); }
    });
    clear.addEventListener("click", () => chooseLocation(""));
    advancedOpen.addEventListener("click", () => showAdvancedFrame());
    advancedBack.addEventListener("click", () => {
        if (advancedOpenedHere) {
            advancedOpenedHere = false;
            window.history.back();
        } else {
            const url = new URL(window.location.href);
            url.searchParams.delete("advanced");
            window.history.replaceState(null, "", url);
            showFeedFrame();
            if (!activeLabel()) input.focus();
        }
    });
    more.addEventListener("click", () => {
        more.textContent = "Show more";
        loadFeed(Number(more.dataset.nextPage) || 1);
    });
    window.addEventListener("popstate", () => restoreFromUrl());
    window.addEventListener("pagehide", () => { search.cancel(); closeSuggestions(); feedRequest?.abort(); });
    restoreFromUrl(true);
}

document.addEventListener("DOMContentLoaded", initExplore);
