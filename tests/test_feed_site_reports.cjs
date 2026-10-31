const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function node() {
    const classes = new Set();
    return {
        attrs: {}, dataset: {}, handlers: {}, hidden: false, isConnected: true,
        textContent: '', scrollHeight: 100, clientHeight: 62,
        classList: {toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name)},
        setAttribute(name, value) { this.attrs[name] = value; },
        getAttribute(name) { return this.attrs[name] ?? null; },
        removeAttribute(name) { delete this.attrs[name]; },
        addEventListener(name, callback) { this.handlers[name] = callback; },
    };
}

function card(id) {
    const reportBody = node(), reportText = node(), swell = node(), wind = node(), visibility = node();
    const item = node();
    item.dataset = {
        reportState: 'loading',
        reportUrl: `/api/dive-sites/${id}/report`,
        descriptionUrl: `/api/dive-sites/${id}/description`,
        conditionsUrl: `/api/dive-sites/${id}/conditions`,
        visibilityUrl: `/api/dive-sites/${id}/visibility`,
    };
    item.querySelector = selector => ({
        '[data-followed-report-body]': reportBody,
        '[data-followed-report-text]': reportText,
        '[data-followed-swell]': swell,
        '[data-followed-wind]': wind,
        '[data-followed-visibility]': visibility,
    })[selector];
    return {item, reportBody, reportText, swell, wind, visibility};
}

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
    const track = node();
    track.scrollWidth = 1000;
    track.scrollLeft = 0;
    track.scrollTo = ({left}) => { track.scrollLeft = left; };
    track.scrollBy = ({left}) => { track.scrollLeft += left; };
    cards.forEach(card => { card.item.getBoundingClientRect = () => ({width: 300}); });
    const document = {
        readyState: 'complete',
        querySelectorAll: () => cards.map(item => item.item),
        querySelector: selector => selector === '[data-site-reports-track]' ? track : null,
    };
    vm.runInNewContext(fs.readFileSync('pelagia/static/js/feed-site-reports.js', 'utf8'), {
        window, document, fetch, AbortController, Date, Promise, Error,
    });
    return {window, timers, track, starts: () => starts, finishes: () => finishes};
}

test('every followed card loads its cached report preview', async () => {
    const cards = [card(1), card(2)];
    const calls = [];
    const state = setup(cards, async (url, options) => {
        calls.push({url, options});
        if (url.endsWith('/conditions')) return response(200, {status: 'complete', current: {swell: 'Choppy', swell_height_m: 0.65, swell_period_s: 10, wind_speed_kn: 12.3}});
        if (url.endsWith('/visibility')) return response(200, {status: 'complete', clarity: 'excellent'});
        return response(200, {status: 'complete', report: `Daily report for ${url.includes('/1/') ? 'one' : 'two'} with enough words to fill the four-line preview.`});
    });
    await flush();
    assert.equal(calls.length, 6);
    assert.equal(state.starts(), 2);
    assert.equal(state.finishes(), 2);
    for (const [index, card] of cards.entries()) {
        assert.match(card.reportText.textContent, new RegExp(index ? 'two' : 'one'));
        assert.equal(card.item.dataset.reportState, 'ready');
        assert.equal(card.swell.textContent, '0.7m @ 10s');
        assert.equal(card.swell.dataset.grade, 'yellow');
        assert.equal(card.wind.dataset.grade, 'yellow');
        assert.equal(card.visibility.dataset.grade, 'green');
        assert.equal(card.wind.textContent, '12.3 kn');
        assert.equal(card.visibility.textContent, 'excellent');
    }
    assert.equal(calls.length, 6);
});

test('feet, descriptor colors, and wind boundaries are normalized', async () => {
    const cards = [card(1), card(2), card(3), card(4)];
    cards.forEach(card => { card.item.dataset.lengthUnit = 'ft'; });
    const speeds = [9.9, 10, 15, 20];
    const swell = ['Calm', 'Choppy', 'Rough', 'Very rough'];
    const clarity = ['good', 'fair', 'poor', 'very poor'];
    setup(cards, async url => {
        const index = Number(url.match(/dive-sites\/(\d+)/)[1]) - 1;
        if (url.endsWith('/conditions')) return response(200, {status: 'complete', current: {swell: swell[index], swell_height_m: .65, swell_period_s: 10, wind_speed_kn: speeds[index]}});
        if (url.endsWith('/visibility')) return response(200, {status: 'complete', clarity: clarity[index]});
        return response(200, {status: 'complete', report: 'Conditions.'});
    });
    await flush();
    const grades = ['green', 'yellow', 'orange', 'red'];
    cards.forEach((card, i) => {
        assert.equal(card.swell.textContent, '2ft @ 10s');
        assert.equal(card.swell.dataset.grade, grades[i]);
        assert.equal(card.wind.dataset.grade, grades[i]);
        assert.equal(card.visibility.dataset.grade, grades[i]);
        assert.match(card.wind.attrs['aria-label'], /Light|Moderate|Fresh|Strong/);
    });
});

test('missing values and visibility failures leave available conditions intact', async () => {
    const followed = card(1);
    setup([followed], async url => {
        if (url.endsWith('/conditions')) return response(200, {status: 'complete', current: {swell: null, wind_speed_kn: 0}});
        if (url.endsWith('/visibility')) return response(503, {status: 'unavailable'});
        return response(200, {status: 'complete', report: 'Calm seas.'});
    });
    await flush();
    assert.equal(followed.swell.textContent, '—');
    assert.equal(followed.wind.textContent, '0 kn');
    assert.equal(followed.visibility.textContent, '');
    assert.equal(followed.item.dataset.conditionsState, 'ready');
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
    assert.equal(calls.filter(call => call.url.endsWith('/description')).length, 1);
    assert.ok(calls.some(call => call.url.endsWith('/conditions')));
    assert.ok(calls.some(call => call.url.endsWith('/visibility')));
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[0].options.headers['X-Requested-With'], 'fetch');
    assert.equal(followed.item.dataset.reportState, 'ready');
});

test('short reports stay compact and failures remain actionable', async () => {
    const short = card(1), failed = card(2);
    short.reportText.scrollHeight = short.reportText.clientHeight;
    setup([short, failed], async url => url.includes('/1/')
        ? response(200, {status: 'complete', report: 'Light currents hold through the day.'})
        : response(503, {status: 'unavailable'}));
    await flush();
    assert.equal(failed.reportText.textContent, 'Today’s report is unavailable. Open the site for conditions and forecasts.');
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
    assert.equal(signals.length, 4);
    assert.ok(signals.every(signal => signal.aborted));
    assert.equal(state.timers.size, 0);
});


test('a stalled request times out with an actionable unavailable state', async () => {
    const followed = card(1);
    const state = setup([followed], (_url, {signal}) => new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('Aborted')));
    }));
    [...state.timers.values()].find(timer => timer.delay === 120000).callback();
    await flush();
    assert.equal(followed.item.dataset.reportState, 'unavailable');
    assert.match(followed.reportText.textContent, /Open the site/);
    assert.equal(state.finishes(), 1);
});

test('returning through browser Back resumes interrupted reports and preserves completed ones', async () => {
    const cards = [card(1), card(2)];
    let resumed = false;
    const calls = [];
    const state = setup(cards, (url, {signal}) => {
        calls.push(url);
        if (url.includes('/2/') && !resumed) return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('Aborted'))));
        return Promise.resolve(response(200, {status: 'complete', report: 'Settled conditions.'}));
    });
    await flush();
    state.window.handlers.pagehide();
    await flush();
    assert.equal(state.timers.size, 0);
    resumed = true;
    state.window.handlers.pageshow({persisted: true});
    await flush();
    assert.equal(calls.filter(url => url.endsWith('/1/report')).length, 1);
    assert.equal(calls.filter(url => url.endsWith('/2/report')).length, 2);
    assert.ok(cards.every(card => card.item.dataset.reportState === 'ready'));
});

test('the swipe track keeps keyboard navigation without visual controls', async () => {
    const state = setup([card(1), card(2), card(3)], async () => response(200, {status: 'complete', report: 'Calm seas.'}));
    await flush();
    let prevented = 0;
    const press = key => state.track.handlers.keydown({key, preventDefault() { prevented++; }});
    press('ArrowRight');
    assert.equal(state.track.scrollLeft, 312);
    press('ArrowLeft');
    assert.equal(state.track.scrollLeft, 0);
    press('End');
    assert.equal(state.track.scrollLeft, 1000);
    press('Home');
    assert.equal(state.track.scrollLeft, 0);
    press('Tab');
    assert.equal(prevented, 4);
});
