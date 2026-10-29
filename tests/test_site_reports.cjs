const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function setup(responses) {
    const element = () => ({ handlers: {}, addEventListener(name, callback) { this.handlers[name] = callback; } });
    const host = element(), body = element(), text = element(), retry = element(), window = element();
    host.dataset = {url: '/api/dive-sites/1/report'};
    host.open = false;
    host.querySelector = selector => ({'[data-report-body]': body, '[data-report-text]': text, '[data-report-retry]': retry})[selector];
    let now = new Date('2026-10-25T15:00:00Z').getTime(), calls = [], loading = 0, ended = 0;
    const timers = new Map(), intervals = new Map();
    let nextTimer = 0;
    window.setTimeout = (callback, delay) => { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; };
    window.clearTimeout = id => timers.delete(id);
    window.setInterval = callback => { const id = ++nextTimer; intervals.set(id, callback); return id; };
    window.clearInterval = id => intervals.delete(id);
    window.dispatchEvent = event => window.handlers[event.type]?.(event);
    window.PelagiaLoading = {begin(node, label, markup) {
        loading++; assert.equal(node, body); assert.match(markup, /skeleton-line/);
        return () => { ended++; };
    }};
    class Clock extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
    const document = {readyState: 'complete', querySelector: () => host};
    const fetch = async (url, options) => {
        calls.push({url, options});
        let data = responses.shift();
        if (typeof data === 'function') data = await data();
        if (data instanceof Error) throw data;
        return {ok: true, json: async () => data};
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pelagia/static/js/site-report.js'), 'utf8'), {
        window, document, fetch, AbortController, Event, Intl, Date: Clock,
    });
    return {host, window, text, retry, calls, timers, intervals,
        loading: () => loading, ended: () => ended,
        tick: stamp => { now = new Date(stamp).getTime(); },
        open: () => {host.open = true; host.handlers.toggle();},
        poll: () => { const entry = [...timers.entries()].find(([, timer]) => timer.delay === 2000);
            assert.ok(entry); timers.delete(entry[0]); entry[1].callback(); },
    };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const complete = (date = '2026-10-25') => ({status: 'complete', report: 'Warm water and steady winds today.', date, timezone: 'Pacific/Galapagos'});

test('expansion shows skeleton, polls dependencies, and renders report once', async () => {
    const state = setup([{status: 'pending', reason: 'dependencies'}, complete()]);
    assert.equal(state.calls.length, 0);
    state.open();
    assert.equal(state.loading(), 1);
    await flush();
    state.poll(); await flush();
    assert.equal(state.text.textContent, complete().report);
    assert.equal(state.ended(), 1);
    assert.equal(state.retry.hidden, true);
    assert.equal(state.calls[0].options.method, 'POST');
    assert.equal(state.calls[0].options.headers['X-Requested-With'], 'fetch');
    state.host.open = false; state.host.handlers.toggle(); state.open(); await flush();
    assert.equal(state.calls.length, 2);
});

test('only one request runs during repeated toggles', async () => {
    const state = setup([{status: 'pending'}, complete()]);
    state.open(); state.open(); await flush();
    assert.equal(state.calls.length, 1);
    state.poll(); await flush();
    assert.equal(state.calls.length, 2);
});

test('site-local midnight invalidates visible report', async () => {
    const state = setup([complete(), complete('2026-10-26')]);
    state.open(); await flush();
    state.tick('2026-10-26T05:59:59Z');
    [...state.intervals.values()][0](); await flush();
    assert.equal(state.calls.length, 1);
    state.tick('2026-10-26T06:00:00Z');
    [...state.intervals.values()][0](); await flush();
    assert.equal(state.calls.length, 2);
});

test('daily failed attempt does not automatically retry', async () => {
    const state = setup([{...complete(), status: 'unavailable', report: null}]);
    state.open(); await flush();
    assert.match(state.text.textContent, /unavailable/);
    assert.equal(state.retry.hidden, true);
    [...state.intervals.values()][0](); state.open(); await flush();
    assert.equal(state.calls.length, 1);
});

test('network failures end skeleton and can recheck the server cache', async () => {
    const state = setup([new Error('network'), complete()]);
    state.open(); await flush();
    assert.equal(state.ended(), 1);
    assert.equal(state.retry.hidden, false);
    [...state.intervals.values()][0](); await flush();
    assert.equal(state.calls.length, 1);
    state.retry.handlers.click(); await flush();
    assert.equal(state.text.textContent, complete().report);
});

test('terminal unavailable sites do not offer a retry that cannot help', async () => {
    for (const reason of ['coordinates', 'not_ocean', 'configuration']) {
        const state = setup([{status: 'unavailable', reason}]);
        state.open(); await flush();
        assert.equal(state.retry.hidden, true);
        assert.equal(state.host.dataset.reportState, 'unavailable');
    }
});

test('a late pre-navigation response cannot overwrite the restored page', async () => {
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    const state = setup([() => pending, complete()]);
    state.open(); await flush();
    state.window.handlers.pagehide();
    state.window.handlers.pageshow({persisted: true}); await flush();
    assert.equal(state.host.dataset.reportState, 'ready');
    release({...complete(), report: 'Stale response'}); await flush();
    assert.equal(state.text.textContent, complete().report);
});

test('pagehide aborts request and clears polling; bfcache restarts checking', async () => {
    const state = setup([{status: 'pending'}, complete()]);
    state.open(); await flush();
    state.window.handlers.pagehide();
    assert.equal(state.calls[0].options.signal.aborted, true);
    assert.equal(state.timers.size, 0);
    assert.equal(state.intervals.size, 0);
    state.window.handlers.pageshow({persisted: true}); await flush();
    assert.equal(state.intervals.size, 1);
    assert.equal(state.text.textContent, complete().report);
});
