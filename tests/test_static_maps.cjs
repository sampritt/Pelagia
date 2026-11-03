const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('map tiles use the actual thumbnail viewport so the location stays underneath its pin', () => {
    const context = vm.createContext({document: {addEventListener() {}}, window: {}});
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8'), context);
    vm.runInContext('ensureTileLayer = () => ({}); renderTileGrid = (_layer, options) => { globalThis.viewport = options; };', context);
    for (const [width, height] of [[56, 56], [64, 64], [320, 216]]) {
        const pin = {style: {}};
        context.map = {
            clientWidth: width, clientHeight: height,
            dataset: {mapLat: '54.1', mapLng: '-132.9', mapZoom: '10'},
            classList: {add() {}, remove() {}},
            querySelector: () => pin,
        };
        vm.runInContext('renderMiniTileMap(map)', context);
        assert.equal(context.viewport.width, width);
        assert.equal(context.viewport.height, height);
        assert.equal(pin.style.left, '50%');
        assert.equal(pin.style.top, '50%');
    }
});

test('static maps rerender at their new size without installing duplicate observers', () => {
    const observers = [];
    const map = {clientWidth: 260, clientHeight: 240};
    const context = vm.createContext({
        document: {addEventListener() {}, querySelectorAll: () => [map]}, window: {},
        ResizeObserver: class {
            constructor(callback) { this.callback = callback; observers.push(this); }
            observe(target) { assert.equal(target, map); }
        },
    });
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8'), context);
    vm.runInContext('renderMiniTileMap = map => { globalThis.lastWidth = map.clientWidth; }; initStaticMaps(); initStaticMaps();', context);
    assert.equal(observers.length, 1);
    map.clientWidth = 530;
    observers[0].callback();
    assert.equal(context.lastWidth, 530);
});
