const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(standalone = false, options = {}) {
    const element = () => ({
        handlers: {}, attributes: {}, style: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        dispatchEvent(event) { this.handlers[event.type]?.(event); return !event.defaultPrevented; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; },
    });
    const window = element();
    window.scrollX = 0; window.scrollY = options.scrollY || 0;
    window.scrollTo = ({left, top}) => { window.scrollX = left; window.scrollY = top; };
    const storage = options.storage || new Map();
    window.sessionStorage = options.blockedStorage ? {
        getItem() { throw new Error("Storage is disabled"); }, setItem() { throw new Error("Storage is disabled"); },
    } : {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)};
    let backCount = 0;
    window.location = { href: "https://pelagia.test/home", pathname: "/home", assign(url) { this.destination = url; }, replace(url) { this.replaced = url; } };
    window.history = {
        state: null,
        pushState(state, _, url) { this.state = state; window.location.href = url; },
        replaceState(state, _, url) { this.state = state; window.location.href = url; },
        back() { backCount++; this.state = null; window.handlers.popstate(); },
    };
    const reader = element(), dialog = element(), trigger = element(), closeLink = element(), heading = element();
    heading.textContent = "The Dive Brief";
    const disclosure = element(), summary = element();
    reader.dataset = {briefEdition: options.edition || "2026-09-04"};
    disclosure.open = true;
    const scroller = element();
    scroller.scrollHeight = 2000; scroller.clientHeight = 800; scroller.clientWidth = 390; scroller.scrollTop = 0;
    trigger.href = "https://pelagia.test/brief/2026-09-04";
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    reader.querySelector = selector => selector === "[data-brief-heading]" ? heading : scroller;
    reader.querySelectorAll = () => [closeLink];
    const classes = new Set();
    const document = element();
    document.querySelector = selector => ({
        "[data-brief-reader]": reader,
        "[data-brief-dialog]": standalone ? null : dialog,
        "[data-brief-open]": standalone ? null : trigger,
        "[data-brief-disclosure]": standalone ? null : disclosure,
        "[data-brief-toggle]": standalone ? null : summary,
    })[selector];
    document.title = "Home - Pelagia";
    document.documentElement = {dataset: {}};
    document.body = { style: {top: ""}, classList: { add: name => classes.add(name), remove: name => classes.delete(name) } };
    const context = vm.createContext({window, document});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveBrief()", context);
    const click = (overrides = {}) => ({button: 0, detail: 1, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }, ...overrides});
    const open = () => trigger.handlers.click(click());
    const touch = (x, y, targetLink = false) => ({
        touches: [{clientX: x, clientY: y}],
        changedTouches: [{clientX: x, clientY: y}],
        target: {closest: () => targetLink},
    });
    const end = (x, y) => ({touches: [], changedTouches: [{clientX: x, clientY: y}], preventDefault() { this.prevented = true; }});
    return {window, document, reader, dialog, trigger, closeLink, heading, disclosure, summary, storage, scroller, classes, open, click, touch, end, context, backCount: () => backCount};
}

test("reader focus starts at its heading and returning restores the feed scroll and title", () => {
    const state = setup(false, {scrollY: 240});
    state.open();
    assert.equal(state.heading.focused, true);
    assert.equal(state.document.title, "The Dive Brief · Pelagia");
    assert.equal(state.document.body.style.top, "-240px");
    state.window.scrollY = 0; // A fixed body moves the document scroll to zero.
    state.closeLink.handlers.click(state.click());
    assert.equal(state.window.scrollY, 240);
    assert.equal(state.document.body.style.top, "");
    assert.equal(state.document.title, "Home - Pelagia");
});

test("repeated open activation and queued close events cannot corrupt a reopened reader", () => {
    const state = setup();
    state.open(); state.open();
    state.window.history.back();
    assert.equal(state.backCount(), 1);
    state.window.history.state = {pelagiaBrief: true};
    state.window.handlers.popstate();
    state.dialog.handlers.close();
    assert.equal(state.dialog.open, true);
    assert.equal(state.classes.has("brief-is-open"), true);
    assert.equal(state.trigger.attributes["aria-expanded"], "true");
    assert.equal(state.document.title, "The Dive Brief · Pelagia");
});

test("touch focus stays quiet while keyboard interaction restores visible focus styling", () => {
    const state = setup();
    vm.runInContext("initInteractionFocus()", state.context);
    const modality = () => state.document.documentElement.dataset.inputModality;
    assert.equal(modality(), "pointer");
    state.document.handlers.keydown({key: "Tab"});
    assert.equal(modality(), "keyboard");
    state.document.handlers.pointerdown({pointerType: "touch"});
    assert.equal(modality(), "pointer");
    state.document.handlers.keydown({key: "Escape"});
    assert.equal(modality(), "keyboard");
    state.document.handlers.touchstart();
    assert.equal(modality(), "pointer");
});

test("the Feed button after a reader refresh consumes the existing history entry", () => {
    const state = setup(true);
    state.window.history.state = {pelagiaBrief: true};
    state.window.location.pathname = "/home"; // The prior entry is the same document after a modal refresh.
    state.closeLink.handlers.click(state.click());
    state.closeLink.handlers.click(state.click());
    assert.equal(state.backCount(), 1);
    assert.equal(state.window.location.replaced, "/home");
});

test("brief opens immediately and browser Back restores focus and scroll lock", () => {
    const state = setup();
    state.open();
    assert.equal(state.dialog.open, true);
    assert.equal(state.window.location.href, state.trigger.href);
    assert.equal(state.classes.has("brief-is-open"), true);
    state.window.history.back();
    assert.equal(state.dialog.open, false);
    assert.equal(state.summary.focused, true);
    assert.equal(state.disclosure.open, false);
    assert.equal(state.classes.size, 0);
    state.window.history.state = {pelagiaBrief: true};
    state.window.handlers.popstate();
    assert.equal(state.dialog.open, true);
    assert.equal(state.trigger.attributes["aria-expanded"], "true");
});

test("horizontal touch gestures leave modal and standalone readers open without consuming events", () => {
    for (const standalone of [false, true]) {
        for (const dx of [-130, 130]) {
            const state = setup(standalone);
            if (!standalone) state.open();
            for (const [type, event] of [
                ["touchstart", state.touch(190, 400)],
                ["touchmove", state.touch(190 + dx / 2, 401)],
                ["touchend", state.end(190 + dx, 402)],
            ]) {
                event.type = type;
                state.reader.dispatchEvent(event);
                assert.equal(event.prevented, undefined);
            }
            assert.equal(state.backCount(), 0);
            assert.equal(state.window.location.destination, undefined);
            if (!standalone) assert.equal(state.dialog.open, true);
            const click = state.click();
            click.type = "click";
            state.document.dispatchEvent(click);
            assert.equal(click.prevented, undefined);
            assert.equal(click.stopped, undefined);
        }
    }
});

test("close and Escape consume only one history entry; modified clicks keep native link behavior", () => {
    const state = setup();
    const modified = state.click({ctrlKey:true});
    state.trigger.handlers.click(modified);
    assert.equal(modified.prevented, undefined);
    assert.equal(state.dialog.open, undefined);
    state.open();
    const cancel = state.click();
    state.dialog.handlers.cancel(cancel);
    state.closeLink.handlers.click(state.click());
    assert.equal(cancel.prevented, true);
    assert.equal(state.backCount(), 1);
});

test("standalone editions return to home", () => {
    const state = setup(true);
    state.reader.handlers.keydown({key:"Escape"});
    assert.equal(state.window.location.destination, "/home");
});

test("horizontal trackpad scrolling leaves readers open and preserves native wheel behavior", () => {
    for (const standalone of [false, true]) {
        for (const direction of [-1, 1]) {
            const state = setup(standalone);
            if (!standalone) state.open();
            for (let i = 0; i < 4; i++) {
                const event = {type: "wheel", deltaX: direction * 60, deltaY: 0, deltaMode: 0,
                    target: {closest: () => false}, preventDefault() { this.prevented = true; }};
                state.reader.dispatchEvent(event);
                assert.equal(event.prevented, undefined);
            }
            assert.equal(state.backCount(), 0);
            assert.equal(state.window.location.destination, undefined);
            if (!standalone) assert.equal(state.dialog.open, true);
        }
    }
});

test("exiting the reader collapses the card; expanding the header restores the preview without reopening the reader", () => {
    const state = setup();
    assert.equal(state.disclosure.open, true);
    state.open();
    state.closeLink.handlers.click(state.click());
    assert.equal(state.disclosure.open, false);
    assert.equal(state.summary.focused, true);
    assert.equal(state.storage.get("pelagia:brief:collapsed:2026-09-04"), "true");
    state.disclosure.open = true; // Native details behavior on summary activation.
    state.disclosure.handlers.toggle();
    assert.equal(state.dialog.open, false);
    assert.equal(state.storage.get("pelagia:brief:collapsed:2026-09-04"), "false");
    state.open();
    assert.equal(state.dialog.open, true);
});

test("collapsed state survives reloads and standalone returns, while a new edition starts expanded", () => {
    const standalone = setup(true);
    standalone.closeLink.handlers.click(standalone.click());
    assert.equal(standalone.window.location.destination, "/home");
    const returned = setup(false, {storage: standalone.storage});
    assert.equal(returned.disclosure.open, false);
    returned.disclosure.open = true;
    returned.window.handlers.pagehide(); // Refresh before the native toggle event fires.
    assert.equal(setup(false, {storage: returned.storage}).disclosure.open, true);
    returned.disclosure.open = false;
    returned.disclosure.handlers.toggle();
    assert.equal(setup(false, {storage: returned.storage, edition:"2026-09-05"}).disclosure.open, true);
});

test("browser Back from a standalone reader marks the edition read and blocked storage never prevents closing", () => {
    const standalone = setup(true);
    standalone.window.handlers.pagehide();
    assert.equal(setup(false, {storage:standalone.storage}).disclosure.open, false);
    const state = setup(false, {blockedStorage:true});
    state.open();
    state.window.history.back();
    assert.equal(state.dialog.open, false);
    assert.equal(state.disclosure.open, false);
});

test("browser Back after refreshing a modal reader fetches the actual feed document", () => {
    const standalone = setup(true);
    standalone.window.handlers.popstate();
    assert.equal(standalone.window.location.replaced, "/home");
    assert.equal(setup(false, {storage:standalone.storage}).disclosure.open, false);
});
