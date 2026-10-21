const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const loadingSource = fs.readFileSync('pelagia/static/js/loading.js', 'utf8');
const appSource = fs.readFileSync('pelagia/static/js/app.js', 'utf8');

function element() {
    const classes = new Set();
    return {
        attrs: {}, children: [], hidden: true, inert: false, handlers: {},
        classList: { add: name => classes.add(name), remove: name => classes.delete(name),
            contains: name => classes.has(name), toggle(name, on) { on ? classes.add(name) : classes.delete(name); } },
        getAttribute(name) { return this.attrs[name] ?? null; },
        setAttribute(name, value) { this.attrs[name] = value; },
        removeAttribute(name) { delete this.attrs[name]; },
        appendChild(child) { this.children.push(child); child.remove = () => { this.children = this.children.filter(item => item !== child); }; },
        addEventListener(name, callback) { (this.handlers[name] ||= []).push(callback); },
        removeEventListener(name, callback) { this.handlers[name] = (this.handlers[name] || []).filter(item => item !== callback); },
        dispatch(name, event = {}) { (this.handlers[name] || []).forEach(callback => callback(event)); },
    };
}

function setup() {
    let now = 0;
    let next = 0;
    const timers = new Map();
    const document = element();
    const status = element();
    const shell = element(); shell.dataset = {};
    const main = element();
    document.body = element();
    document.createElement = element;
    document.getElementById = () => main;
    document.querySelector = selector => selector.includes('navigation-skeleton') ? shell : status;
    document.querySelectorAll = () => [];
    const window = element();
    window.location = { href: 'http://localhost/home', origin: 'http://localhost', pathname: '/home', search: '' };
    window.scrollTo = () => {};
    window.setTimeout = (callback, delay) => { const id = ++next; timers.set(id, { at: now + delay, callback }); return id; };
    window.clearTimeout = id => timers.delete(id);
    let observeMedia;
    const context = vm.createContext({ document, window, URL, URLSearchParams, MutationObserver: class { constructor(callback) { observeMedia = callback; } observe() {} } });
    vm.runInContext(loadingSource, context);
    document.dispatch('DOMContentLoaded');
    function tick(ms) {
        now += ms;
        for (const [id, timer] of timers) {
            if (timer.at <= now) { timers.delete(id); timer.callback(); }
        }
    }
    return { context, document, window, status, shell, main, tick, observeMedia, loading: window.PelagiaLoading };
}

test('fast regions never flash; slow regions restore prior busy and inert states', () => {
    const { loading, tick } = setup();
    const host = element();
    let end = loading.begin(host);
    end(); tick(200);
    assert.equal(host.children.length, 0);
    assert.equal(host.getAttribute('aria-busy'), null);
    host.setAttribute('aria-busy', 'false');
    end = loading.begin(host, 'Loading suggestions', undefined, { reveal: true });
    tick(160);
    assert.equal(host.hidden, false);
    assert.equal(host.inert, true);
    assert.equal(host.children.length, 1);
    end(); end();
    assert.equal(host.children.length, 0);
    assert.equal(host.inert, false);
    assert.equal(host.getAttribute('aria-busy'), 'false');
});

test('a stale region cleanup cannot clear a newer loading state', () => {
    const { loading, tick } = setup();
    const host = element();
    const oldEnd = loading.begin(host);
    const newEnd = loading.begin(host);
    tick(160); oldEnd();
    assert.equal(host.getAttribute('aria-busy'), 'true');
    assert.equal(host.children.length, 1);
    newEnd();
    assert.equal(host.children.length, 0);
});

test('navigation keeps chrome usable, resets on history restore, and recovers from stalls', () => {
    const { loading, tick, shell, main, window, status } = setup();
    loading.startNavigation('/you'); tick(160);
    assert.equal(shell.hidden, false);
    assert.equal(shell.dataset.layout, 'profile');
    assert.equal(main.inert, true);
    window.dispatch('pageshow');
    assert.equal(shell.hidden, true);
    assert.equal(main.inert, false);
    loading.startNavigation('/you/settings'); tick(160);
    assert.equal(shell.dataset.layout, 'form');
    window.dispatch('pageshow');
    loading.startNavigation('/dive/new'); tick(160);
    assert.equal(shell.dataset.layout, 'form');
    tick(15000);
    assert.equal(shell.hidden, true);
    assert.equal(main.inert, false);
    assert.match(status.textContent, /try again/);
});

test('modified links, same-page anchors, downloads, external links and prevented events do not mask content', () => {
    const { window, tick, shell } = setup();
    const link = { href: 'http://localhost/you', target: '', hasAttribute: () => false };
    const click = extra => window.dispatch('click', { button: 0, target: { closest: () => link }, ...extra });
    click({ ctrlKey: true }); tick(200); assert.equal(shell.hidden, true);
    click({ defaultPrevented: true }); tick(200); assert.equal(shell.hidden, true);
    link.href = 'http://localhost/home#metrics'; click(); tick(200); assert.equal(shell.hidden, true);
    link.href = 'http://localhost/you'; link.hasAttribute = () => true;
    click(); tick(200); assert.equal(shell.hidden, true);
    link.hasAttribute = () => false; link.href = 'https://example.com/you';
    click(); tick(200); assert.equal(shell.hidden, true);
});

test('searches discard older responses, cancelled responses, and recover after errors', async () => {
    const { context, window } = setup();
    vm.runInContext(appSource, context);
    const queue = [];
    context.fetch = () => new Promise((resolve, reject) => queue.push({ resolve, reject }));
    const host = element();
    context.host = host;
    context.results = [];
    const first = vm.runInContext('loadSuggestionRegion(host, "/api/search?q=a", items => results.push(items))', context);
    const second = vm.runInContext('loadSuggestionRegion(host, "/api/search?q=b", items => results.push(items))', context);
    queue[1].resolve({ ok: true, json: async () => ['new'] }); await second;
    queue[0].resolve({ ok: true, json: async () => ['old'] }); await first;
    assert.equal(JSON.stringify(context.results), '[["new"]]');
    const cancelled = vm.runInContext('loadSuggestionRegion(host, "/api/search?q=c", items => results.push(items))', context);
    vm.runInContext('hideMenu(host)', context);
    queue[2].resolve({ ok: true, json: async () => ['dismissed'] }); await cancelled;
    assert.equal(host.hidden, true);
    assert.equal(JSON.stringify(context.results), '[["new"]]');
    const failed = vm.runInContext('loadSuggestionRegion(host, "/api/search?q=d", () => {})', context);
    queue[3].reject(new Error('offline')); await failed;
    assert.equal(host.hidden, false);
    assert.match(host.innerHTML, /Type to try again/);
    assert.equal(host.getAttribute('aria-busy'), null);
});

test('failed actions restore buttons and reject duplicate submissions while pending', async () => {
    const { context, status } = setup();
    vm.runInContext(appSource, context);
    const button = element();
    context.button = button;
    let fail;
    let calls = 0;
    context.task = () => { calls++; return new Promise((_, reject) => { fail = reject; }); };
    const pending = vm.runInContext('withPendingAction([button], task)', context);
    await vm.runInContext('withPendingAction([button], task)', context);
    assert.equal(calls, 1);
    assert.equal(button.disabled, true);
    fail(new Error('offline')); await pending;
    assert.equal(button.disabled, false);
    assert.equal(button.inert, false);
    assert.match(status.textContent, /Couldn’t save/);
});


test('dynamic media clears on load, failure, source changes, and timeout', () => {
    const { observeMedia, tick } = setup();
    const img = element();
    img.attrs.src = '/photo.jpg';
    img.closest = () => null;
    img.complete = false;
    const track = () => observeMedia([{type:'attributes', target:img, addedNodes:[], removedNodes:[]}]);
    track(); tick(160);
    assert.equal(img.classList.contains('is-media-loading'),true);
    img.dispatch('error');
    assert.equal(img.classList.contains('is-media-loading'),false);
    assert.equal(img.getAttribute('aria-busy'),null);
    track(); tick(160);
    img.attrs.src = '/other.jpg'; track();
    assert.equal(img.classList.contains('is-media-loading'),false);
    tick(160); img.dispatch('load');
    assert.equal(img.classList.contains('is-media-loading'),false);
    track(); tick(160); tick(15000);
    assert.equal(img.classList.contains('is-media-loading'),false);
});


test('Escape and focus leaving the field cancel suggestions before they can reopen', async () => {
    const { context, document, tick } = setup();
    vm.runInContext(appSource, context);
    const input = element();
    const menu = element();
    const container = {contains: target => target === input || target === menu};
    input.closest = () => container;
    document.activeElement = input;
    context.input = input;
    context.menu = menu;
    let calls = 0;
    let respond;
    context.fetch = () => { calls++; return new Promise(resolve => { respond = resolve; }); };
    const search = vm.runInContext('createSuggestionLoader(input, menu)',context);
    input.dispatch('keydown', {key:'Escape'});
    await search('/api/search', () => assert.fail('Dismissed suggestions cannot render'));
    assert.equal(calls,0);
    input.dispatch('input');
    const pending = search('/api/search', () => assert.fail('Blurred suggestions cannot render'));
    document.activeElement = null;
    input.dispatch('blur'); tick(0);
    respond({ok:true,json:async()=>['result']}); await pending;
    assert.equal(menu.hidden,true);
    assert.equal(menu.getAttribute('aria-busy'),null);
});
