const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('editing and closing settings does not save or reload the page', () => {
    const handlers = {};
    const open = {};
    const close = {};
    const dialog = {
        open: false,
        addEventListener(name, handler) {handlers[name] = handler;},
        querySelector() {return {addEventListener(name, handler) {close[name] = handler;}};},
        showModal() {this.open = true;},
        close() {this.open = false; handlers.close?.();},
        getBoundingClientRect: () => ({left: 10, right: 100, top: 10, bottom: 100}),
    };
    const context = vm.createContext({
        document: {
            querySelector: (selector) => selector === '[data-profile-settings]' ? dialog
                : {addEventListener(name, handler) {open[name] = handler;}},
            addEventListener() {},
        },
        window: {location: {reload() {assert.fail('Closing settings must not reload');}}},
        fetch() {assert.fail('Settings must only save through form submission');},
    });
    vm.runInContext(fs.readFileSync('pelagia/static/js/app.js', 'utf8') + '\ninitProfileSettings();', context);
    open.click();
    assert.equal(dialog.open, true);
    assert.equal(handlers.input, undefined);
    assert.equal(handlers.change, undefined);
    close.click();
    assert.equal(dialog.open, false);
    open.click();
    handlers.click({target: dialog, clientX: 0, clientY: 0});
    assert.equal(dialog.open, false);
});
