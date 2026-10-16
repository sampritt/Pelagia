const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function element() {
    return {handlers: {}, hidden: true, disabled: false, textContent: "",
        addEventListener(name, callback) { this.handlers[name] = callback; },
        focus() {this.focused = true;}, getAttribute() {return null;}};
}

async function setup(options = {}) {
    const install = element();
    const guide = element();
    const close = element();
    const dialog = element();
    dialog.querySelector = () => close;
    dialog.showModal = () => {dialog.open = true;};
    dialog.close = () => {dialog.open = false; dialog.handlers.close();};
    const parts = Object.fromEntries(["offline-notice", "update-notice", "install-notice", "update", "retry", "back"].map(name => [name, element()]));
    const classes = new Set();
    const document = element();
    document.documentElement = {classList: {toggle(name, enabled) {if (enabled) classes.add(name); else classes.delete(name);}}, style: {setProperty() {}}};
    document.querySelectorAll = selector => selector === "[data-pwa-guide]" ? [guide] : [install];
    document.querySelector = selector => selector === "[data-pwa-install-dialog]" ? dialog : parts[selector.match(/data-pwa-(.*)\]/)[1]];
    document.referrer = options.referrer || "";
    document.visibilityState = "visible";
    const displayMode = element();
    displayMode.matches = !!options.standalone;
    let reloads = 0;
    let backs = 0;
    let checks = 0;
    const messages = [];
    const window = element();
    window.matchMedia = () => displayMode;
    window.isSecureContext = options.secure !== false;
    window.innerHeight = 844;
    window.location = {origin: "https://pelagia.example", reload() {reloads++;}};
    window.history = {length: 2, back() {backs++;}};
    window.visualViewport = element();
    window.visualViewport.height = 844;
    const registration = element();
    const worker = element();
    registration.installing = worker;
    registration.waiting = options.waiting ? {postMessage(message) {messages.push(message.type);}} : null;
    registration.update = async () => {checks++;};
    const serviceWorker = element();
    const registrations = [];
    serviceWorker.controller = options.firstInstall ? null : {};
    serviceWorker.register = async (...args) => {registrations.push(args); return registration;};
    const navigator = {onLine: options.online !== false, userAgent: options.ios ? "iPhone" : "Chrome", platform: options.ipad ? "MacIntel" : "", maxTouchPoints: options.ipad ? 5 : 0, standalone: !!options.legacyStandalone};
    if (options.serviceWorker !== false) navigator.serviceWorker = serviceWorker;
    const warnings = [];
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/pwa.js"), "utf8"), vm.createContext({window, document, navigator, URL, console: {warn: (...args) => warnings.push(args)}}));
    await new Promise(resolve => setImmediate(resolve));
    return {install, guide, close, dialog, parts, classes, window, document, navigator, serviceWorker, registration, worker, messages, registrations, warnings, displayMode,
        get reloads() {return reloads;}, get backs() {return backs;}, get checks() {return checks;}};
}

test("install UI stays hidden until supported, is hidden standalone, and does not register on insecure origins", async () => {
    for (const options of [{}, {ios: true, standalone: true}, {ipad: true, legacyStandalone: true}, {ios: true, secure: false}]) {
        const s = await setup(options);
        assert.equal(s.install.hidden, true);
        assert.equal(s.registrations.length, options.secure === false ? 0 : 1);
    }
    const unsupported = await setup({serviceWorker: false});
    assert.equal(unsupported.registrations.length, 0);
    assert.equal(unsupported.install.hidden, true);
});

test("Android prompts synchronously on click, permits dismissal, and hides after installation", async () => {
    const s = await setup();
    let prompted = false;
    let prevented = false;
    s.window.handlers.beforeinstallprompt({preventDefault() {prevented = true;}, prompt() {prompted = true; return Promise.resolve();}, userChoice: Promise.resolve({outcome: "dismissed"})});
    assert.equal(prevented, true);
    assert.equal(s.install.hidden, false);
    const completion = s.install.handlers.click();
    assert.equal(prompted, true);
    assert.equal(s.install.disabled, true);
    await completion;
    assert.equal(s.install.hidden, true);
    assert.equal(s.install.disabled, false);
    s.window.handlers.beforeinstallprompt({preventDefault() {}});
    assert.equal(s.install.hidden, false);
    s.window.handlers.appinstalled();
    assert.equal(s.install.hidden, true);
});

test("iPhone and desktop-mode iPad offer instructions, and closing restores focus", async () => {
    for (const options of [{ios: true}, {ipad: true}]) {
        const s = await setup(options);
        assert.equal(s.install.hidden, false);
        assert.match(s.install.textContent, /Home Screen/);
        await s.install.handlers.click();
        assert.equal(s.dialog.open, true);
        s.close.handlers.click();
        assert.equal(s.dialog.open, false);
        assert.equal(s.install.focused, true);
        s.displayMode.matches = true;
        s.displayMode.handlers.change();
        assert.equal(s.install.hidden, true);
    }
});

test("offline POST submissions are blocked including submitter overrides; reconnection clears the notice", async () => {
    const s = await setup({online: false});
    assert.equal(s.parts["offline-notice"].hidden, false);
    for (const [method, override, blocked] of [["POST", null, true], ["get", "post", true], ["post", "GET", false], [null, null, false], ["dialog", null, false]]) {
        let prevented = false;
        let stopped = false;
        s.document.handlers.submit({target: {getAttribute: () => method}, submitter: {getAttribute: () => override},
            preventDefault() {prevented = true;}, stopImmediatePropagation() {stopped = true;}});
        assert.equal(prevented, blocked);
        assert.equal(stopped, blocked);
    }
    s.navigator.onLine = true;
    s.window.handlers.online();
    assert.equal(s.parts["offline-notice"].hidden, true);
});

test("waiting updates never reload an open form until requested, and update checks resume on foregrounding", async () => {
    const s = await setup({waiting: true});
    assert.equal(s.parts["update-notice"].hidden, false);
    s.serviceWorker.handlers.controllerchange();
    assert.equal(s.reloads, 0);
    s.navigator.onLine = false;
    s.parts.update.handlers.click();
    assert.deepEqual(s.messages, []);
    s.navigator.onLine = true;
    s.parts.update.handlers.click();
    assert.deepEqual(s.messages, ["SKIP_WAITING"]);
    assert.equal(s.reloads, 0);
    s.serviceWorker.handlers.controllerchange();
    s.serviceWorker.handlers.controllerchange();
    assert.equal(s.reloads, 1);
    s.document.handlers.visibilitychange();
    assert.equal(s.checks, 1);
    const first = await setup({waiting: true, firstInstall: true});
    assert.equal(first.parts["update-notice"].hidden, true);
});

test("updates detected after load show a notice and install prompt failures offer the browser menu", async () => {
    const s = await setup();
    assert.equal(s.parts["update-notice"].hidden, true);
    s.registration.waiting = {postMessage() {}};
    s.worker.handlers.statechange();
    assert.equal(s.parts["update-notice"].hidden, false);
    s.window.handlers.beforeinstallprompt({preventDefault() {}, prompt() {throw new Error("Unavailable");}});
    await s.install.handlers.click();
    assert.equal(s.parts["install-notice"].hidden, false);
    assert.equal(s.install.disabled, false);
});

test("standalone Back uses local history and retains the home fallback after external entry", async () => {
    for (const [referrer, expected] of [["https://pelagia.example/dive/1", 1], ["https://accounts.google.com/", 0], ["", 0]]) {
        const s = await setup({referrer, standalone: true});
        let prevented = false;
        s.parts.back.handlers.click({button: 0, preventDefault() {prevented = true;}});
        assert.equal(s.backs, expected);
        assert.equal(prevented, expected === 1);
    }
});

test("the mobile navigation clears the keyboard and offline retry reloads the current destination", async () => {
    const s = await setup();
    s.document.activeElement = {matches: () => true};
    s.window.visualViewport.height = 500;
    s.window.visualViewport.handlers.resize();
    assert.equal(s.classes.has("pwa-keyboard-open"), true);
    s.window.visualViewport.height = 844;
    s.window.visualViewport.handlers.resize();
    assert.equal(s.classes.has("pwa-keyboard-open"), false);
    s.parts.retry.handlers.click();
    assert.equal(s.reloads, 1);
});


test("Download opens guidance on every browser and restores focus when closed", async () => {
    for (const options of [{}, {secure: false}, {standalone: true}, {ios: true}]) {
        const s = await setup(options);
        s.guide.handlers.click();
        assert.equal(s.dialog.open, true);
        s.close.handlers.click();
        assert.equal(s.dialog.open, false);
        assert.equal(s.guide.focused, true);
    }
});
