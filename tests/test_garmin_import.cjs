const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(options = {}) {
    const element = () => ({handlers: {}, attributes: {}, hidden: true, textContent: "", value: "", focused: false,
        addEventListener(name, handler) { this.handlers[name] = handler; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; }, click() { this.clicked = true; }});
    const names = ["title", "back-label", "step", "brands", "upload", "choose", "file", "progress", "error", "garmin", "back", "close"];
    const parts = Object.fromEntries(names.map(name => [name, element()]));
    const trigger = element(), dialog = element();
    dialog.dataset = {importUrl: "/api/dive-import/garmin"};
    dialog.querySelector = selector => parts[selector.slice("[data-computer-import-".length, -1)];
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close?.(); };
    const classes = new Set();
    const document = {addEventListener() {}, querySelector: () => dialog,
        body: {style: {top: ""}, classList: {add: value => classes.add(value), remove: value => classes.delete(value)}}};
    const window = {handlers: {}, scrollX: 0, scrollY: 240, location: {href: "https://pelagia.test/dive/new"},
        addEventListener(name, handler) { this.handlers[name] = handler; },
        scrollTo({left, top}) { this.scrollX = left; this.scrollY = top; }};
    const entries = [null];
    let index = 0;
    window.history = {state: null,
        pushState(state) { entries.splice(++index); entries.push(state); this.state = state; },
        go(delta) { index += delta; this.state = entries[index]; window.handlers.popstate(); },
        back() { this.go(-1); }};
    let nextTimer = 0;
    const timers = new Map();
    window.setTimeout = fn => { timers.set(++nextTimer, fn); return nextTimer; };
    window.clearTimeout = timer => timers.delete(timer);
    const requests = [], applied = [], pickers = [];
    if (options.picker) window.showOpenFilePicker = async config => {
        pickers.push(config);
        return options.picker(config);
    };
    const navigator = {onLine: true};
    const result = {fields: {depth_m: 21.038}, computer_data: {depth_profile: [{elapsed_seconds: 0, depth_m: 1.602}]}, notices: []};
    const context = vm.createContext({document, window, navigator, AbortController,
        fetch: async (url, config) => {
            requests.push({url, ...config});
            return options.fetch ? options.fetch(url, config) : {ok: true, json: async () => result};
        }});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    context.form = {querySelector: () => trigger};
    context.apply = data => applied.push(data);
    vm.runInContext("initDiveComputerImport(form, apply)", context);
    const open = () => { trigger.handlers.click(); parts.garmin.handlers.click(); };
    const file = {name: "dive.fit", size: 100};
    const select = async (chosen = file) => { parts.file.files = [chosen]; await parts.file.handlers.change(); };
    return {parts, trigger, dialog, document, window, classes, requests, applied, pickers, navigator, timers, open, select, file};
}

test("brand and Garmin screens support Back, Escape, focus, and scroll restoration", () => {
    const state = setup();
    state.trigger.handlers.click();
    assert.equal(state.parts.brands.hidden, false);
    assert.equal(state.parts.upload.hidden, true);
    assert.equal(state.dialog.open, true);
    assert.equal(state.parts.title.focused, true);
    assert.equal(state.document.body.style.top, "-240px");
    state.parts.garmin.handlers.click();
    assert.equal(state.parts.upload.hidden, false);
    assert.equal(state.parts.title.textContent, "Import from Garmin");
    state.parts.back.handlers.click();
    assert.equal(state.parts.brands.hidden, false);
    let prevented = false;
    state.dialog.handlers.cancel({preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(state.dialog.open, false);
    assert.equal(state.document.body.style.top, "");
    assert.equal(state.window.scrollY, 240);
    assert.equal(state.trigger.focused, true);
    assert.equal(state.classes.size, 0);
});

test("native selection immediately uploads raw FIT bytes and returns to the mounted form", async () => {
    const state = setup();
    state.open();
    await state.parts.choose.handlers.click();
    assert.equal(state.parts.file.clicked, true);
    await state.select();
    assert.equal(state.requests.length, 1);
    assert.equal(state.requests[0].body, state.file);
    assert.equal(state.requests[0].headers["Content-Type"], "application/octet-stream");
    assert.equal(state.requests[0].cache, "no-store");
    assert.equal(state.applied.length, 1);
    assert.equal(state.dialog.open, false);
    assert.equal(state.window.history.state, null);
    assert.equal(state.timers.size, 0);
});

test("enhanced picker requests Downloads, remembers its directory ID, and accepts uppercase FIT", async () => {
    const file = {name: "DIVE.FIT", size: 100};
    const state = setup({picker: async () => [{getFile: async () => file}]});
    state.open();
    await state.parts.choose.handlers.click();
    assert.equal(state.pickers[0].startIn, "downloads");
    assert.equal(state.pickers[0].id, "pelagia-garmin-fit");
    assert.equal(state.requests[0].body, file);
    assert.equal(state.applied.length, 1);
});

test("picker cancellation leaves the form untouched; unsupported enhanced pickers offer native retry", async () => {
    let denied = false;
    const state = setup({picker: async () => {
        const error = new Error("Picker unavailable");
        error.name = denied ? "SecurityError" : "AbortError";
        throw error;
    }});
    state.open();
    await state.parts.choose.handlers.click();
    assert.equal(state.parts.error.hidden, true);
    assert.equal(state.applied.length, 0);
    denied = true;
    await state.parts.choose.handlers.click();
    assert.equal(state.parts.error.hidden, false);
    await state.parts.choose.handlers.click();
    assert.equal(state.parts.file.clicked, true);
});

test("wrong extensions, oversized files, and offline imports do not submit", async () => {
    const state = setup();
    state.open();
    await state.select({name: "dive.txt", size: 10});
    assert.match(state.parts.error.textContent, /ending in .fit/);
    await state.select({name: "dive.fit", size: 10 * 1024 * 1024 + 1});
    assert.match(state.parts.error.textContent, /10 MiB/);
    state.navigator.onLine = false;
    await state.select();
    assert.match(state.parts.error.textContent, /offline/);
    assert.equal(state.requests.length, 0);
    assert.equal(state.applied.length, 0);
});

test("server rejection preserves the form and permits retry with the same file", async () => {
    let succeed = false;
    const state = setup({fetch: async () => ({ok: succeed, json: async () => succeed ? {fields: {}} : {error: "Only single-gas dives are supported."}})});
    state.open();
    await state.select();
    assert.equal(state.dialog.open, true);
    assert.equal(state.parts.choose.disabled, false);
    assert.match(state.parts.error.textContent, /single-gas/);
    assert.equal(state.applied.length, 0);
    succeed = true;
    await state.select();
    assert.equal(state.applied.length, 1);
    assert.equal(state.dialog.open, false);
});

test("leaving during parsing aborts the request and ignores late responses", async () => {
    let finish;
    const state = setup({fetch: () => new Promise(resolve => { finish = resolve; })});
    state.open();
    const work = state.select();
    assert.equal(state.parts.choose.disabled, true);
    state.parts.back.handlers.click();
    assert.equal(state.requests[0].signal.aborted, true);
    finish({ok: true, json: async () => ({fields: {}})});
    await work;
    assert.equal(state.applied.length, 0);
    assert.equal(state.parts.brands.hidden, false);
    assert.equal(state.timers.size, 0);
});
