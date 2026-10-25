const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(responses = []) {
    const handlers = {};
    const input = value => ({value, handlers: {}, addEventListener(name, handler) { this.handlers[name] = handler; }});
    const latitude = input("-0.5667634");
    const longitude = input("-90.14297416");
    const siteId = input("1");
    const options = ["fresh", "salt"].map(value => ({value, checked: false, dataset: {optionLabel: value === "salt" ? "Salt" : "Fresh"},
        addEventListener(name, handler) { this.handler = handler; }}));
    const label = {textContent: "-"};
    const form = {querySelectorAll: () => options, querySelector: () => label};
    const requests = [];
    const context = vm.createContext({document: {addEventListener(name, handler) { handlers[name] = handler; }},
        window: {setTimeout(handler) { handler(); return 1; }, clearTimeout() {}}, URLSearchParams, console,
        fetch: async url => { requests.push(url); return responses.shift() || {ok: true, json: async () => ({status: "complete", water_type: "salt"})}; }});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    context.form = form; context.latitude = latitude; context.longitude = longitude; context.siteId = siteId;
    vm.runInContext("lookup = initWaterTypeLookup(form, latitude, longitude, siteId)", context);
    return {context, latitude, longitude, siteId, options, label, requests};
}

test("valid coordinates prefill Salt for an OCEAN classification", async () => {
    const state = setup();
    await state.context.lookup.lookup();
    assert.equal(state.options[1].checked, true);
    assert.equal(state.label.textContent, "Salt");
    assert.equal(state.requests[0], "/api/water-type?latitude=-0.5667634&longitude=-90.14297416&site_id=1");
});

test("non-ocean classifications prefill Fresh and failures preserve the selection", async () => {
    const state = setup([
        {ok: true, json: async () => ({status: "complete", water_type: "fresh"})},
        {ok: false, json: async () => ({status: "unavailable"})},
    ]);
    await state.context.lookup.lookup();
    assert.equal(state.options[0].checked, true);
    state.latitude.value = "20.137461";
    state.longitude.value = "-87.5782533";
    await state.context.lookup.lookup();
    assert.equal(state.options[0].checked, true);
    assert.equal(state.label.textContent, "Fresh");
});

test("invalid coordinates do not call the API", async () => {
    const state = setup();
    state.latitude.value = "91";
    await state.context.lookup.lookup();
    assert.equal(state.requests.length, 0);
});

test("clearing coordinates prevents an older lookup from changing Water type", async () => {
    let finish;
    const response = new Promise(resolve => { finish = resolve; });
    const state = setup([response]);
    const pending = state.context.lookup.lookup();
    state.latitude.value = "";
    state.latitude.handlers.input();
    finish({ok: true, json: async () => ({status: "complete", water_type: "salt"})});
    await pending;
    assert.equal(state.options.some(option => option.checked), false);
    assert.equal(state.label.textContent, "-");
});
