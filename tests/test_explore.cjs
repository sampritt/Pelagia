const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

function element() {
    return {
        value: "", hidden: false, dataset: {}, handlers: {}, children: [], textContent: "",
        set innerHTML(value) { this.html = value; this.children = []; },
        get innerHTML() { return this.html || ""; },
        replaceChildren() { this.children = []; this.html = ""; },
        insertAdjacentHTML(_where, html) { this.html = (this.html || "") + html; },
        addEventListener(type, callback) { (this.handlers[type] ||= []).push(callback); },
        emit(type, event = {}) { for (const callback of this.handlers[type] || []) callback(event); },
    };
}
const initialNearby = {
    query: "Victoria", displayName: "Victoria, British Columbia, Canada",
    latitude: 48.4, longitude: -123.3, radius: 15, unit: "mi",
};
function setup({ nearby = initialNearby, query = "", location = "", unit = "mi", deferSaves = false } = {}) {
    const names = ["results", "count", "more", "distance", "radius-slider", "radius-number", "initial-nearby"];
    const parts = Object.fromEntries(names.map(name => [name, element()]));
    parts["initial-nearby"].textContent = JSON.stringify(nearby);
    parts["radius-number"].value = unit === "mi" ? "15" : "50";
    const units = [element(), element()];
    units[0].value = "mi"; units[0].checked = unit === "mi";
    units[1].value = "km"; units[1].checked = unit === "km";
    const root = element();
    root.dataset = { query, location };
    root.querySelector = selector => parts[selector.match(/data-explore-(.+)\]/)[1]];
    root.querySelectorAll = () => units;
    const document = element(); document.querySelector = () => root;
    const window = element();
    window.location = { href: "http://localhost/explore", reload() { window.reloaded = true; } };
    window.history = { replaceState(_state, _unused, url) { window.location.href = String(url); } };
    window.setTimeout = () => 1; window.clearTimeout = () => {};
    const requests = [], saves = [];
    const context = vm.createContext({
        document, window, URL, URLSearchParams, AbortController,
        debounce(fn) { fn.cancel = () => {}; return fn; }, initStaticMaps() {},
        fetchJson(url, options) {
            return new Promise((resolve, reject) => {
                const call = { url, options, resolve, reject };
                if (url.endsWith("/preference")) {
                    saves.push(call);
                    if (!deferSaves) resolve({ saved: true });
                } else requests.push(call);
            });
        },
    });
    vm.runInContext(fs.readFileSync("pelagia/static/js/explore.js", "utf8"), context);
    document.emit("DOMContentLoaded");
    return { parts, units, requests, saves, window };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const geoResult = { html: "Nearby cards", total: 3, next_page: 2, query: "Victoria", radius: 15, unit: "mi",
    place: { display_name: initialNearby.displayName, latitude: 48.4, longitude: -123.3 } };

test("a saved place restores controls without fetching or geocoding again", () => {
    const { parts, requests } = setup();
    assert.equal(requests.length, 0);
    assert.equal(parts.distance.hidden, false);
    assert.equal(parts["radius-number"].value, "15");
});

test("free-text search geocodes once, then pagination and slider reuse coordinates", async () => {
    const { parts, requests, window, saves } = setup({ nearby: null, query: "Victoria" });
    assert.equal(parts.distance.hidden, true);
    assert.deepEqual(JSON.parse(requests[0].options.body), { query: "Victoria", radius: 15, unit: "mi" });
    requests[0].resolve(geoResult); await flush();
    assert.equal(parts.distance.hidden, false);
    assert.match(parts.count.textContent, /3 results within 15 miles of Victoria/);
    assert.match(window.location.href, /latitude=48.4/);
    parts.more.emit("click");
    assert.match(requests[1].url, /page=2/);
    assert.equal(requests[1].options.method, undefined);
    requests[1].resolve({ html: " More cards", total: 3, next_page: null }); await flush();
    assert.equal(parts.results.innerHTML, "Nearby cards More cards");
    parts["radius-slider"].value = "35"; parts["radius-slider"].emit("input");
    assert.equal(parts["radius-number"].value, "35");
    assert.match(requests[2].url, /radius=35/);
    requests[2].resolve({ html: "Expanded cards", total: 8, next_page: null }); await flush();
    assert.equal(parts.results.innerHTML, "Expanded cards");
    assert.equal(JSON.parse(saves[1].options.body).radius, 35);
});

test("metric searches default to 50 km and zero sites still show an adjustable radius", async () => {
    const { parts, requests } = setup({ nearby: null, query: "Victoria", unit: "km" });
    assert.deepEqual(JSON.parse(requests[0].options.body), { query: "Victoria", radius: 50, unit: "km" });
    requests[0].resolve({ ...geoResult, total: 0, unit: "km", radius: 50, html: "No dive sites here yet" }); await flush();
    assert.equal(parts.distance.hidden, false);
    assert.match(parts.count.textContent, /0 results within 50 km/);
    assert.match(parts.results.innerHTML, /No dive sites/);
});

test("stale radius and pagination responses cannot replace newer results", async () => {
    const { parts, requests } = setup();
    parts["radius-slider"].value = "20"; parts["radius-slider"].emit("input");
    parts["radius-slider"].value = "40"; parts["radius-slider"].emit("input");
    assert.equal(requests[0].options.signal.aborted, true);
    requests[1].resolve({ html: "Current", total: 12, next_page: null }); await flush();
    requests[0].resolve({ html: "Stale", total: 1, next_page: 2 }); await flush();
    assert.equal(parts.results.innerHTML, "Current");
    assert.match(parts.count.textContent, /12 results within 40 miles/);
    assert.equal(parts.more.hidden, true);
});

test("unit changes convert the selected distance and numeric input clamps at limits", () => {
    const { parts, units, requests } = setup();
    units[0].checked = false; units[1].checked = true; units[1].emit("change");
    assert.equal(parts["radius-number"].value, "24");
    assert.equal(parts["radius-slider"].max, 160);
    assert.match(requests[0].url, /unit=km/);
    parts["radius-number"].value = "300"; parts["radius-number"].emit("input");
    assert.equal(parts["radius-number"].value, "160");
    parts["radius-number"].value = ""; parts["radius-number"].emit("blur");
    assert.equal(parts["radius-number"].value, "1");
});

test("place failures offer retry and missing places leave the universal search usable", async () => {
    const { parts, requests } = setup({ nearby: null, query: "Gaunacaste" });
    requests[0].reject(new Error("offline")); await flush();
    assert.equal(parts.more.textContent, "Try again");
    parts.more.emit("click"); requests[1].resolve({ error: "no_results" }); await flush();
    assert.equal(parts.more.hidden, true);
    assert.match(parts.count.textContent, /No search results for Gaunacaste/);
    assert.equal(parts.distance.hidden, true);
});

test("radius preferences save in order and browser history restores the server-rendered entry", async () => {
    const { parts, requests, saves, window } = setup({ deferSaves: true });
    for (const radius of [20, 40]) {
        parts["radius-slider"].value = String(radius); parts["radius-slider"].emit("input");
        requests.at(-1).resolve({ html: "Cards", total: 2, next_page: null }); await flush();
    }
    assert.equal(saves.length, 1);
    saves[0].resolve({ saved: true }); await flush();
    assert.equal(JSON.parse(saves[1].options.body).radius, 40);
    window.emit("popstate"); assert.equal(window.reloaded, true);
});

test("regional results paginate without showing radius controls", async () => {
    const { parts, requests } = setup({ nearby: null, location: "Canada" });
    assert.equal(parts.distance.hidden, true);
    assert.equal(requests.length, 0);
    parts.more.dataset.nextPage = 2; parts.more.emit("click");
    assert.match(requests[0].url, /location=Canada&page=2/);
    requests[0].resolve({ html: "More", total: 33, next_page: null }); await flush();
    assert.equal(parts.count.textContent, "33 results in Canada");
});
