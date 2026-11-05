const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup(rating = '') {
    const element = (value = '') => ({value, handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; },
        setCustomValidity(message) { this.validationMessage = message; }});
    const name = element('Alert Rock'), id = element('1'), body = element('Original text'), action = element();
    const title = {}, legend = {};
    const stars = Array.from({length: 5}, (_, i) => Object.assign(element(String(i + 1)), {checked: rating === String(i + 1)}));
    const section = {dataset: {diveReview: 'site'}, querySelectorAll: () => stars,
        querySelector: selector => ({textarea: body, '[data-review-action]': action, '[data-review-title]': title, '[data-review-legend]': legend})[selector]};
    const form = {querySelectorAll: () => [section], querySelector: selector => selector === '[data-site-input]' ? name : id};
    const context = vm.createContext({document: {addEventListener() {}}, window: {}, form});
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../pelagia/static/js/app.js'), 'utf8'), context);
    const refresh = vm.runInContext('initDiveReviews(form)', context);
    const click = value => {
        const star = stars[Number(value) - 1];
        const changed = !star.checked;
        stars.forEach(input => { input.checked = input === star; });
        star.handlers.click();
        if (changed) star.handlers.change();
    };
    return {name, id, body, action, title, legend, stars, section, refresh, click};
}

test('optional ratings select, change, and clear without deleting an existing profile review unseen by this form', () => {
    const state = setup();
    state.click('4');
    assert.equal(state.action.value, 'save');
    state.click('5');
    assert.equal(state.stars[4].checked, true);
    state.click('5');
    assert.equal(state.stars.some(star => star.checked), false);
    assert.equal(state.action.value, '');
});

test('clearing a prefilled review requests deletion; rating again requests an update', () => {
    const state = setup('4');
    assert.equal(state.action.value, '');
    state.click('4');
    assert.equal(state.action.value, 'delete');
    state.click('3');
    assert.equal(state.action.value, 'save');
});

test('place changes clear drafts and old IDs immediately; empty places disable and hide review fields', () => {
    const state = setup('4');
    state.name.value = 'Kelp Garden';
    state.name.handlers.input();
    assert.equal(state.id.value, '');
    assert.equal(state.title.textContent, 'How was Kelp Garden?');
    assert.equal(state.legend.textContent, state.title.textContent);
    assert.equal(state.body.value, '');
    assert.equal(state.action.value, '');
    assert.equal(state.stars.some(star => star.checked), false);
    state.click('3');
    assert.match(state.name.validationMessage, /Choose a dive site/);
    state.click('3');
    assert.equal(state.name.validationMessage, '');
    state.name.value = '  ';
    state.name.handlers.input();
    assert.equal(state.section.hidden, true);
    assert.equal(state.section.disabled, true);
    state.name.value = 'Imported site'; state.id.value = '2'; state.refresh();
    assert.equal(state.title.textContent, 'How was Imported site?');
    assert.equal(state.section.disabled, false);
});

test('keyboard arrow changes and Space clearing update the pending review', () => {
    const state = setup('4');
    state.stars[3].checked = false;
    state.stars[4].checked = true;
    state.stars[4].handlers.change();
    assert.equal(state.action.value, 'save');
    let prevented = false;
    state.stars[4].handlers.keydown({key: ' ', preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(state.stars[4].checked, false);
    assert.equal(state.action.value, 'delete');
});
