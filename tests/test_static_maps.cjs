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
