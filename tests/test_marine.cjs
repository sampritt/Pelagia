const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
function node(tag = 'div') {
    return {tag, dataset: {}, attrs: {}, children: [], handlers: {},
        appendChild(child) { this.children.push(child); return child; },
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
        addEventListener(k, v) { this.handlers[k] = v; },
        matches(s) { return this.dataset.chart && s.includes('marine-chart'); },
    };
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function setup(coordinates = 'true') {
    const host = node(), status = node(), retry = node(), charts = [node(), node()], values = ['strength', 'temperature', 'tide'].map(v => { const n = node(); n.dataset.marineValue = v; return n; });
    charts.forEach(n => { n.dataset.chart = true; });
    const buttons = ['daily', 'hourly'].map(v => { const n = node(); n.dataset.marineRange = v; return n; });
    host.dataset = {coordinates, url: '/api/dive-sites/1/conditions', temperatureUnit: 'f', lengthUnit: 'ft'};
    host.querySelector = s => ({'[data-marine-status]':status,'[data-marine-retry]':retry,'[data-marine-chart="current"]':charts[0],'[data-marine-chart="tide"]':charts[1]})[s];
    host.querySelectorAll = s => s.includes('value') ? values : buttons;
    const window = node(); let id = 0; const timers = new Map(); const requests = []; let ended = 0;
    window.setTimeout = (fn, delay) => { timers.set(++id, {fn, delay}); return id; }; window.clearTimeout = n => timers.delete(n);
    window.PelagiaLoading = {begin: () => () => { ended++; }};
    const document = {readyState: 'complete', querySelector: () => host, createElement: node, createElementNS: (_, tag) => node(tag)};
    const context = vm.createContext({window, document, Intl, Date, AbortController, module: {exports: {}}, fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}))});
    vm.runInContext(fs.readFileSync('pelagia/static/js/marine.js', 'utf8'), context);
    return {host, status, retry, charts, values, buttons, window, timers, requests, context, ended: () => ended};
}
function data() {
    const points = Array.from({length: 48}, (_, i) => ({time:1792940400 + i * 3600, value: .5}));
    return {status:'complete', timezone:'Pacific/Galapagos', fetched_at:1792940400,
        current:{strength:'Moderate', temperature_c:28.3, tide:'Rising', velocity_kn:.5, timestamps:{ocean_current_velocity:1792940400}},
        charts:{current_daily:points.slice(0,7), current_hourly:points, tide_hourly:points.slice(0,24)}};
}
test('forecast renders Fahrenheit, accessible charts, and range toggle without another request', async () => {
    const s = setup(); s.requests[0].resolve({status:200,ok:true,json:async()=>data()}); await flush();
    assert.equal(s.values[1].textContent,'83°F'); assert.equal(s.values[0].textContent,'Moderate');
    assert.equal(s.ended(),5); assert.equal(s.timers.size,0); assert.equal(s.retry.hidden,true);
    s.buttons[1].handlers.click(); assert.equal(s.requests.length,1); assert.equal(s.buttons[1].attrs['aria-pressed'],'true');
    assert.equal(s.charts[0].children[1].children[0].children.filter(n=>n.tag==='rect').length,48);
});
test('failure stops loading and retry issues one new request', async () => {
    const s=setup();s.requests[0].reject(new Error());await flush();
    assert.equal(s.status.textContent,'Forecast unavailable');assert.equal(s.retry.hidden,false);assert.equal(s.ended(),5);
    s.retry.handlers.click();assert.equal(s.requests.length,2);
});
test('missing coordinates never fetch; leaving page aborts and cancels timers', () => {
    const missing=setup('false');assert.equal(missing.requests.length,0);assert.equal(missing.retry.hidden,true);
    const s=setup();s.window.handlers.pagehide();assert.equal(s.requests[0].options.signal.aborted,true);assert.equal(s.timers.size,0);assert.equal(s.ended(),5);
});
test('pending response polls; deadline aborts requests', async () => {
    const s=setup();s.requests[0].resolve({status:202});await flush();
    const poll=[...s.timers.values()].find(t=>t.delay===2000);assert.ok(poll);poll.fn();assert.equal(s.requests.length,2);
    [...s.timers.values()].find(t=>t.delay===20000).fn();assert.equal(s.requests[1].options.signal.aborted,true);
    assert.equal(s.status.textContent,'Forecast unavailable');
});
test('site-local labels include 12am and handle DST hours', () => {
    const s=setup('false'), api=s.context.module.exports;
    assert.equal(api.localHour(Date.parse('2026-10-25T06:00:00Z')/1000,'Pacific/Galapagos'),'12am');
    assert.equal(api.hourNumber(Date.parse('2026-11-01T06:00:00Z')/1000,'America/New_York'),1);
});
test('chart inspection works with arrow keys, preserves selection on resize, and exposes exact values', async () => {
    const s=setup();const d=data();d.charts.current_daily[6].value=1.25;
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    const chart=s.charts[0], scroll=chart.children[1];
    let prevented=false;scroll.handlers.keydown({key:'End',preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(chart.dataset.selectedIndex,'6');
    assert.equal(chart.children[2].children[1].textContent,'1.25 kn');
    s.host.clientWidth=320; s.window.handlers.resize();assert.equal(chart.dataset.selectedIndex,'6');
    assert.equal(chart.children[2].children[1].textContent,'1.25 kn');
});
test('daily chart fits a narrow phone and pointer selection does not add dozens of tab stops', async () => {
    const s=setup();s.charts[0].clientWidth=270;
    s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const svg=s.charts[0].children[1].children[0];
    assert.equal(svg.attrs.width,'270');
    assert.equal(svg.children.filter(n=>n.attrs.tabindex).length,0);
    svg.getBoundingClientRect=()=>({left:0,width:270});
    svg.handlers.pointerdown({clientX:200,type:'pointerdown',pointerType:'touch'});
    assert.ok(Number(s.charts[0].dataset.selectedIndex)>0);
});
