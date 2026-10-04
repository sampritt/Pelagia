const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(navigator = {}, secure = true, options = {}) {
    const element = () => ({
        handlers: {}, hidden: false, textContent: "", value: "",
        addEventListener(name, callback) { this.handlers[name] = callback; },
        focus() { this.focused = true; },
        select() { this.selected = true; },
        setSelectionRange(start, end) { this.selection = [start, end]; },
    });
    const parts = Object.fromEntries(["link", "copy", "copy-label", "save", "native", "status", "preview", "close"].map(name => [name, element()]));
    const dialog = element();
    dialog.querySelector = selector => parts[selector.match(/data-share-([a-z-]+)/)[1]];
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    const document = element();
    document.querySelector = () => dialog;
    const downloads = [];
    document.body = { appendChild() {} };
    document.createElement = () => ({click() { downloads.push(this); }, remove() { this.removed = true; }});
    const context = vm.createContext({
        document, navigator, File, AbortSignal,
        fetch: options.fetch || (async () => ({ok: true, blob: async () => new Blob(["image"], {type: "image/jpeg"})})),
        window: {isSecureContext: secure, matchMedia: () => ({matches: !!options.mobile})},
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveSharing()", context);
    const trigger = element();
    trigger.dataset = {
        shareUrl: "https://pelagia.example/share/dive/7",
        shareImage: "https://pelagia.example/share/dive/7/preview.jpg",
        shareDownload: "https://pelagia.example/share/dive/7/preview.jpg?download=1",
        shareTitle: "Blue Corner",
    };
    const event = {target: {closest: () => trigger}, preventDefault() { this.prevented = true; }};
    const open = () => document.handlers.click(event);
    return {parts, dialog, trigger, event, open, downloads};
}

test("native sharing is invoked immediately with the permanent URL", async () => {
    let payload;
    const state = setup({share(data) { payload = data; return Promise.resolve(); }});
    state.open();
    assert.equal(state.parts.native.hidden, false);
    const promise = state.parts.native.handlers.click();
    assert.equal(payload.url, state.trigger.dataset.shareUrl);
    assert.equal(payload.title, "Check out my logged dive at Blue Corner");
    assert.equal(payload.text, "Check out my logged dive at Blue Corner");
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
    assert.equal(state.parts["copy-label"].textContent, "Copied");
    assert.equal(state.parts.link.hidden, true);
    state.dialog.close();
    assert.equal(state.trigger.focused, true);
    state.open();
    assert.equal(state.parts["copy-label"].textContent, "Copy link");
    assert.equal(state.parts.status.textContent, "");
});

test("unavailable clipboard leaves a focused, selected link for manual copying", async () => {
    for (const navigator of [{}, {clipboard: {writeText: () => Promise.reject(new Error("denied"))}}]) {
        const state = setup(navigator);
        state.open();
        await state.parts.copy.handlers.click();
        assert.equal(state.parts.link.hidden, false);
        assert.equal(state.parts.link.focused, true);
        assert.equal(state.parts.link.selected, true);
        assert.deepEqual(state.parts.link.selection, [0, state.trigger.dataset.shareUrl.length]);
        assert.match(state.parts.status.textContent, /Select and copy/);
    }
});

test("insecure contexts explain the More fallback; modified links retain browser behavior", async () => {
    const state = setup({share() {}}, false);
    state.event.ctrlKey = true;
    state.open();
    assert.equal(state.dialog.open, undefined);
    assert.equal(state.event.prevented, undefined);
    state.event.ctrlKey = false;
    state.open();
    assert.equal(state.parts.native.hidden, false);
    await state.parts.native.handlers.click();
    assert.match(state.parts.status.textContent, /Use Copy link/);
});

test("Save downloads the thumbnail attachment on desktop", async () => {
    const state = setup();
    state.open();
    await state.parts.save.handlers.click();
    assert.equal(state.downloads.length, 1);
    assert.equal(state.downloads[0].href, state.trigger.dataset.shareDownload);
    assert.equal(state.downloads[0].download, "pelagia-dive.jpg");
    assert.equal(state.downloads[0].removed, true);
    assert.equal(state.parts.status.textContent, "Image download started.");
});

const flushPreparation = () => new Promise(resolve => setImmediate(resolve));

test("mobile Save preloads a JPEG and shares the file immediately on click", async () => {
    let payload;
    const state = setup({canShare: data => data.files[0].type === "image/jpeg", share(data) { payload = data; return Promise.resolve(); }}, true, {mobile: true});
    state.open();
    assert.equal(state.parts.save.disabled, true);
    await flushPreparation();
    assert.equal(state.parts.save.disabled, false);
    const sharing = state.parts.save.handlers.click();
    assert.equal(payload.files.length, 1);
    assert.equal(payload.files[0].name, "pelagia-dive.jpg");
    assert.equal(payload.files[0].type, "image/jpeg");
    assert.equal(payload.url, undefined);
    await sharing;
    assert.equal(state.downloads.length, 0);
});

test("mobile Save cancellation does not download; failed sharing falls back to download", async () => {
    for (const errorName of ["AbortError", "NotAllowedError"]) {
        const state = setup({canShare: () => true, share: () => Promise.reject(Object.assign(new Error(), {name: errorName}))}, true, {mobile: true});
        state.open();
        await flushPreparation();
        await state.parts.save.handlers.click();
        assert.equal(state.downloads.length, errorName === "AbortError" ? 0 : 1);
        if (errorName === "AbortError") assert.equal(state.parts.status.textContent, "");
    }
});

test("unavailable file sharing or failed image preparation leaves Save working", async () => {
    for (const options of [{mobile: true}, {mobile: true, fetch: async () => ({ok: false})}, {mobile: true, fetch: () => Promise.reject(new Error("offline"))}]) {
        const state = setup({canShare: () => false, share() { throw new Error("Must use download"); }}, true, options);
        state.open();
        await flushPreparation();
        assert.equal(state.parts.save.disabled, false);
        await state.parts.save.handlers.click();
        assert.equal(state.downloads.length, 1);
    }
});

test("an earlier image request cannot overwrite the current dive's image", async () => {
    const responses = [];
    let payload;
    const state = setup({canShare: () => true, share(data) { payload = data; return Promise.resolve(); }}, true, {
        mobile: true, fetch: () => new Promise(resolve => responses.push(resolve)),
    });
    state.open();
    state.dialog.close();
    state.trigger.dataset.shareImage = "https://pelagia.example/share/dive/8/preview.jpg";
    state.open();
    responses[1]({ok: true, blob: async () => new Blob(["current image"])});
    await flushPreparation();
    responses[0]({ok: true, blob: async () => new Blob(["earlier image"])});
    await flushPreparation();
    await state.parts.save.handlers.click();
    assert.equal(await payload.files[0].text(), "current image");
});
