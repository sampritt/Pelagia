const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function node(tag = 'div') {
    const handlers = {};
    return {
        tag, children: [], dataset: {}, hidden: false, attrs: {}, textContent: '', removed: false,
        classList: {add() {}, remove() {}, toggle() {}},
        appendChild(child) { this.children.push(child); },
        remove() { this.removed = true; },
        setAttribute(name, value) { this.attrs[name] = value; },
        getAttribute(name) { return this.attrs[name] ?? null; },
        removeAttribute(name) { delete this.attrs[name]; delete this.dataset[name]; },
        addEventListener(name, callback) { handlers[name] = callback; },
        click() { handlers.click?.(); },
        querySelectorAll(selector) {
            if (selector === '[data-species-name]' || selector === '[data-site-sightings-tags] > span') return this.children;
            return [];
        },
    };
}

const response = (status, payload) => ({status, ok: status >= 200 && status < 300, json: async () => payload});
const flush = async () => { for (let index = 0; index < 10; index++) await Promise.resolve(); };

function setup(existing = []) {
    let timerId = 0;
    const timers = new Map();
    const tags = node();
    existing.forEach(name => {
        const tag = node('span');
        tag.dataset.speciesName = name.toLowerCase();
        tag.textContent = name;
        tags.appendChild(tag);
    });
    tags.hidden = existing.length === 0;
    const empty = node('p');
    empty.hidden = existing.length > 0;
    const loading = node();
    const more = node('button');
    more.hidden = true;
    const host = node();
    host.dataset.obisSpeciesUrl = '/api/dive-sites/1/obis-species';
    host.querySelector = selector => ({
        '[data-site-sightings-tags]': tags,
        '[data-site-sightings-empty]': empty,
        '[data-site-sightings-loading]': loading,
        '[data-site-sightings-more]': more,
    })[selector] || null;
    host.querySelectorAll = selector => selector === '[data-site-sightings-tags] > span' ? tags.children : [];
    const document = {
        querySelector: selector => selector === '[data-site-sightings]' ? host : null,
        querySelectorAll: () => [],
        addEventListener() {},
        createElement: node,
    };
    const window = {
        PelagiaLoading: {begin: () => () => {}},
        setTimeout(callback, delay) { const id = ++timerId; timers.set(id, {callback, delay}); return id; },
        clearTimeout(id) { timers.delete(id); },
        addEventListener() {}, removeEventListener() {},
    };
    const queued = [];
    const fetch = (url, options) => new Promise((resolve, reject) => queued.push({url, options, resolve, reject}));
    const context = vm.createContext({window, document, fetch, AbortController, URL, console});
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8'), context);
    vm.runInContext('initObisSpecies()', context);
    return {host, tags, empty, loading, more, queued, timers, context};
}

test('completed enrichment appends unique tags and keeps logged species once', async () => {
    const state = setup(['Coral']);
    assert.equal(state.queued[0].options.method, 'POST');
    assert.equal(state.queued[0].options.headers['X-Requested-With'], 'fetch');
    state.queued[0].resolve(response(200, {status: 'complete', species: ['coral', 'Reef Fish']}));
    await flush();
    assert.deepEqual(state.tags.children.map(tag => tag.textContent), ['Coral', 'Reef Fish']);
    assert.equal(state.empty.hidden, true);
    assert.equal(state.loading.removed, true);
});

test('empty completion reveals the empty state', async () => {
    const state = setup();
    assert.equal(state.empty.hidden, true);
    state.queued[0].resolve(response(200, {status: 'complete', species: []}));
    await flush();
    assert.equal(state.tags.hidden, true);
    assert.equal(state.empty.hidden, false);
});

test('pending enrichment polls and invalid responses preserve existing sightings', async () => {
    const state = setup(['Coral']);
    state.queued[0].resolve(response(202, {status: 'pending'}));
    await flush();
    const poll = [...state.timers.values()].find(timer => timer.delay === 2000);
    assert.ok(poll);
    poll.callback();
    await flush();
    assert.equal(state.queued.length, 2);
    state.queued[1].resolve(response(200, {status: 'complete', species: [7]}));
    await flush();
    assert.deepEqual(state.tags.children.map(tag => tag.textContent), ['Coral']);
});

test('large cached sets collapse after twelve tags and can expand', () => {
    const state = setup(Array.from({length: 15}, (_value, index) => `Species ${index + 1}`));
    vm.runInContext('initSightingsDisclosure(document.querySelector("[data-site-sightings]"))', state.context);
    assert.equal(state.tags.children.filter(tag => tag.hidden).length, 3);
    assert.equal(state.more.hidden, false);
    assert.equal(state.more.textContent, 'Show 3 more');
    state.more.click();
    assert.equal(state.tags.children.filter(tag => tag.hidden).length, 0);
    assert.equal(state.more.textContent, 'Show fewer');
});
