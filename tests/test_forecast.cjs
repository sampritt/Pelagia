const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({module: {exports: {}}, document: {readyState: 'loading', addEventListener() {}}, Intl});
vm.runInContext(fs.readFileSync('pelagia/static/js/forecast.js', 'utf8'), context);
const api = context.module.exports;

test('forecast grades use the site current cutoffs and feed wind cutoffs before rounding', () => {
    for (const [speed, grade] of [[0,'green'],[.499,'green'],[.5,'yellow'],[.999,'yellow'],[1,'orange'],[1.999,'orange'],[2,'red']]) {
        assert.equal(api.currentGrade(speed)[0], grade);
    }
    for (const [speed, grade] of [[0,'green'],[9.99,'green'],[10,'yellow'],[14.99,'yellow'],[15,'orange'],[19.99,'orange'],[20,'red']]) {
        assert.equal(api.windGrade(speed)[0], grade);
    }
    for (const invalid of [null, -1, NaN, Infinity, true, '1']) {
        assert.equal(api.currentGrade(invalid), null);
        assert.equal(api.windGrade(invalid), null);
    }
});

test('forecast compass, local midnight, and temperature preferences preserve zero and missing data', () => {
    assert.equal(api.compass(350).label, 'N');
    assert.equal(api.compass(337.5).label, 'NNW');
    assert.equal(api.compass(360).degrees, 0);
    assert.equal(api.compass(null), null);
    assert.equal(api.temperature(0, 'f'), '32°F');
    assert.equal(api.temperature(-6, 'c'), '-6°C');
    assert.equal(api.temperature(null, 'c'), '—');
    assert.equal(api.hour(Date.parse('2026-11-07T05:45:00Z') / 1000, 'Asia/Kathmandu'), '11am');
    assert.equal(api.hour(Date.parse('2026-11-07T06:00:00Z') / 1000, 'Pacific/Galapagos'), '12am');
});

test('forecast metric links target existing charts and temperature links target conditions', () => {
    assert.equal(api.linkUrl('/dive-sites/12', 'swell', 1794000000), '/dive-sites/12?forecast_time=1794000000#forecast-swell');
    assert.equal(api.linkUrl('/dive-sites/12', 'conditions', 1794000000), '/dive-sites/12?forecast_time=1794000000#forecast-conditions');
});

test('rows separate swell height and period with a coupled grade and retain independent temperature links', () => {
    const makeNode = tag => ({tag, children: [], dataset: {}, style: {}, attrs: {},
        appendChild(node) {this.children.push(node);}, replaceChildren() {this.children = [];},
        setAttribute(key, value) {this.attrs[key] = value;}});
    context.document.createElement = makeNode;
    context.document.createElementNS = (_, tag) => makeNode(tag);
    const body = makeNode('tbody');
    const panel = {dataset: {siteUrl: '/dive-sites/1'}, querySelector: () => body};
    const point = {time: 1794024000, current_kn: .46, current_direction_deg: 337.5, wind_speed_kn: 12.35, wind_direction_deg: 337.5,
        swell_height_m: .8, swell_period_s: 9, swell: 'Choppy', water_temperature_c: 28.3, air_temperature_c: 26};
    api.renderRows(panel, {timezone: 'Pacific/Galapagos', forecast: {slots: Array(8).fill(point)}}, {length: 'ft', temperature: 'f'});
    assert.equal(body.children.length, 8);
    const cells = body.children[0].children;
    assert.equal(cells.length, 9);
    const links = cells.map(cell => cell.children[0]);
    assert.equal(links[1].textContent, '0.5 kn');
    assert.equal(links[1].dataset.grade, 'green'); // Grade the unrounded model value.
    assert.equal(links[2].textContent, 'NNW');
    assert.equal(links[2].dataset.grade, undefined);
    assert.equal(links[2].children[0].children[1].attrs.transform, 'rotate(337.5)');
    assert.match(links[2].attrs['aria-label'], /Current toward: NNW/);
    assert.match(links[2].href, /#forecast-current$/);
    assert.equal(links[3].textContent, '12.4 kn');
    assert.equal(links[4].textContent, 'NNW');
    assert.equal(links[4].children[0].children[1].attrs.transform, 'rotate(157.5)');
    assert.equal(links[4].children[0].children[1].children[0].attrs.d, 'M0,-6 L3,2 L0,0 L-3,2 Z');
    assert.equal(links[4].dataset.grade, undefined);
    assert.equal(links[5].textContent, '2.6 ft');
    assert.equal(links[6].textContent, '9s');
    assert.equal(links[5].dataset.grade, 'yellow');
    assert.equal(links[6].dataset.grade, links[5].dataset.grade);
    assert.match(links[5].href, /#forecast-swell$/);
    assert.match(links[6].href, /#forecast-swell$/);
    assert.equal(links[7].textContent, '83°F');
    assert.equal(links[8].textContent, '79°F');
    assert.match(links[7].href, /#forecast-conditions$/);
    assert.match(links[8].href, /#forecast-conditions$/);
    api.renderRows(panel, {timezone: 'Pacific/Galapagos', forecast: {slots: Array(8).fill(point)}}, {length: 'ft', temperature: 'f'}, {loading: true});
    assert.equal(body.children.length, 8);
    for (const row of body.children) {
        assert.equal(row.children[0].children[0].textContent, api.hour(point.time, 'Pacific/Galapagos'));
        for (const cell of row.children.slice(1)) {
            const link = cell.children[0];
            assert.match(link.children[0].className, /skeleton/);
            assert.match(link.attrs['aria-label'], /loading/);
            assert.equal(link.dataset.grade, undefined);
            assert.equal(link.textContent, undefined);
        }
    }
});

test('current direction preserves north and wraparound and leaves invalid or missing values neutral', () => {
    const makeNode = tag => ({tag, children: [], dataset: {}, attrs: {},
        appendChild(node) {this.children.push(node);}, replaceChildren() {this.children = [];},
        setAttribute(key, value) {this.attrs[key] = value;}});
    context.document.createElement = makeNode;
    context.document.createElementNS = (_, tag) => makeNode(tag);
    const body = makeNode('tbody');
    const panel = {dataset: {siteUrl: '/dive-sites/1'}, querySelector: () => body};
    for (const degrees of [0, 90, 180, 270, 360, null, undefined, -1, 361, NaN, Infinity, true, '90']) {
        api.renderRows(panel, {timezone: 'UTC', forecast: {slots: [{time: 1794024000, current_direction_deg: degrees}]}},
            {length: 'm', temperature: 'c'});
        const link = body.children[0].children[2].children[0];
        assert.equal(link.dataset.grade, undefined);
        const valid = typeof degrees === 'number' && Number.isFinite(degrees) && degrees >= 0 && degrees <= 360;
        assert.equal(link.textContent, valid ? api.compass(degrees).label : '—');
        assert.equal(link.children.length, valid ? 1 : 0);
        if (valid) assert.equal(link.children[0].children[1].attrs.transform, `rotate(${degrees % 360})`);
        else assert.match(link.attrs['aria-label'], /unavailable/);
    }
});

test('tide extrema show High or Low and precise local time without numeric heights', () => {
    const makeNode = tag => ({tag, children: [], attrs: {}, className: '',
        appendChild(node) {this.children.push(node);}, append(...nodes) {this.children.push(...nodes);},
        replaceChildren() {this.children = [];}, setAttribute(key, value) {this.attrs[key] = value;}});
    context.document.createElement = makeNode;
    context.document.createElementNS = (_, tag) => makeNode(tag);
    const host = makeNode('div'); host.clientWidth = 320;
    const panel = {querySelector: () => host, getAttribute: () => 'Gordon Rocks'};
    const start = Date.parse('2026-11-07T06:00:00Z') / 1000;
    api.renderTide(panel, {timezone: 'Pacific/Galapagos', forecast: {start, end: start + 86400, times: Array.from({length: 8}, (_, i) => start + i * 10800),
        tide: [{time: start, value: 0}, {time: start + 3600, value: 1}, {time: start + 86400, value: 0}],
        extrema: [{time: start + 1800, value: .8, kind: 'High'}, {time: start + 43200, value: -.8, kind: 'Low'}]}}, 'm');
    const texts = host.children[0].children.filter(node => node.tag === 'text');
    assert.deepEqual(texts.filter(n => n.attrs.class === 'forecast-tide-label').map(n => n.textContent), ['High', 'Low']);
    assert.deepEqual(texts.filter(n => n.attrs.class === 'forecast-tide-time').map(n => n.textContent), ['12:30am', '12:00pm']);
    assert.ok(texts.every(n => !/[0-9]+\.[0-9]+\s*m/.test(n.textContent)));
});

test('smooth tide curve preserves sampled heights and does not overshoot a turn', () => {
    const points = [{x: 0, y: 10}, {x: 5, y: 8}, {x: 15, y: 0}, {x: 17, y: 2}, {x: 35, y: 10}];
    const path = api.tidePath(points);
    const segments = [...path.matchAll(/C([\d.e+-]+),([\d.e+-]+) ([\d.e+-]+),([\d.e+-]+) ([\d.e+-]+),([\d.e+-]+)/g)];
    assert.equal(segments.length, points.length - 1);
    segments.forEach((match, i) => {
        const [, , cy1, , cy2, endX, endY] = match.map(Number);
        assert.equal(endX, points[i + 1].x);
        assert.equal(endY, points[i + 1].y);
        const lo = Math.min(points[i].y, endY), hi = Math.max(points[i].y, endY);
        for (let n = 0; n <= 100; n++) {
            const t = n / 100, u = 1 - t;
            const y = u ** 3 * points[i].y + 3 * u ** 2 * t * cy1 + 3 * u * t ** 2 * cy2 + t ** 3 * endY;
            assert.ok(y >= lo - 1e-9 && y <= hi + 1e-9);
        }
    });
});

test('tide rendering separates missing intervals and rounds estimated local times to minutes', () => {
    const node = tag => ({tag, children: [], attrs: {}, appendChild(n) {this.children.push(n);},
        append(...nodes) {this.children.push(...nodes);}, replaceChildren() {this.children = [];},
        setAttribute(k, v) {this.attrs[k] = v;}});
    context.document.createElement = node;
    context.document.createElementNS = (_, tag) => node(tag);
    const host = node('div'); host.clientWidth = 240;
    const start = Date.parse('2026-11-07T06:00:00Z') / 1000;
    const tide = [0, 1, null, 1, 0].map((value, i) => ({time: start + i * 3600, value}));
    api.renderTide({querySelector: () => host, getAttribute: () => 'Test site'}, {
        timezone: 'Pacific/Galapagos', forecast: {start, end: start + 86400,
            times: Array.from({length: 8}, (_, i) => start + i * 10800), tide,
            extrema: [{time: start + 3599, value: 1, kind: 'High'}]},
    });
    const svg = host.children[0];
    assert.equal(svg.children.filter(n => n.attrs.class === 'forecast-tide-line').length, 2);
    assert.equal(svg.children.find(n => n.attrs.class === 'forecast-tide-time').textContent, '1:00am');
    assert.match(svg.attrs['aria-label'], /estimates interpolated from hourly model/);
    assert.deepEqual(svg.children.filter(n => n.attrs.class === 'forecast-tide-axis').map(n => n.textContent), ['12am', '6am', '12pm', '6pm', '12am']);
});
