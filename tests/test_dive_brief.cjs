const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(standalone = false, options = {}) {
    const element = () => ({
        handlers: {}, attributes: {}, style: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; },
    });
    const window = element();
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
    const reader = element(), dialog = element(), trigger = element(), closeLink = element();
    const disclosure = element(), summary = element();
    reader.dataset = {briefEdition: options.edition || "2026-09-04"};
    disclosure.open = true;
    const scroller = element(), progress = element();
    scroller.scrollHeight = 2000; scroller.clientHeight = 800; scroller.clientWidth = 390; scroller.scrollTop = 0;
    trigger.href = "https://pelagia.test/brief/2026-09-04";
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; dialog.handlers.close(); };
    reader.querySelector = selector => selector.includes("progress") ? progress : scroller;
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
    document.body = { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } };
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
    return {window, document, reader, dialog, trigger, closeLink, disclosure, summary, storage, scroller, progress, classes, open, click, touch, end, backCount: () => backCount};
}

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

test("left and right swipes return to feed while vertical, cancelled, and link gestures stay in reader", () => {
    for (const dx of [-120, 120]) {
        const state = setup(); state.open();
        state.reader.handlers.touchstart(state.touch(180, 400));
        state.reader.handlers.touchend(state.end(180 + dx, 405));
        assert.equal(state.backCount(), 1);
        assert.equal(state.dialog.open, false);
    }
    for (const gesture of ["vertical", "cancel", "link", "multitouch", "short"]) {
        const state = setup(); state.open();
        state.reader.handlers.touchstart(state.touch(180, 400, gesture === "link"));
        if (gesture === "vertical") state.reader.handlers.touchmove(state.touch(190, 500));
        if (gesture === "cancel") state.reader.handlers.touchcancel();
        if (gesture === "multitouch") state.reader.handlers.touchmove({touches: [{clientX:180,clientY:400}, {}]});
        state.reader.handlers.touchend(state.end(gesture === "short" ? 200 : 310, 405));
        assert.equal(state.dialog.open, true, gesture);
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

test("reader progress tracks its own scroll and standalone editions return to home", () => {
    const state = setup(true);
    state.scroller.scrollTop = 600;
    state.scroller.handlers.scroll();
    assert.equal(state.progress.style.transform, "scaleX(0.5)");
    state.scroller.scrollTop = -50;
    state.scroller.handlers.scroll();
    assert.equal(state.progress.style.transform, "scaleX(0)");
    state.scroller.scrollTop = 3000;
    state.scroller.handlers.scroll();
    assert.equal(state.progress.style.transform, "scaleX(1)");
    state.reader.handlers.keydown({key:"Escape"});
    assert.equal(state.window.location.destination, "/home");
    state.reader.handlers.touchstart(state.touch(180, 400));
    state.reader.handlers.touchend(state.end(50, 405));
    assert.equal(state.window.location.destination, "/home");
});

test("trackpad swipes close in either direction and vertical scroll, zoom and content scrolling remain native", () => {
    const wheel = (deltaX, deltaY = 0, extra = {}) => ({
        deltaX, deltaY, deltaMode: 0, target: {closest: () => false},
        preventDefault() { this.prevented = true; }, ...extra,
    });
    for (const direction of [-1, 1]) {
        const state = setup(); state.open();
        for (let i = 0; i < 3; i++) state.reader.handlers.wheel(wheel(direction * 45, 2));
        assert.equal(state.backCount(), 1);
        assert.equal(state.dialog.open, false);
    }
    for (const event of [wheel(2, 100), wheel(50, 40), wheel(150, 0, {ctrlKey:true}), wheel(150, 0, {target:{closest:()=>true}})]) {
        const state = setup(); state.open();
        state.reader.handlers.wheel(event);
        assert.equal(event.prevented, undefined);
        assert.equal(state.dialog.open, true);
    }
    const state = setup(); state.open();
    state.reader.handlers.wheel(wheel(80));
    state.reader.handlers.wheel(wheel(-80));
    assert.equal(state.dialog.open, true, "opposite gestures do not combine");
    state.reader.handlers.wheel(wheel(-4, 0, {deltaMode:1}));
    assert.equal(state.dialog.open, false, "line-based wheel deltas are normalized");
});

test("selecting story text never dismisses the reader on a horizontal gesture", () => {
    const state = setup(); state.open();
    state.window.getSelection = () => ({isCollapsed:false});
    state.reader.handlers.touchstart(state.touch(180, 400));
    state.reader.handlers.touchend(state.end(50, 405));
    const event = {deltaX:150, deltaY:0, target:{closest:()=>false}, preventDefault() { this.prevented = true; }};
    state.reader.handlers.wheel(event);
    assert.equal(event.prevented, undefined);
    assert.equal(state.dialog.open, true);
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

test("dismissal swipes cancel compatibility clicks before they can activate a logged dive", () => {
    for (const dx of [-130, 130]) {
        const state = setup(); state.open();
        state.reader.handlers.touchstart(state.touch(200, 500));
        const end = state.end(200 + dx, 500);
        state.reader.handlers.touchend(end);
        assert.equal(end.prevented, true);
        assert.equal(state.dialog.open, false);
        const compatibilityClick = state.click();
        state.document.handlers.click(compatibilityClick);
        assert.equal(compatibilityClick.prevented, true);
        assert.equal(compatibilityClick.stopped, true);
        const laterClick = state.click();
        state.document.handlers.click(laterClick);
        assert.equal(laterClick.prevented, undefined, "the guard consumes only the leftover click");
    }
});

test("fresh touch, mouse and keyboard actions remain usable immediately after a swipe", () => {
    for (const kind of ["touch", "mouse", "keyboard"]) {
        const state = setup(); state.open();
        state.reader.handlers.touchstart(state.touch(200, 500));
        state.reader.handlers.touchend(state.end(70, 500));
        if (kind === "touch") state.document.handlers.touchstart();
        if (kind === "mouse") state.document.handlers.pointerdown({pointerType:"mouse"});
        const click = state.click({detail: kind === "keyboard" ? 0 : 1});
        state.document.handlers.click(click);
        assert.equal(click.prevented, undefined, kind);
    }
});

test("vertical gestures and taps never cancel or suppress subsequent feed clicks", () => {
    for (const [dx, dy] of [[3, -150], [2, 1], [90, 80]]) {
        const state = setup(); state.open();
        state.reader.handlers.touchstart(state.touch(200, 500));
        state.reader.handlers.touchmove(state.touch(200 + dx, 500 + dy));
        const end = state.end(200 + dx, 500 + dy);
        state.reader.handlers.touchend(end);
        assert.equal(end.prevented, undefined);
        const click = state.click();
        state.document.handlers.click(click);
        assert.equal(click.prevented, undefined);
    }
});
