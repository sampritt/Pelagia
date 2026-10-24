const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync('pelagia/static/js/welcome.js', 'utf8');

function setup({ reducedMotion = false } = {}) {
    let now = 0;
    let nextTimer = 0;
    const timers = new Map();
    const classes = new Set(['welcome-pending']);
    const handlers = {};
    let removed = false;
    let focus = 'splash';
    let url = '/welcome';
    const background = { tagName: 'MAIN', inert: false };
    const alreadyInert = { tagName: 'DIV', inert: true };
    const theme = { content: '#062a46' };
    const button = { focus() { focus = 'continue'; }, addEventListener(name, fn) { handlers[name] = fn; } };
    const splash = {
        dataset: { feedUrl: '/home' },
        focus() { focus = 'splash'; },
        remove() { removed = true; },
        querySelector() { return button; },
        addEventListener(name, fn) { handlers[name] = fn; },
    };
    const document = {
        body: { children: [splash, background, alreadyInert], classList: {
            add(name) { classes.add(name); }, remove(...names) { names.forEach(name => classes.delete(name)); },
        } },
        querySelector(selector) { return selector.includes('theme-color') ? theme : splash; },
        getElementById() { return { focus() { focus = 'feed'; } }; },
    };
    const window = {
        matchMedia() { return { matches: reducedMotion }; },
        history: { state: { retained: true }, replaceState(state, unused, destination) { assert.equal(state.retained, true); url = destination; } },
        setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { at: now + delay, fn }); return id; },
        clearTimeout(id) { timers.delete(id); },
        addEventListener(name, fn) { handlers[name] = fn; },
    };
    vm.runInNewContext(source, { document, window });
    function tick(ms) {
        now += ms;
        for (const [id, timer] of [...timers]) {
            if (timer.at <= now) { timers.delete(id); timer.fn(); }
        }
    }
    return { background, alreadyInert, theme, classes, handlers, tick, timers,
        get removed() { return removed; }, get focus() { return focus; }, get url() { return url; } };
}

test('welcome reveals the existing feed and preserves prior inert state', () => {
    const page = setup();
    assert.equal(page.url, '/home');
    assert.equal(page.background.inert, true);
    page.tick(1700);
    assert.equal(page.classes.has('welcome-revealing'), true);
    page.tick(1000);
    assert.equal(page.removed, true);
    assert.equal(page.background.inert, false);
    assert.equal(page.alreadyInert.inert, true);
    assert.equal(page.theme.content, '#062a46');
    assert.equal(page.focus, 'feed');
    assert.equal(page.classes.size, 0);
    assert.equal(page.timers.size, 0);
});

test('keyboard users can reach Continue and skip the pause with Escape', () => {
    const page = setup();
    let prevented = false;
    page.handlers.keydown({ key: 'Tab', preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(page.focus, 'continue');
    page.handlers.keydown({ key: 'Escape' });
    page.tick(1000);
    assert.equal(page.removed, true);
    assert.equal(page.focus, 'feed');
});

test('leaving during the intro cancels timers without stealing focus', () => {
    const page = setup();
    page.handlers.pagehide();
    page.tick(5000);
    assert.equal(page.removed, true);
    assert.equal(page.background.inert, false);
    assert.equal(page.focus, 'splash');
    assert.equal(page.timers.size, 0);
    assert.equal(page.url, '/home');
});

test('reduced motion finishes the welcome in less than a second', () => {
    const page = setup({ reducedMotion: true });
    page.tick(500);
    page.tick(200);
    assert.equal(page.removed, true);
    assert.equal(page.background.inert, false);
});

test('modified Continue clicks retain normal link behavior', () => {
    const page = setup();
    let prevented = false;
    page.handlers.click({ button: 0, metaKey: true, preventDefault() { prevented = true; } });
    assert.equal(prevented, false);
    assert.equal(page.classes.has('welcome-revealing'), false);
});
