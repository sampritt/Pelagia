const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(diveValues = ["open water"], currentValues = ["none"], strength = "none") {
    const element = () => ({ handlers: {}, addEventListener(name, handler) { (this.handlers[name] ||= []).push(handler); } });
    function control(values, selected, fallback, exclusive) {
        const root = element();
        const inputs = values.map(value => ({ value, checked: selected.includes(value), dataset: { optionLabel: value === "none" ? "-" : value } }));
        const summary = { textContent: "", focus() { this.focused = true; } };
        Object.assign(root, { inputs, summary, dataset: { default: fallback, exclusive }, open: false,
            querySelectorAll: selector => selector.endsWith(":checked") ? inputs.filter(input => input.checked) : inputs,
            querySelector: () => summary, contains: target => target === root || inputs.includes(target) });
        return root;
    }
    const dive = control(["open water", "reef", "wall"], diveValues, "open water");
    const current = control(["none", "tidal", "drift"], currentValues, "none", "none");
    const range = Object.assign(element(), { value: "0", closest: () => ({classList: {toggle() {}}}) });
    const hidden = { value: strength };
    const output = {};
    const form = {
        querySelectorAll: () => [dive, current],
        querySelector: selector => selector === "[data-current-type-select]" ? current : selector === "[data-current-strength-range]" ? range : hidden,
    };
    const document = Object.assign(element(), { getElementById: () => output });
    const context = vm.createContext({ document, window: {} });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    context.form = form;
    vm.runInContext("initMultiSelects(form); initCurrentStrengthSlider(form);", context);
    const change = (control, value, checked) => {
        const input = control.inputs.find(item => item.value === value);
        input.checked = checked;
        control.handlers.change.forEach(handler => handler({target: input}));
    };
    return {dive, current, range, hidden, output, document, change};
}

test("dive dropdown selects multiple options, removes individual choices and retains a default", () => {
    const {dive, change} = setup();
    change(dive, "reef", true);
    change(dive, "wall", true);
    assert.equal(dive.summary.textContent, "open water, reef, wall");
    change(dive, "open water", false);
    assert.equal(dive.summary.textContent, "reef, wall");
    change(dive, "reef", false);
    change(dive, "wall", false);
    assert.equal(dive.summary.textContent, "open water");
});

test("multiple currents enable strength; removing the last current resets strength and None", () => {
    const {current, range, hidden, change} = setup();
    assert.equal(range.disabled, true);
    change(current, "tidal", true);
    change(current, "drift", true);
    assert.equal(current.summary.textContent, "tidal, drift");
    assert.equal(current.inputs[0].checked, false);
    assert.equal(range.disabled, false);
    range.value = "3";
    range.handlers.input[0]();
    assert.equal(hidden.value, "strong");
    change(current, "tidal", false);
    assert.equal(hidden.value, "strong");
    assert.equal(range.disabled, false);
    change(current, "drift", false);
    assert.equal(current.summary.textContent, "-");
    assert.equal(range.disabled, true);
    assert.equal(hidden.value, "none");
});

test("reopening restores all choices; selecting None clears currents and Escape/outside clicks close menus", () => {
    const {dive, current, range, hidden, change, document} = setup(["reef", "wall"], ["tidal", "drift"], "strong");
    assert.equal(dive.summary.textContent, "reef, wall");
    assert.equal(current.summary.textContent, "tidal, drift");
    assert.equal(range.disabled, false);
    assert.equal(hidden.value, "strong");
    change(current, "none", true);
    assert.deepEqual(current.inputs.filter(input => input.checked).map(input => input.value), ["none"]);
    assert.equal(hidden.value, "none");
    dive.open = current.open = true;
    dive.handlers.keydown[0]({key: "Escape"});
    assert.equal(dive.open, false);
    assert.equal(dive.summary.focused, true);
    document.handlers.click[0]({target: {}});
    assert.equal(current.open, false);
});
