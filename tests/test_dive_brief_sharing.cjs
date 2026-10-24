const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(navigator = {}, secure = true) {
    const element = () => ({
        handlers: {}, attributes: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
        focus() { this.focused = true; },
        select() { this.selected = true; },
        setSelectionRange(start, end) { this.selection = [start, end]; },
    });
    const share = element(), status = element(), fallback = element(), link = element();
    share.href = "https://pelagia.example/share/brief/2026-10-22";
    share.dataset = {shareTitle: "The Dive Brief · Thursday, October 22, 2026"};
    link.value = share.href;
    status.textContent = "";
    fallback.hidden = true;
    const reader = element();
    reader.dataset = {briefPublic: "true"};
    reader.querySelector = selector => ({
        "[data-brief-share]": share,
        "[data-brief-share-status]": status,
        "[data-brief-share-fallback]": fallback,
        "[data-brief-share-link]": link,
    })[selector];
    const document = element();
    document.querySelector = () => reader;
    const window = {};
    window.isSecureContext = secure;
    const context = vm.createContext({document, window, navigator});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveBriefSharing()", context);
    const click = (overrides = {}) => ({button: 0, preventDefault() { this.prevented = true; }, ...overrides});
    return {share, status, fallback, link, reader, context, click};
}

test("native share opens immediately with this edition's public URL", async () => {
    let payload;
    const state = setup({share(data) { payload = data; return Promise.resolve(); }});
    const event = state.click();
    const pending = state.share.handlers.click(event);
    assert.equal(payload.url, state.share.href);
    assert.equal(payload.title, state.share.dataset.shareTitle);
    assert.equal(event.prevented, true);
    await pending;
    assert.equal(state.status.textContent, "Brief shared.");
    assert.equal(state.fallback.hidden, true);
    assert.equal(state.share.attributes["aria-busy"], undefined);
});

test("cancelled native share stays quiet and does not copy the link", async () => {
    let copies = 0;
    const state = setup({
        share: async () => { throw Object.assign(new Error(), {name: "AbortError"}); },
        clipboard: {writeText: async () => { copies++; }},
    });
    await state.share.handlers.click(state.click());
    assert.equal(copies, 0);
    assert.equal(state.status.textContent, "");
    assert.equal(state.fallback.hidden, true);
});

test("unavailable or denied native sharing copies the public edition link", async () => {
    for (const mode of ["unsupported", "denied", "insecure"]) {
        let copied;
        const navigator = {clipboard: {writeText: async value => { copied = value; }}};
        if (mode !== "unsupported") navigator.share = async () => { throw new Error("Unavailable"); };
        const state = setup(navigator, mode !== "insecure");
        await state.share.handlers.click(state.click());
        assert.equal(copied, state.share.href);
        assert.match(state.status.textContent, /Link copied/);
        assert.equal(state.fallback.hidden, true);
    }
});

test("clipboard failure exposes and selects a link for manual sharing", async () => {
    for (const navigator of [{}, {clipboard: {writeText: async () => { throw new Error("Denied"); }}}]) {
        const state = setup(navigator);
        await state.share.handlers.click(state.click());
        assert.equal(state.fallback.hidden, false);
        assert.equal(state.link.focused, true);
        assert.equal(state.link.selected, true);
        assert.deepEqual(state.link.selection, [0, state.share.href.length]);
        assert.match(state.status.textContent, /Copy this link/);
    }
});

test("repeated clicks do not open concurrent share sheets and sharing can retry", async () => {
    let calls = 0, finish;
    const state = setup({share() { calls++; return new Promise(resolve => { finish = resolve; }); }});
    const first = state.share.handlers.click(state.click());
    await state.share.handlers.click(state.click());
    assert.equal(calls, 1);
    finish(); await first;
    const second = state.share.handlers.click(state.click());
    assert.equal(calls, 2);
    finish(); await second;
});

test("modified clicks preserve the public link's native browser behavior", async () => {
    const state = setup({share() { throw new Error("Must not share"); }});
    for (const override of [{ctrlKey: true}, {metaKey: true}, {shiftKey: true}, {altKey: true}, {button: 1}]) {
        const event = state.click(override);
        await state.share.handlers.click(event);
        assert.equal(event.prevented, undefined);
    }
});

test("public reader does not install Feed or Escape navigation", () => {
    const state = setup();
    vm.runInContext("initDiveBrief()", state.context);
    assert.deepEqual(state.reader.handlers, {});
});
