const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync('pelagia/static/js/app.js', 'utf8');
const pickerSource = source.slice(source.indexOf('function initProfileLocation()'), source.indexOf('document.addEventListener("DOMContentLoaded", initProfileLocation)'));
function element() {
    return {value: '', hidden: true, children: [], handlers: {}, attrs: {},
        addEventListener(type, fn) {(this.handlers[type] ||= []).push(fn);},
        emit(type, event = {}) {for (const fn of this.handlers[type] || []) fn(event);},
        setAttribute(key, value) {this.attrs[key] = value;},
        removeAttribute(key) {delete this.attrs[key];},
        replaceChildren() {this.children = [];}, appendChild(child) {this.children.push(child);},
        setCustomValidity(value) {this.validationMessage = value;}, scrollIntoView() {},
    };
}
function setup() {
    const input = element(), results = element(), field = element(), document = element();
    field.querySelector = selector => selector.endsWith('-input]') ? input : selector.endsWith('-results]') ? results : {textContent: JSON.stringify(['Alaska', 'Bonaire', 'British Virgin Islands'])};
    field.contains = target => target === input || results.children.includes(target);
    document.querySelector = () => field;
    document.createElement = element;
    input.focus = () => {document.activeElement = input; input.emit('focus');};
    const context = vm.createContext({document, window: {setTimeout: fn => fn()}});
    vm.runInContext(pickerSource + '\ninitProfileLocation();', context);
    input.focus();
    const type = value => {input.value = value; input.emit('input');};
    const key = value => input.emit('keydown', {key: value, preventDefault() {}});
    return {input, results, document, type, key};
}
test('typing filters catalogue regions and clicking chooses the full value', () => {
    const {input, results, type} = setup();
    type('virgin');
    assert.equal(results.hidden, false);
    assert.deepEqual(results.children.map(option => option.textContent), ['British Virgin Islands']);
    results.children[0].emit('click');
    assert.equal(input.value, 'British Virgin Islands');
    assert.equal(input.validationMessage, '');
    assert.equal(results.hidden, true);
});
test('arrow keys and Enter select a region without submitting the form', () => {
    const {input, results, type, key} = setup();
    type('a'); key('ArrowUp');
    assert.equal(input.attrs['aria-activedescendant'], 'profileLocationOption-2');
    assert.equal(results.children[2].attrs['aria-selected'], 'true');
    key('Enter');
    assert.equal(input.value, 'British Virgin Islands');
    assert.equal(input.attrs['aria-expanded'], 'false');
});
test('Escape, outside clicks and blur dismiss suggestions; arrows reopen them', () => {
    const {input, results, document, key} = setup();
    key('Escape'); assert.equal(results.hidden, true);
    key('ArrowDown'); assert.equal(results.hidden, false);
    document.emit('click', {target: {}}); assert.equal(results.hidden, true);
    input.focus(); document.activeElement = {}; input.emit('blur');
    assert.equal(results.hidden, true);
    assert.equal(input.attrs['aria-activedescendant'], undefined);
});
test('unmatched input displays an empty state and clearing the optional field is valid', () => {
    const {input, results, type} = setup();
    type('Not a region');
    assert.equal(results.children[0].attrs.role, 'status');
    assert.match(results.children[0].textContent, /No matches/);
    assert.match(input.validationMessage, /Choose a location/);
    type('  bonaire  '); assert.equal(input.validationMessage, '');
    type(''); assert.equal(input.validationMessage, '');
});
