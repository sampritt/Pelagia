const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(href = "https://pelagia.test/dive/new", reducedMotion = false) {
    const navigations = [{}, {}].map(() => ({handlers: {}, addEventListener(name, callback) {this.handlers[name] = callback;}}));
    const scrolls = [];
    const document = {addEventListener() {}, querySelectorAll: () => navigations};
    const window = {location: {href}, matchMedia: () => ({matches: reducedMotion}), scrollTo: options => scrolls.push(options)};
    const context = vm.createContext({document, window, URL});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext("initPrimaryNavigation()", context);
    const tap = (href, options = {}, navIndex = 0) => {
        const link = {href, target: options.target || "", hasAttribute: name => name === "download" && options.download};
        const event = {button: 0, defaultPrevented: false, ...options,
            target: {closest: () => link}, preventDefault() {this.defaultPrevented = true;}};
        navigations[navIndex].handlers.click(event);
        return event;
    };
    return {tap, scrolls, window};
}

test("reselecting a tab scrolls up without reloading a draft in either navigation bar", () => {
    const state = setup();
    for (const index of [0, 1]) {
        assert.equal(state.tap("https://pelagia.test/dive/new", {}, index).defaultPrevented, true);
        assert.equal(state.scrolls[index].top, 0);
        assert.equal(state.scrolls[index].behavior, "smooth");
    }
    assert.equal(state.window.location.href, "https://pelagia.test/dive/new");
});

test("reselecting Explore retains its selected location and respects reduced motion", () => {
    const state = setup("https://pelagia.test/explore?location=Ecuador", true);
    assert.equal(state.tap("https://pelagia.test/explore").defaultPrevented, true);
    assert.equal(state.scrolls[0].behavior, "instant");
    assert.match(state.window.location.href, /location=Ecuador/);
    assert.equal(state.tap("https://pelagia.test/explore?location=Canada").defaultPrevented, false);
});

test("other destinations, modifier clicks, downloads and new tabs keep native navigation", () => {
    const state = setup();
    for (const options of [{metaKey: true}, {ctrlKey: true}, {shiftKey: true}, {altKey: true}, {button: 1},
                           {download: true}, {target: "_blank"}]) {
        assert.equal(state.tap("https://pelagia.test/dive/new", options).defaultPrevented, false);
    }
    assert.equal(state.tap("https://pelagia.test/home").defaultPrevented, false);
    assert.equal(state.tap("https://example.test/dive/new").defaultPrevented, false);
    assert.equal(state.scrolls.length, 0);
});
