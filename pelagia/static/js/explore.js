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
    const initialLocation = root.dataset.location;
    let location = initialLocation;
    let suggestionRequest;
    let feedRequest;
    let options = [];
    let active = -1;

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

    function paintLocation() {
        tag.hidden = !location;
        label.textContent = location;
        clear.setAttribute("aria-label", `Remove location ${location}`);
        input.hidden = Boolean(location);
        input.disabled = Boolean(location);
        input.value = "";
    }

    function chooseLocation(next, updateHistory = true) {
        search.cancel();
        closeSuggestions();
        location = next;
        paintLocation();
        if (updateHistory) {
            const url = new URL(window.location.href);
            url.searchParams.set("location", location);
            window.history.pushState(null, "", url);
        }
        loadFeed();
        if (location) clear.focus();
        else input.focus();
    }

    async function loadFeed(page = 1) {
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
            if (append) results.insertAdjacentHTML("beforeend", data.html);
            else results.innerHTML = data.html;
            count.textContent = selectedLocation ? `${data.total} ${data.total === 1 ? "dive site" : "dive sites"} in ${selectedLocation}` : "";
            more.dataset.nextPage = data.next_page || "";
            more.hidden = !data.next_page;
            initStaticMaps(results);
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

    const search = debounce(async () => {
        const query = input.value.trim();
        if (!query || location || document.activeElement !== input) return;
        const controller = new AbortController();
        suggestionRequest = controller;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
        try {
            const names = await fetchJson(`/api/explore/locations?${new URLSearchParams({ q: query })}`, { signal: controller.signal });
            if (suggestionRequest !== controller || location) return;
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

    input.addEventListener("input", () => { closeSuggestions(); search(); });
    input.addEventListener("focus", () => { if (input.value.trim()) search(); });
    input.addEventListener("blur", () => {
        window.setTimeout(() => {
            if (!root.querySelector(".explore-search").contains(document.activeElement)) closeSuggestions();
        }, 0);
    });
    input.addEventListener("keydown", (event) => {
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
    document.addEventListener("click", (event) => {
        if (!root.querySelector(".explore-search").contains(event.target)) { search.cancel(); closeSuggestions(); }
    });
    clear.addEventListener("click", () => chooseLocation(""));
    more.addEventListener("click", () => {
        more.textContent = "Show more";
        loadFeed(Number(more.dataset.nextPage) || 1);
    });
    window.addEventListener("popstate", () => {
        const params = new URL(window.location.href).searchParams;
        chooseLocation(params.has("location") ? params.get("location") : initialLocation, false);
    });
    window.addEventListener("pagehide", () => { search.cancel(); closeSuggestions(); feedRequest?.abort(); });
}

document.addEventListener("DOMContentLoaded", initExplore);
