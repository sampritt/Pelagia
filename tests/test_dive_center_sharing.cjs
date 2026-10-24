const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(navigator = {}) {
    const element = () => ({
        handlers: {}, attributes: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
        focus() { this.focused = true; }, select() { this.selected = true; },
        setSelectionRange(start, end) { this.selection = [start, end]; },
    });
    const share = element(), status = element(), fallback = element(), link = element();
    share.href = "https://pelagia.example/share/dive-center/1";
    share.dataset = {shareTitle: "Shark Bay Dive Center · Dive center on Pelagia"};
    link.value = share.href;
    fallback.hidden = true;
    const host = element();
    host.querySelector = selector => ({
        "[data-center-share]": share, "[data-center-share-status]": status,
        "[data-center-share-fallback]": fallback, "[data-center-share-link]": link,
    })[selector];
    const document = element();
    document.querySelector = selector => selector === "[data-center-sharing]" ? host : null;
    const context = vm.createContext({document, window: {isSecureContext: true}, navigator});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveCenterSharing()", context);
    const event = {button: 0, preventDefault() { this.prevented = true; }};
    return {share, status, fallback, link, event};
}

test("dive center native sharing immediately uses the public center URL and title", async () => {
    let payload;
    const state = setup({share(data) { payload = data; return Promise.resolve(); }});
    const pending = state.share.handlers.click(state.event);
    assert.equal(payload.url, state.share.href);
    assert.equal(payload.title, state.share.dataset.shareTitle);
    assert.equal(state.event.prevented, true);
    await pending;
    assert.equal(state.status.textContent, "Dive center shared.");
});

test("unsupported sharing copies the public center URL with center-specific feedback", async () => {
    let copied;
    const state = setup({clipboard: {writeText: async value => { copied = value; }}});
    await state.share.handlers.click(state.event);
    assert.equal(copied, state.share.href);
    assert.equal(state.status.textContent, "Link copied. Ready to share this dive center.");
});

test("center share cancellation stays quiet and clipboard failure exposes the link", async () => {
    const cancelled = setup({share: async () => { throw Object.assign(new Error(), {name: "AbortError"}); }});
    await cancelled.share.handlers.click(cancelled.event);
    assert.equal(cancelled.status.textContent, "");
    assert.equal(cancelled.fallback.hidden, true);
    const manual = setup();
    await manual.share.handlers.click(manual.event);
    assert.equal(manual.fallback.hidden, false);
    assert.equal(manual.link.focused, true);
    assert.equal(manual.link.selected, true);
    assert.deepEqual(manual.link.selection, [0, manual.share.href.length]);
    assert.equal(manual.status.textContent, "Copy this link to share the dive center.");
});
