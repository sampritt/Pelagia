const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(standalone = false) {
    const element = () => ({
        handlers: {}, attributes: {}, style: {},
        addEventListener(name, callback) { this.handlers[name] = callback; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; },
    });
    const window = element();
    let backCount = 0;
    window.location = { href: "https://pelagia.test/home", assign(url) { this.destination = url; } };
    window.history = {
        state: null,
        pushState(state, _, url) { this.state = state; window.location.href = url; },
        replaceState(state, _, url) { this.state = state; window.location.href = url; },
        back() { backCount++; this.state = null; window.handlers.popstate(); },
    };
    const reader = element(), dialog = element(), trigger = element(), closeLink = element();
    const scroller = element(), progress = element();
    scroller.scrollHeight = 2000; scroller.clientHeight = 800; scroller.scrollTop = 0;
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
    })[selector];
    document.body = { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } };
    const context = vm.createContext({window, document});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initDiveBrief()", context);
    const click = (overrides = {}) => ({button: 0, preventDefault() { this.prevented = true; }, ...overrides});
    const open = () => trigger.handlers.click(click());
    const touch = (x, y, targetLink = false) => ({
        touches: [{clientX: x, clientY: y}],
        changedTouches: [{clientX: x, clientY: y}],
        target: {closest: () => targetLink},
    });
    const end = (x, y) => ({touches: [], changedTouches: [{clientX: x, clientY: y}]});
    return {window, reader, dialog, trigger, closeLink, scroller, progress, classes, open, click, touch, end, backCount: () => backCount};
}

test("brief opens immediately and browser Back restores focus and scroll lock", () => {
    const state = setup();
    state.open();
    assert.equal(state.dialog.open, true);
    assert.equal(state.window.location.href, state.trigger.href);
    assert.equal(state.classes.has("brief-is-open"), true);
    state.window.history.back();
    assert.equal(state.dialog.open, false);
    assert.equal(state.trigger.focused, true);
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
    state.reader.handlers.keydown({key:"Escape"});
    assert.equal(state.window.location.destination, "/home");
    state.reader.handlers.touchstart(state.touch(180, 400));
    state.reader.handlers.touchend(state.end(50, 405));
    assert.equal(state.window.location.destination, "/home");
});
