const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function node() {
    const classes = new Set();
    return {
        attrs: {}, handlers: {}, hidden: false, isConnected: true,
        textContent: '', scrollHeight: 100, clientHeight: 62,
        classList: {toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name)},
        setAttribute(name, value) { this.attrs[name] = value; },
        getAttribute(name) { return this.attrs[name] ?? null; },
        addEventListener(name, callback) { this.handlers[name] = callback; },
    };
}

function card(id) {
    const reportBody = node(), reportText = node(), toggle = node(), header = node();
    header.style = {};
    header.height = 60;
    header.getBoundingClientRect = () => ({height: header.height});
    toggle.hidden = true;
    toggle.attrs['aria-expanded'] = 'false';
    const item = node();
    item.dataset = {
        reportUrl: `/api/dive-sites/${id}/report`,
        descriptionUrl: `/api/dive-sites/${id}/description`,
        conditionsUrl: `/api/dive-sites/${id}/conditions`,
    };
    item.querySelector = selector => ({
        '[data-followed-report-body]': reportBody,
        '[data-followed-report-text]': reportText,
        '[data-followed-report-toggle]': toggle,
        '.explore-card-copy': header,
    })[selector];
    return {item, reportBody, reportText, toggle, header};
}

test('maps align to the tallest natural header and recalculate when the viewport changes', async () => {
    const cards = [card(1), card(2)];
    cards[1].header.height = 85;
    const state = setup(cards, async () => response(200, {status: 'complete', report: 'A calm morning.'}));
    await flush();
    assert.equal(cards[0].header.style.minHeight, '85px');
    assert.equal(cards[1].header.style.minHeight, '85px');
    cards[1].header.height = 60;
    state.window.handlers.resize();
    assert.equal(cards[0].header.style.minHeight, '60px');
    assert.equal(cards[1].header.style.minHeight, '60px');
});

const response = (status, data) => ({status, ok: status >= 200 && status < 300, json: async () => data});
const flush = async () => {
    for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
};

function setup(cards, fetch) {
    const window = node();
    let timer = 0;
    const timers = new Map();
    window.setTimeout = (callback, delay) => { const id = ++timer; timers.set(id, {callback, delay}); return id; };
    window.clearTimeout = id => timers.delete(id);
    window.requestAnimationFrame = callback => callback();
    let starts = 0, finishes = 0;
    window.PelagiaLoading = {begin() { starts++; return () => { finishes++; }; }};
    const document = {readyState: 'complete', querySelectorAll: () => cards.map(item => item.item)};
    vm.runInNewContext(fs.readFileSync('pelagia/static/js/feed-site-reports.js', 'utf8'), {
        window, document, fetch, AbortController, Date, Promise, Error,
    });
    return {window, timers, starts: () => starts, finishes: () => finishes};
}

test('every followed card loads its cached report and expands without another request', async () => {
    const cards = [card(1), card(2)];
    const calls = [];
    const state = setup(cards, async (url, options) => {
        calls.push({url, options});
        return response(200, {status: 'complete', report: `Daily report for ${url.includes('/1/') ? 'one' : 'two'} with enough words to fill the four-line preview.`});
    });
    await flush();
    assert.equal(calls.length, 2);
    assert.equal(state.starts(), 2);
    assert.equal(state.finishes(), 2);
    for (const [index, card] of cards.entries()) {
        assert.match(card.reportText.textContent, new RegExp(index ? 'two' : 'one'));
        assert.equal(card.item.dataset.reportState, 'ready');
        assert.equal(card.toggle.hidden, false);
        assert.equal(card.toggle.textContent, 'Read more');
        card.toggle.handlers.click();
        assert.equal(card.reportText.classList.contains('is-expanded'), true);
        assert.equal(card.toggle.textContent, 'Show less');
        assert.equal(calls.length, 2);
    }
});

test('a cold feed warms description and conditions caches before requesting the report again', async () => {
    const followed = card(7);
    const calls = [];
    let reportCalls = 0;
    setup([followed], async (url, options) => {
        calls.push({url, options});
        if (url.endsWith('/report')) {
            reportCalls++;
            return reportCalls === 1
                ? response(202, {status: 'pending', reason: 'dependencies'})
                : response(200, {status: 'complete', report: 'Currents ease through the morning before rebuilding later today.'});
        }
        return response(200, {status: 'complete'});
    });
    await flush();
    assert.equal(reportCalls, 2);
    assert.deepEqual(calls.map(call => call.url), [
        '/api/dive-sites/7/report', '/api/dive-sites/7/description',
        '/api/dive-sites/7/conditions', '/api/dive-sites/7/report',
    ]);
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(calls[2].options.method, 'GET');
    assert.equal(calls[0].options.headers['X-Requested-With'], 'fetch');
    assert.equal(followed.item.dataset.reportState, 'ready');
});

test('short reports do not show a redundant disclosure and failures stay compact', async () => {
    const short = card(1), failed = card(2);
    short.reportText.scrollHeight = short.reportText.clientHeight;
    setup([short, failed], async url => url.includes('/1/')
        ? response(200, {status: 'complete', report: 'Light currents hold through the day.'})
        : response(503, {status: 'unavailable'}));
    await flush();
    assert.equal(short.toggle.hidden, true);
    assert.equal(failed.reportText.textContent, 'Today’s report is unavailable.');
    assert.equal(failed.toggle.hidden, true);
    assert.equal(failed.item.dataset.reportState, 'unavailable');
});

test('leaving the feed aborts all in-flight site report requests', async () => {
    const cards = [card(1), card(2)];
    const signals = [];
    const state = setup(cards, (_url, options) => {
        signals.push(options.signal);
        return new Promise(() => {});
    });
    await flush();
    state.window.handlers.pagehide();
    assert.equal(signals.length, 2);
    assert.ok(signals.every(signal => signal.aborted));
    assert.equal(state.timers.size, 0);
});
