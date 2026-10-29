const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync('pelagia/templates/_pwa_launch.js', 'utf8');

function setup(mode) {
    const classes = new Set();
    const documentEvents = {};
    const windowEvents = {};
    const timers = new Map();
    const document = {
        documentElement: { classList: {
            add: name => classes.add(name), remove: name => classes.delete(name),
        } },
        addEventListener: (name, callback) => { documentEvents[name] = callback; },
    };
    const window = {
        navigator: { standalone: mode === 'ios' },
        matchMedia: query => ({ matches: query === `(display-mode: ${mode})` }),
        addEventListener: (name, callback) => { windowEvents[name] = callback; },
        setTimeout: (callback, delay) => { timers.set(1, { callback, delay }); return 1; },
        clearTimeout: id => timers.delete(id),
    };
    vm.runInNewContext(source, { document, window });
    return { classes, documentEvents, windowEvents, timers };
}

for (const mode of ['standalone', 'fullscreen', 'ios']) {
    test(`${mode} shows the logo until the app is ready`, () => {
        const state = setup(mode);
        assert.ok(state.classes.has('pwa-launching'));
        state.documentEvents.DOMContentLoaded();
        assert.equal(state.classes.size, 0);
        assert.equal(state.timers.size, 0);
    });
}

test('ordinary browser visits do not show a launch overlay', () => {
    const state = setup('browser');
    assert.equal(state.classes.size, 0);
    assert.equal(state.timers.size, 0);
});

test('stalled resources cannot trap the user behind the splash', () => {
    const state = setup('standalone');
    const timer = state.timers.get(1);
    assert.equal(timer.delay, 15000);
    timer.callback();
    assert.equal(state.classes.size, 0);
});

for (const event of ['pagehide', 'pageshow']) {
    test(`${event} clears the splash for history restoration`, () => {
        const state = setup('standalone');
        state.windowEvents[event]();
        assert.equal(state.classes.size, 0);
        assert.equal(state.timers.size, 0);
    });
}
