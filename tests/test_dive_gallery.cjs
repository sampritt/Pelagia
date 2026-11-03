const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function gallery({reduced = false, count = 4} = {}) {
    const handlers = {}, resize = {};
    const dots = Array.from({length: count}, () => ({
        attrs: {}, handlers: {},
        setAttribute(name, value) { this.attrs[name] = value; },
        addEventListener(name, fn) { this.handlers[name] = fn; },
    }));
    const track = {
        scrollLeft: 0, step: 260, width: 300,
        getBoundingClientRect: () => ({left: 20}),
        addEventListener(name, fn) { handlers[name] = fn; },
        scrollTo({left, behavior}) {
            this.lastBehavior = behavior;
            this.scrollLeft = Math.max(0, Math.min(left, count * this.step - 10 - this.width));
            handlers.scroll();
        },
    };
    track.children = Array.from({length: count}, (_, i) => ({
        getBoundingClientRect: () => ({left: 20 + i * track.step - track.scrollLeft}),
    }));
    const context = vm.createContext({
        document: {addEventListener() {}, querySelectorAll: () => [{querySelector: () => track, querySelectorAll: () => dots}]},
        window: {matchMedia: () => ({matches: reduced}), addEventListener(name, fn) { resize[name] = fn; }},
    });
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8'), context);
    vm.runInContext('initDiveGalleries()', context);
    return {track, dots, resize, handlers, key(key, modifiers = {}) {
        handlers.keydown({key, preventDefault() {}, ...modifiers});
    }};
}

test('gallery keys reach either end and identify the final slide despite the previous-slide peek', () => {
    const g = gallery({reduced: true});
    g.key('End');
    assert.equal(g.track.scrollLeft, 730);
    assert.equal(g.dots[3].attrs['aria-pressed'], 'true');
    assert.equal(g.track.lastBehavior, 'instant');
    g.key('ArrowLeft');
    assert.equal(g.track.scrollLeft, 520);
    assert.equal(g.dots[2].attrs['aria-pressed'], 'true');
    g.key('Home');
    assert.equal(g.track.scrollLeft, 0);
    g.key('ArrowLeft');
    assert.equal(g.track.scrollLeft, 0);
});

test('gallery dots jump directly, scroll updates selection, and modified keys are left alone', () => {
    const g = gallery();
    g.dots[3].handlers.click();
    assert.equal(g.track.scrollLeft, 730);
    assert.equal(g.track.lastBehavior, 'smooth');
    g.key('Home', {ctrlKey: true});
    assert.equal(g.track.scrollLeft, 730);
    g.track.scrollLeft = 260;
    g.handlers.scroll();
    assert.equal(g.dots[1].attrs['aria-pressed'], 'true');
    assert.equal(g.dots[3].attrs['aria-pressed'], 'false');
});

test('a single visual needs no keyboard or scroll listeners', () => {
    const g = gallery({count: 1});
    assert.deepEqual(g.handlers, {});
});
