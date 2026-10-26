const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(initial = "Canada", { deferSaves = false, initialNearby = null } = {}) {
    let document;
    function element() {
        return {
            value: "", hidden: false, disabled: false, dataset: {}, attrs: {}, children: [], handlers: {}, textContent: "",
            set innerHTML(value) { this.html = value; this.children = []; },
            get innerHTML() { return this.html || ""; },
            replaceChildren() { this.children = []; this.html = ""; },
            appendChild(child) { this.children.push(child); },
            insertAdjacentHTML(_where, html) { this.html = (this.html || "") + html; },
            addEventListener(type, callback) { (this.handlers[type] ||= []).push(callback); },
            emit(type, event = {}) { for (const callback of this.handlers[type] || []) callback(event); },
            setAttribute(key, value) { this.attrs[key] = value; },
            removeAttribute(key) { delete this.attrs[key]; },
            focus() { document.activeElement = this; },
            scrollIntoView() {}, contains(target) { return target === this || this.children.includes(target); },
        };
    }
    const names = [
        "input", "suggestions", "tag", "location", "clear", "results", "count", "more",
        "feed-frame", "advanced-frame", "advanced-open", "advanced-back", "nearby-form",
        "radius-slider", "radius-number", "place", "nearby-error", "nearby-submit",
        "initial-nearby",
    ];
    const parts = Object.fromEntries(names.map(name => [name, element()]));
    parts.input.hidden = Boolean(initial);
    parts.input.disabled = Boolean(initial);
    parts.tag.hidden = !initial;
    parts["advanced-frame"].hidden = true;
    parts["radius-slider"].value = "50";
    parts["radius-number"].value = "50";
    parts["nearby-error"].hidden = true;
    parts["nearby-submit"].textContent = "Search";
    parts["initial-nearby"].textContent = JSON.stringify(initialNearby);
    const units = [element(), element()];
    units[0].value = "mi";
    units[0].checked = true;
    units[1].value = "km";
    units[1].checked = false;
    const search = element();
    search.contains = target => [parts.input, parts.clear, ...parts.suggestions.children].includes(target);
    const root = element();
    root.dataset.location = initial;
    root.querySelector = selector => selector === ".explore-search" ? search : parts[selector.match(/data-explore-(.+)\]/)[1]];
    root.querySelectorAll = selector => selector === "[data-explore-unit]" ? units : [];
    document = element();
    document.querySelector = () => root;
    document.createElement = element;
    const window = element();
    window.location = { href: "http://localhost/explore" };
    window.history = {
        pushState(_state, _unused, url) { window.location.href = String(url); },
        replaceState(_state, _unused, url) { window.location.href = String(url); },
        back() {},
    };
    window.setTimeout = () => 1;
    window.clearTimeout = () => {};
    const requests = [];
    const saves = [];
    const context = vm.createContext({
        document, window, URL, URLSearchParams, AbortController,
        debounce(fn) { fn.cancel = () => {}; return fn; },
        initStaticMaps() {},
        fetchJson(url, options) {
            if (url === "/api/explore/location") {
                return new Promise((resolve, reject) => {
                    saves.push({ url, options, resolve, reject });
                    if (!deferSaves) resolve({ location: JSON.parse(options.body).location });
                });
            }
            return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/explore.js"), "utf8"), context);
    document.emit("DOMContentLoaded");
    return { parts, units, requests, saves, window, document };
}

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("clearing a selected location unlocks search and selection locks it again", async () => {
    const { parts, requests, window, document } = setup();
    assert.equal(parts.input.disabled, true);
    assert.equal(requests.length, 0); // Server-rendered feed needs no duplicate request.
    parts.clear.emit("click");
    assert.equal(parts.input.disabled, false);
    assert.equal(parts.tag.hidden, true);
    assert.equal(document.activeElement, parts.input);
    assert.match(window.location.href, /location=$/);
    assert.equal(requests.length, 0);
    assert.match(parts.results.innerHTML, /Where will you dive next/);
    parts.input.value = "Komodo";
    parts.input.emit("input");
    requests[0].resolve(["Komodo National Park"]);
    await flush();
    assert.equal(parts.suggestions.hidden, false);
    parts.input.emit("keydown", { key: "ArrowDown", preventDefault() {} });
    assert.equal(parts.input.attrs["aria-activedescendant"], "exploreLocation-0");
    parts.input.emit("keydown", { key: "Enter", preventDefault() {} });
    assert.equal(parts.input.disabled, true);
    assert.equal(parts.input.hidden, true);
    assert.equal(parts.location.textContent, "Komodo National Park");
    assert.equal(parts.suggestions.hidden, true);
    assert.equal(document.activeElement, parts.clear);
    requests[1].resolve({ html: "Komodo cards", total: 42, next_page: 2 });
    await flush();
    assert.equal(parts.results.innerHTML, "Komodo cards");
    assert.equal(parts.count.textContent, "42 dive sites in Komodo National Park");
    assert.equal(parts.more.hidden, false);
});

test("stale search results and Escape cannot reopen dismissed suggestions", async () => {
    const { parts, requests } = setup("");
    parts.input.focus();
    parts.input.value = "Can";
    parts.input.emit("input");
    parts.input.value = "Kom";
    parts.input.emit("input");
    assert.equal(requests[0].options.signal.aborted, true);
    requests[1].resolve(["Komodo National Park"]);
    await flush();
    requests[0].resolve(["Canada"]);
    await flush();
    assert.equal(parts.suggestions.children[0].textContent, "Komodo National Park");
    parts.input.emit("keydown", { key: "Escape" });
    assert.equal(parts.suggestions.hidden, true);
    assert.equal(parts.input.attrs["aria-expanded"], "false");
});

test("a stale location feed cannot replace current results, and pagination appends", async () => {
    const { parts, requests, window } = setup();
    parts.clear.emit("click");
    window.location.href = "http://localhost/explore?location=Canada";
    window.emit("popstate");
    window.location.href = "http://localhost/explore?location=Komodo+National+Park";
    window.emit("popstate");
    assert.equal(requests[0].options.signal.aborted, true);
    requests[1].resolve({ html: "First cards", total: 42, next_page: 2 });
    await flush();
    requests[0].resolve({ html: "Stale cards", total: 0, next_page: null });
    await flush();
    assert.equal(parts.results.innerHTML, "First cards");
    parts.more.emit("click");
    assert.match(requests[2].url, /page=2/);
    requests[2].resolve({ html: " More cards", total: 42, next_page: null });
    await flush();
    assert.equal(parts.results.innerHTML, "First cards More cards");
    assert.equal(parts.more.hidden, true);
});

test("failed feeds offer retry and failed suggestions allow another search", async () => {
    const { parts, requests, window } = setup();
    parts.clear.emit("click");
    window.location.href = "http://localhost/explore?location=Canada";
    window.emit("popstate");
    requests[0].reject(new Error("offline"));
    await flush();
    assert.equal(parts.more.textContent, "Try again");
    assert.equal(parts.more.hidden, false);
    parts.more.emit("click");
    requests[1].resolve({ html: "Choose a location", total: 0, next_page: null });
    await flush();
    parts.clear.emit("click");
    parts.input.value = "Can";
    parts.input.emit("input");
    requests[2].reject(new Error("offline"));
    await flush();
    assert.match(parts.suggestions.innerHTML, /search locations/);
    parts.input.emit("input");
    requests[3].resolve(["Canada"]);
    await flush();
    assert.equal(parts.suggestions.children[0].textContent, "Canada");
});

test("explicit selections and clearing are remembered without saving browser history navigation", async () => {
    const { parts, requests, saves, window } = setup();
    assert.equal(saves.length, 0);
    parts.clear.emit("click");
    assert.deepEqual(JSON.parse(saves[0].options.body), { location: "" });
    assert.equal(saves[0].options.keepalive, true);
    assert.equal(saves[0].options.method, "POST");
    await flush();
    parts.input.value = "Komodo";
    parts.input.emit("input");
    requests[0].resolve(["Komodo National Park"]);
    await flush();
    parts.suggestions.children[0].emit("click");
    assert.deepEqual(JSON.parse(saves[1].options.body), { location: "Komodo National Park" });
    window.location.href = "http://localhost/explore?location=Canada";
    window.emit("popstate");
    assert.equal(saves.length, 2);
});

test("rapid selection changes save in order and preference failures do not block the feed", async () => {
    const { parts, saves } = setup("Canada", { deferSaves: true });
    parts.clear.emit("click");
    parts.clear.emit("click");
    assert.equal(saves.length, 1);
    saves[0].reject(new Error("offline"));
    await flush();
    assert.equal(saves.length, 2);
    saves[1].resolve({ location: "" });
    await flush();
    assert.equal(parts.input.disabled, false);
});

test("advanced search keeps radius controls in sync and shows no-result feedback in its frame", async () => {
    const { parts, units, requests, document } = setup("");
    parts["advanced-open"].emit("click");
    assert.equal(parts["feed-frame"].hidden, true);
    assert.equal(parts["advanced-frame"].hidden, false);
    assert.notEqual(document.activeElement, parts.place);
    parts["radius-slider"].value = "72";
    parts["radius-slider"].emit("input");
    assert.equal(parts["radius-number"].value, "72");
    units[0].checked = false;
    units[1].checked = true;
    units[1].emit("change");
    assert.equal(parts["radius-number"].value, 116);
    assert.equal(parts["radius-slider"].max, 160);
    parts.place.value = "Gaunacaste";
    parts["nearby-form"].emit("submit", { preventDefault() {} });
    assert.deepEqual(JSON.parse(requests[0].options.body), {
        query: "Gaunacaste", radius: 116, unit: "km",
    });
    requests[0].resolve({ error: "no_results", query: "Gaunacaste" });
    await flush();
    assert.equal(parts["advanced-frame"].hidden, false);
    assert.equal(parts["nearby-error"].hidden, false);
    assert.equal(parts["nearby-error"].textContent, "No search results for Gaunacaste");
});

test("advanced search returns to the feed using the API display name as the removable tag", async () => {
    const { parts, requests, window, document } = setup("Canada");
    parts["advanced-open"].emit("click");
    parts.place.value = "Guanacaste";
    parts["radius-number"].value = "50";
    parts["nearby-form"].emit("submit", { preventDefault() {} });
    requests[0].resolve({
        html: "Nearby cards", total: 3, next_page: 2,
        query: "Guanacaste", radius: 50, unit: "mi",
        place: {
            display_name: "Guanacaste, Costa Rica",
            latitude: 10.3788441, longitude: -85.4338287,
        },
    });
    await flush();
    assert.equal(parts["advanced-frame"].hidden, true);
    assert.equal(parts["feed-frame"].hidden, false);
    assert.equal(parts.location.textContent, "Guanacaste, Costa Rica");
    assert.equal(parts.clear.attrs["aria-label"], "Remove location Guanacaste, Costa Rica");
    assert.equal(parts.results.innerHTML, "Nearby cards");
    assert.equal(parts.count.textContent, "3 dive sites within 50 miles of Guanacaste, Costa Rica");
    assert.equal(document.activeElement, parts.clear);
    assert.match(window.location.href, /display=Guanacaste%2C\+Costa\+Rica/);
    parts.more.emit("click");
    assert.match(requests[1].url, /display_name=Guanacaste%2C\+Costa\+Rica/);
    requests[1].resolve({ html: " More", total: 3, next_page: null });
    await flush();
    assert.equal(parts.results.innerHTML, "Nearby cards More");
});

test("a saved advanced result restores its tag and form without another request", () => {
    const initialNearby = {
        query: "Guanacaste", displayName: "Guanacaste Province, Costa Rica",
        latitude: 10.63, longitude: -85.44, radius: 35, unit: "mi",
    };
    const { parts, units, requests, document } = setup("", { initialNearby });
    assert.equal(parts.tag.hidden, false);
    assert.equal(parts.location.textContent, initialNearby.displayName);
    assert.equal(parts.input.disabled, true);
    assert.equal(requests.length, 0);
    parts["advanced-open"].emit("click");
    assert.equal(parts.place.value, "Guanacaste");
    assert.equal(parts["radius-number"].value, 35);
    assert.equal(units[0].checked, true);
    assert.notEqual(document.activeElement, parts.place);
});
