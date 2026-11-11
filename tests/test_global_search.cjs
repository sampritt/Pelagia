const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");
const source = fs.readFileSync("pelagia/static/js/app.js", "utf8");
const searchSource = source.slice(source.indexOf("function initGlobalSearch()"), source.indexOf("\nconst formatSacRate"));
function element() {
    return { value: "", hidden: false, children: [], handlers: {}, attrs: {},
        addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
        emit(type, event = {}) { for (const fn of this.handlers[type] || []) fn(event); },
        setAttribute(key, value) { this.attrs[key] = value; }, removeAttribute(key) { delete this.attrs[key]; },
        replaceChildren() { this.children = []; }, appendChild(child) { this.children.push(child); },
        scrollIntoView() {},
    };
}
function setup(publicSearch = false) {
    const input = element(), results = element(), search = element(), document = element();
    const requests = [], navigations = [];
    search.dataset = { publicSearch: String(publicSearch) };
    input.getBoundingClientRect = () => ({ bottom: 500 });
    results.style = { setProperty() {} };
    search.querySelector = selector => selector.includes("-input") ? input : results;
    search.contains = target => [input, search, ...results.children].includes(target);
    document.querySelector = () => search; document.createElement = element; document.activeElement = input;
    const window = { innerHeight: 900, addEventListener() {}, setTimeout: () => 1, clearTimeout() {}, location: { assign: url => navigations.push(url) } };
    const context = vm.createContext({
        document, window, URLSearchParams, AbortController,
        debounce(fn) { fn.cancel = () => {}; return fn; },
        escapeHtml(value) { return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"); },
        fetchJson(url, options) { return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })); },
    });
    vm.runInContext(searchSource + "\ninitGlobalSearch();", context);
    const type = value => { input.value = value; input.emit("input"); };
    const submit = () => search.emit("submit", { preventDefault() {} });
    return { input, results, search, document, requests, navigations, type, submit };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("typing beyond suggestions remains editable and shows a bold, escaped free-text action", async () => {
    const { type, requests, input, results, submit, navigations } = setup();
    type("Can"); requests[0].resolve([{ label: "Canada", type: "region", url: "/explore?location=Canada" }]); await flush();
    type("Canada <harbour>");
    assert.equal(results.hidden, true);
    requests[1].resolve([]); await flush();
    assert.match(results.children[0].innerHTML, /Show results for <strong>Canada &lt;harbour&gt;<\/strong>/);
    assert.equal(input.value, "Canada <harbour>");
    assert.equal(input.disabled, undefined);
    submit();
    assert.equal(navigations[0], "/explore?nearby=Canada+%3Charbour%3E");
});

test("Enter while a new query is loading submits the new text, never a stale suggestion", async () => {
    const { type, requests, submit, navigations } = setup();
    type("Can"); requests[0].resolve([{ label: "Canada", url: "/explore?location=Canada" }]); await flush();
    type("Canary Wharf"); submit();
    assert.equal(navigations[0], "/explore?nearby=Canary+Wharf");
    requests[1].resolve([]); await flush();
    assert.equal(navigations.length, 1);
});

test("keyboard choice saves a region before navigating to Explore", async () => {
    const { type, requests, input, results, submit, navigations } = setup();
    type("Kom"); requests[0].resolve([{ label: "Komodo National Park", type: "region", url: "/explore?location=Komodo+National+Park" }]); await flush();
    input.emit("keydown", { key: "ArrowDown", preventDefault() {} });
    input.emit("keydown", { key: "ArrowDown", preventDefault() {} });
    assert.equal(input.attrs["aria-activedescendant"], "globalSearchResult-1");
    assert.equal(results.children[1].attrs["aria-selected"], "true");
    submit();
    assert.equal(requests[1].url, "/api/explore/location");
    assert.deepEqual(JSON.parse(requests[1].options.body), { location: "Komodo National Park" });
    assert.equal(navigations.length, 0);
    requests[1].resolve({ location: "Komodo National Park" }); await flush();
    assert.equal(navigations[0], "/explore?location=Komodo+National+Park");
});

test("entity suggestions retain their own destinations and failed suggestions permit place search", async () => {
    const { type, requests, results, navigations } = setup();
    type("Maple"); requests[0].resolve([{ label: "Maple Reef", type: "site", url: "/dive-sites/1" }]); await flush();
    results.children[1].emit("click");
    assert.equal(navigations[0], "/dive-sites/1");
    type("Victoria"); requests[1].reject(new Error("offline")); await flush();
    results.children[0].emit("click");
    assert.equal(navigations[1], "/explore?nearby=Victoria");
});

test("stale responses and Escape cannot reopen dismissed results", async () => {
    const { type, input, requests, results } = setup();
    type("Can"); type("Kom");
    assert.equal(requests[0].options.signal.aborted, true);
    requests[1].resolve([{ label: "Komodo", url: "/explore?location=Komodo" }]); await flush();
    requests[0].resolve([{ label: "Canada", url: "/explore?location=Canada" }]); await flush();
    assert.match(results.children[1].innerHTML, /Komodo/);
    type("Victoria"); input.emit("keydown", { key: "Escape" });
    requests[2].resolve([]); await flush();
    assert.equal(results.hidden, true);
    assert.equal(input.attrs["aria-expanded"], "false");
});


test("ArrowUp starts at the last available suggestion", async () => {
    const { type, requests, input } = setup();
    type("reef"); requests[0].resolve([
        { label: "First Reef", url: "/dive-sites/1" },
        { label: "Last Reef", url: "/dive-sites/2" },
    ]); await flush();
    input.emit("keydown", { key: "ArrowUp", preventDefault() {} });
    assert.equal(input.attrs["aria-activedescendant"], "globalSearchResult-2");
});


test("Dauin always offers place search alongside site and center matches, and Enter searches the place", async () => {
    const { type, requests, results, submit, navigations } = setup();
    type("Dauin"); requests[0].resolve([
        { label: "Dauin Reef", type: "site", url: "/dive-sites/1" },
        { label: "Dauin Dive Center", type: "center", url: "/dive-centers/1" },
    ]); await flush();
    assert.equal(results.children.length, 3);
    assert.match(results.children[0].innerHTML, /Show results for <strong>Dauin<\/strong>/);
    assert.match(results.children[0].innerHTML, /Dive sites near this place/);
    submit();
    assert.equal(navigations[0], "/explore?nearby=Dauin");
});

test("a matching catalog region remains explicit while unselected Enter searches the typed place", async () => {
    const { type, requests, submit, navigations } = setup();
    type("Canada"); requests[0].resolve([{ label: "Canada", type: "region", url: "/explore?location=Canada" }]); await flush();
    submit();
    assert.equal(navigations[0], "/explore?nearby=Canada");
    assert.equal(requests.length, 1);
});


test("public autocomplete requests no accounts and navigates regions without saving a preference", async () => {
    const { type, requests, results, navigations } = setup(true);
    type("Canada");
    assert.equal(requests[0].url, "/api/search?q=Canada&public=1");
    requests[0].resolve([{ label: "Canada", type: "region", url: "/explore?location=Canada" }]);
    await flush();
    results.children[1].emit("click");
    assert.equal(requests.length, 1);
    assert.equal(navigations[0], "/explore?location=Canada");
});
