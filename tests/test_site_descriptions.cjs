const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function element(tag = 'div') {
    const classes = new Set();
    return {
        tag, attrs: {}, children: [], handlers: {}, hidden: true, inert: false, removed: false,
        classList: {add: value => classes.add(value), remove: value => classes.delete(value),
            contains: value => classes.has(value), toggle(value, on) { on ? classes.add(value) : classes.delete(value); }},
        matches: () => false,
        getAttribute(name) { return this.attrs[name] ?? null; },
        setAttribute(name, value) { this.attrs[name] = value; },
        removeAttribute(name) { delete this.attrs[name]; },
        appendChild(child) { this.children.push(child); child.parent = this; },
        replaceChildren(...children) { this.children = children; },
        remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); },
        addEventListener(name, callback) { (this.handlers[name] ||= new Set()).add(callback); },
        removeEventListener(name, callback) { this.handlers[name]?.delete(callback); },
        dispatch(name) { [...(this.handlers[name] || [])].forEach(callback => callback()); },
    };
}

const completed = {
    status: 'complete', description: 'A reef & rocky wall. [source]',
    fragments: [{text: 'A reef & rocky wall. '}, {text: '[1]', url: 'https://operator.example/site', title: 'Dive source'}],
};
const response = (status = 200, result = completed) => ({status, ok: status >= 200 && status < 300, json: async () => result});
const flush = async () => { for (let index = 0; index < 10; index++) await Promise.resolve(); };

function setup({hostPresent = true} = {}) {
    let now = 0, timerId = 0;
    const timers = new Map();
    const host = element();
    host.dataset = {descriptionUrl: '/api/dive-sites/1/description'};
    const status = element();
    const document = element();
    document.querySelector = selector => selector === '[data-site-description]' ? (hostPresent ? host : null) : status;
    document.createElement = element;
    document.createTextNode = text => ({textContent: text, nodeType: 3});
    const window = element();
    window.setTimeout = (callback, delay) => { const id = ++timerId; timers.set(id, {at: now + delay, callback}); return id; };
    window.clearTimeout = id => timers.delete(id);
    const calls = [];
    const queued = [];
    const fetch = (url, options) => {
        calls.push({url, options});
        return new Promise((resolve, reject) => queued.push({resolve, reject}));
    };
    const context = vm.createContext({window, document, fetch, AbortController, URL});
    vm.runInContext(fs.readFileSync('pelagia/static/js/loading.js', 'utf8'), context);
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8'), context);
    vm.runInContext('initSiteDescription()', context);
    async function tick(ms) {
        const end = now + ms;
        for (;;) {
            const next = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
            if (!next) break;
            now = next[1].at;
            timers.delete(next[0]);
            next[1].callback();
            await flush();
        }
        now = end;
        await flush();
    }
    return {host, status, window, calls, queued, timers, tick};
}

test('fast generation displays escaped text and clickable sources without skeleton flash', async () => {
    const state = setup();
    assert.equal(state.host.hidden, true);
    assert.equal(state.host.attrs['aria-busy'], 'true');
    assert.equal(state.calls[0].options.method, 'POST');
    assert.equal(state.calls[0].options.headers['X-Requested-With'], 'fetch');
    assert.equal(state.calls[0].options.cache, 'no-store');
    state.queued[0].resolve(response());
    await flush();
    await state.tick(200);
    assert.equal(state.host.hidden, false);
    assert.equal(state.host.attrs['aria-busy'], undefined);
    assert.equal(state.host.inert, false);
    assert.equal(state.host.children[0].tag, 'p');
    const [text, link] = state.host.children[0].children;
    assert.equal(text.textContent, 'A reef & rocky wall. ');
    assert.equal(link.tag, 'a');
    assert.equal(link.href, 'https://operator.example/site');
    assert.equal(link.textContent, '[1]');
    assert.equal(link.rel, 'noopener noreferrer');
    assert.equal(link.attrs['aria-label'], 'Source [1]: Dive source');
    assert.equal(state.timers.size, 0);
});

test('slow generation reuses the delayed two-line skeleton and clears busy state', async () => {
    const state = setup();
    await state.tick(159);
    assert.equal(state.host.hidden, true);
    await state.tick(1);
    assert.equal(state.host.hidden, false);
    assert.equal(state.host.inert, true);
    assert.equal(state.host.classList.contains('is-skeleton-loading'), true);
    assert.equal(state.host.children[0].innerHTML.match(/skeleton-line/g).length, 2);
    assert.equal(state.status.textContent, 'Loading dive site description');
    state.queued[0].resolve(response());
    await flush();
    assert.equal(state.host.classList.contains('is-skeleton-loading'), false);
    assert.equal(state.status.textContent, '');
    assert.equal(state.host.children.length, 1);
});

test('NULL, service failures, auth redirects, invalid JSON and network errors remove the whole area', async () => {
    for (const result of [response(200, {status: 'complete', description: null, fragments: []}), response(503),
                          response(403), {status: 200, ok: true, json: async () => { throw new Error('login HTML'); }}, null]) {
        const state = setup();
        await state.tick(160);
        if (result) state.queued[0].resolve(result);
        else state.queued[0].reject(new Error('offline'));
        await flush();
        assert.equal(state.host.removed, true);
        assert.equal(state.host.attrs['aria-busy'], undefined);
        assert.equal(state.host.inert, false);
        assert.equal(state.timers.size, 0);
        await state.tick(40000);
        assert.equal(state.calls.length, 1);
    }
});

test('pending work polls at two seconds and then displays the cached result', async () => {
    const state = setup();
    state.queued[0].resolve(response(202, {status: 'pending'}));
    await flush();
    await state.tick(1999);
    assert.equal(state.calls.length, 1);
    await state.tick(1);
    assert.equal(state.calls.length, 2);
    state.queued[1].resolve(response());
    await flush();
    assert.equal(state.host.removed, false);
    assert.equal(state.host.children[0].tag, 'p');
    assert.equal(state.timers.size, 0);
});

test('the 35-second deadline aborts a hung request and ignores its late response', async () => {
    const state = setup();
    await state.tick(35000);
    assert.equal(state.host.removed, true);
    assert.equal(state.calls[0].options.signal.aborted, true);
    state.queued[0].resolve(response());
    await flush();
    assert.equal(state.host.children.length, 0);
    assert.equal(state.timers.size, 0);
});

test('pending polling cannot extend beyond the 35-second deadline', async () => {
    const state = setup();
    for (let index = 0; index < 18; index++) {
        state.queued[index].resolve(response(202));
        await flush();
        await state.tick(2000);
    }
    assert.equal(state.calls.length, 18);
    assert.equal(state.host.removed, true);
    assert.equal(state.timers.size, 0);
});

test('leaving the page aborts generation and cancels skeleton and poll timers', async () => {
    const state = setup();
    state.queued[0].resolve(response(202));
    await flush();
    state.window.dispatch('pagehide');
    await state.tick(40000);
    assert.equal(state.calls.length, 1);
    assert.equal(state.calls[0].options.signal.aborted, true);
    assert.equal(state.host.removed, true);
    assert.equal(state.timers.size, 0);
});

test('external content is rendered with text nodes and unsafe citation URLs are rejected', async () => {
    const state = setup();
    state.queued[0].resolve(response(200, {...completed, fragments: [{text: '<img src=x onerror=alert(1)>'}]}));
    await flush();
    assert.equal(state.host.children[0].children[0].nodeType, 3);
    assert.equal(state.host.children[0].children[0].textContent, '<img src=x onerror=alert(1)>');
    for (const url of ['javascript:alert(1)', 'https://user:pass@example.com', '/relative']) {
        const invalid = setup();
        invalid.queued[0].resolve(response(200, {...completed, fragments: [{text: '[1]', url}]}));
        await flush();
        assert.equal(invalid.host.removed, true);
    }
});

test('cached descriptions and permanent NULL outcomes do not start client requests', () => {
    const state = setup({hostPresent: false});
    assert.equal(state.calls.length, 0);
    assert.equal(state.timers.size, 0);
});
