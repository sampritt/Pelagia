const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(navigator = {}, secure = true, options = {}) {
    const element = () => ({
        handlers: {}, hidden: false, textContent: "", value: "", dataset: {}, attributes: {}, style: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        setAttribute(name, value) { this.attributes[name] = value; },
        setPointerCapture(pointerId) { this.capturedPointer = pointerId; },
        focus() { this.focused = true; },
        select() { this.selected = true; },
        setSelectionRange(start, end) { this.selection = [start, end]; },
    });
    const parts = Object.fromEntries(["link", "copy", "copy-label", "save", "native", "status", "preview", "close", "carousel", "save-label", "counter"].map(name => [name, element()]));
    const styles = Array.from({length: 6}, element);
    const dialog = element();
    dialog.querySelector = selector => parts[selector.match(/data-share-([a-z-]+)/)[1]];
    dialog.querySelectorAll = () => styles;
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    const document = element();
    document.querySelector = () => dialog;
    const downloads = [];
    document.body = { appendChild() {} };
    document.createElement = () => ({click() { downloads.push(this); }, remove() { this.removed = true; }});
    const context = vm.createContext({
        document, navigator, File, AbortSignal, URL,
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
        shareTransparentImage: "https://pelagia.example/share/dive/7/transparent.png",
        shareTransparentDownload: "https://pelagia.example/share/dive/7/transparent.png?download=1",
        shareTitle: "Blue Corner",
    };
    const event = {target: {closest: () => trigger}, preventDefault() { this.prevented = true; }};
    const open = () => document.handlers.click(event);
    return {parts, styles, dialog, trigger, event, open, downloads};
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

test("pagination dots select the preview and correct attachment", async () => {
    const state = setup();
    state.open();
    assert.equal(state.parts.preview.src, state.trigger.dataset.shareImage);
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    assert.equal(state.styles[0].attributes["aria-pressed"], "true");
    state.styles[1].handlers.click();
    assert.equal(state.parts.preview.src, `${state.trigger.dataset.shareTransparentImage}?layout=vertical`);
    assert.equal(state.parts.preview.dataset.transparent, "true");
    assert.equal(state.parts.counter.textContent, "Image 2 of 5");
    assert.equal(state.styles[1].attributes["aria-pressed"], "true");
    assert.equal(state.styles[0].attributes["aria-pressed"], "false");
    assert.equal(state.parts["save-label"].textContent, "Save image");
    await state.parts.save.handlers.click();
    assert.equal(state.downloads[0].href, `${state.trigger.dataset.shareTransparentDownload}&layout=vertical`);
    assert.equal(state.downloads[0].download, "pelagia-dive-transparent-vertical.png");
    state.parts.carousel.handlers.keydown({key: "ArrowRight", preventDefault() {}});
    assert.equal(state.parts.preview.src, `${state.trigger.dataset.shareTransparentImage}?layout=horizontal`);
    state.parts.carousel.handlers.keydown({key: "ArrowLeft", preventDefault() {}});
    assert.equal(state.parts.preview.src, `${state.trigger.dataset.shareTransparentImage}?layout=vertical`);
    state.dialog.close();
    state.open();
    assert.equal(state.parts.preview.dataset.transparent, "false");
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
});

test("horizontal touch swipes and keyboard arrows change styles; vertical scrolling does not", () => {
    const state = setup();
    state.open();
    const pointer = (x, y, extra = {}) => ({clientX: x, clientY: y, pointerId: 1, isPrimary: true, pointerType: "touch", target: {closest: () => null}, ...extra});
    state.parts.carousel.handlers.pointerdown(pointer(250, 80));
    state.parts.carousel.handlers.pointerup(pointer(150, 90));
    assert.equal(state.parts.counter.textContent, "Image 2 of 5");
    state.parts.carousel.handlers.pointerdown(pointer(150, 80));
    state.parts.carousel.handlers.pointerup(pointer(250, 90));
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    for (const end of [pointer(245, 82), pointer(200, 200)]) {
        state.parts.carousel.handlers.pointerdown(pointer(250, 80));
        state.parts.carousel.handlers.pointerup(end);
        assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    }
    state.parts.carousel.handlers.pointerdown(pointer(250, 80));
    state.parts.carousel.handlers.pointercancel();
    state.parts.carousel.handlers.pointerup(pointer(150, 80));
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    for (const [key, expected] of [["ArrowRight", "Image 2 of 5"], ["Home", "Image 1 of 5"], ["End", "Image 5 of 5"], ["ArrowLeft", "Image 4 of 5"]]) {
        const event = {key, preventDefault() { this.prevented = true; }};
        state.parts.carousel.handlers.keydown(event);
        assert.equal(event.prevented, true);
        assert.equal(state.parts.counter.textContent, expected);
    }
});

test("mobile transparent Save shares a PNG immediately with no background conversion", async () => {
    let payload;
    const state = setup({canShare: data => data.files[0].type === "image/png", share(data) { payload = data; return Promise.resolve(); }}, true, {mobile: true});
    state.open();
    state.styles[1].handlers.click();
    await flushPreparation();
    const sharing = state.parts.save.handlers.click();
    assert.equal(payload.files[0].name, "pelagia-dive-transparent-vertical.png");
    assert.equal(payload.files[0].type, "image/png");
    await sharing;
    assert.equal(state.downloads.length, 0);
});

test("switching styles invalidates an unfinished JPEG preparation", async () => {
    const responses = [];
    let payload;
    const state = setup({canShare: () => true, share(data) { payload = data; return Promise.resolve(); }}, true, {
        mobile: true, fetch: () => new Promise(resolve => responses.push(resolve)),
    });
    state.open();
    state.styles[1].handlers.click();
    responses[1]({ok: true, blob: async () => new Blob(["transparent PNG"])});
    await flushPreparation();
    responses[0]({ok: true, blob: async () => new Blob(["full JPEG"])});
    await flushPreparation();
    assert.equal(state.parts.save.disabled, false);
    await state.parts.save.handlers.click();
    assert.equal(payload.files[0].type, "image/png");
    assert.equal(await payload.files[0].text(), "transparent PNG");
});


test("all five styles wrap, keep transparency and save the selected layout", async () => {
    const state = setup();
    state.open();
    const layouts = [null, "vertical", "horizontal", "stacked", "map"];
    for (let index = 0; index < layouts.length; index++) {
        state.styles[index].handlers.click();
        assert.equal(state.parts.counter.textContent, `Image ${index + 1} of 5`);
        assert.equal(state.parts.preview.dataset.transparent, String(index > 0));
        assert.ok(state.parts.preview.style.aspectRatio);
        assert.equal(state.styles.filter(button => button.attributes["aria-pressed"] === "true").length, 1);
        await state.parts.save.handlers.click();
        const saved = state.downloads.at(-1);
        if (layouts[index]) {
            assert.equal(new URL(saved.href).searchParams.get("layout"), layouts[index]);
            assert.equal(new URL(saved.href).searchParams.get("download"), "1");
            assert.equal(saved.download, `pelagia-dive-transparent-${layouts[index]}.png`);
        } else assert.equal(saved.href, state.trigger.dataset.shareDownload);
    }
    state.parts.carousel.handlers.keydown({key: "ArrowRight", preventDefault() {}});
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    state.parts.carousel.handlers.keydown({key: "ArrowLeft", preventDefault() {}});
    assert.equal(state.parts.counter.textContent, "Image 5 of 5");
});

test("a late vertical PNG cannot replace the selected map PNG", async () => {
    const responses = [];
    let payload;
    const state = setup({canShare: () => true, share(data) { payload = data; return Promise.resolve(); }}, true, {
        mobile: true, fetch: () => new Promise(resolve => responses.push(resolve)),
    });
    state.open();
    state.styles[1].handlers.click();
    state.styles[4].handlers.click();
    responses[2]({ok: true, blob: async () => new Blob(["map PNG"])});
    await flushPreparation();
    responses[1]({ok: true, blob: async () => new Blob(["vertical PNG"])});
    await flushPreparation();
    await state.parts.save.handlers.click();
    assert.equal(payload.files[0].name, "pelagia-dive-transparent-map.png");
    assert.equal(await payload.files[0].text(), "map PNG");
});


test("depth chart adds a sixth transparent style and resets for a dive without a chart", () => {
    const state = setup();
    state.trigger.dataset.shareDepthProfile = "true";
    state.open();
    assert.equal(state.styles[5].hidden, false);
    state.styles[5].handlers.click();
    assert.equal(state.parts.preview.src, `${state.trigger.dataset.shareTransparentImage}?layout=depth_profile`);
    assert.equal(state.parts.preview.dataset.transparent, "true");
    assert.equal(state.parts.preview.style.aspectRatio, "960 / 1200");
    assert.equal(state.parts.counter.textContent, "Image 6 of 6");
    state.parts.save.handlers.click();
    assert.equal(state.downloads[0].href, `${state.trigger.dataset.shareTransparentDownload}&layout=depth_profile`);
    assert.equal(state.downloads[0].download, "pelagia-dive-transparent-depth_profile.png");
    state.parts.carousel.handlers.keydown({key: "ArrowRight", preventDefault() {}});
    assert.equal(state.parts.counter.textContent, "Image 1 of 6");
    state.trigger.dataset.shareDepthProfile = "false";
    state.open();
    assert.equal(state.styles[5].hidden, true);
    assert.equal(state.parts.counter.textContent, "Image 1 of 5");
    state.parts.carousel.handlers.keydown({key: "ArrowLeft", preventDefault() {}});
    assert.equal(state.parts.counter.textContent, "Image 5 of 5");
});

test("mobile depth profile Save shares the transparent PNG", async () => {
    let payload;
    const state = setup({canShare: () => true, share(data) { payload = data; return Promise.resolve(); }}, true, {mobile: true});
    state.trigger.dataset.shareDepthProfile = "true";
    state.open();
    state.styles[5].handlers.click();
    await new Promise(resolve => setImmediate(resolve));
    await state.parts.save.handlers.click();
    assert.equal(payload.files[0].type, "image/png");
    assert.equal(payload.files[0].name, "pelagia-dive-transparent-depth_profile.png");
});
