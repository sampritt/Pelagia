const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(navigator = {}, secure = true) {
    const element = () => ({
        handlers: {}, hidden: false, textContent: "", value: "",
        addEventListener(name, callback) { this.handlers[name] = callback; },
        focus() { this.focused = true; },
        select() { this.selected = true; },
        setSelectionRange(start, end) { this.selection = [start, end]; },
    });
    const parts = Object.fromEntries(["link", "copy", "native", "status", "preview", "open", "close"].map(name => [name, element()]));
    const dialog = element();
    dialog.querySelector = selector => parts[selector.match(/data-share-([a-z]+)/)[1]];
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    const document = element();
    document.querySelector = () => dialog;
    const context = vm.createContext({document, navigator, window: {isSecureContext: secure}});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveSharing()", context);
    const trigger = element();
    trigger.dataset = {
        shareUrl: "https://pelagia.example/share/dive/7",
        shareImage: "https://pelagia.example/share/dive/7/preview.jpg",
        shareTitle: "Blue Corner",
    };
    const event = {target: {closest: () => trigger}, preventDefault() { this.prevented = true; }};
    const open = () => document.handlers.click(event);
    return {parts, dialog, trigger, event, open};
}

test("native sharing is invoked immediately with the permanent URL", async () => {
    let payload;
    const state = setup({share(data) { payload = data; return Promise.resolve(); }});
    state.open();
    assert.equal(state.parts.native.hidden, false);
    const promise = state.parts.native.handlers.click();
    assert.equal(payload.url, state.trigger.dataset.shareUrl);
    assert.equal(payload.title, "Check out my logged dive at Blue Corner");
    await promise;
    assert.equal(state.parts.status.textContent, "Your dive link was shared.");
});

test("cancelling app sharing reports no false success; errors offer copying", async () => {
    for (const errorName of ["AbortError", "NotAllowedError"]) {
        const state = setup({share: () => Promise.reject(Object.assign(new Error(), {name: errorName}))});
        state.open();
        await state.parts.native.handlers.click();
        assert.equal(state.parts.status.textContent, errorName === "AbortError" ? "" : "App sharing is unavailable. You can copy the link instead.");
        assert.equal(state.parts.link.value, state.trigger.dataset.shareUrl);
    }
});

test("clipboard success copies the correct URL and resets when reopened", async () => {
    let copied;
    const state = setup({clipboard: {writeText: async value => { copied = value; }}});
    state.open();
    await state.parts.copy.handlers.click();
    assert.equal(copied, state.trigger.dataset.shareUrl);
    assert.equal(state.parts.copy.textContent, "Copied");
    state.dialog.close();
    assert.equal(state.trigger.focused, true);
    state.open();
    assert.equal(state.parts.copy.textContent, "Copy link");
    assert.equal(state.parts.status.textContent, "");
});

test("unavailable clipboard leaves a focused, selected link for manual copying", async () => {
    for (const navigator of [{}, {clipboard: {writeText: () => Promise.reject(new Error("denied"))}}]) {
        const state = setup(navigator);
        state.open();
        assert.equal(state.parts.native.hidden, true);
        await state.parts.copy.handlers.click();
        assert.equal(state.parts.link.focused, true);
        assert.equal(state.parts.link.selected, true);
        assert.deepEqual(state.parts.link.selection, [0, state.trigger.dataset.shareUrl.length]);
        assert.match(state.parts.status.textContent, /Select and copy/);
    }
});

test("insecure contexts hide native sharing; modified links retain browser behavior", () => {
    const state = setup({share() {}}, false);
    state.event.ctrlKey = true;
    state.open();
    assert.equal(state.dialog.open, undefined);
    assert.equal(state.event.prevented, undefined);
    state.event.ctrlKey = false;
    state.open();
    assert.equal(state.parts.native.hidden, true);
    assert.equal(state.parts.open.href, state.trigger.dataset.shareUrl);
});
