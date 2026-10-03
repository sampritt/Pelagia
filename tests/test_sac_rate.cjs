const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const context = vm.createContext({ document: { addEventListener() {} }, window: {} });
vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);

test("SAC volume uses the selected tank size and rounds only the final result", () => {
    assert.equal(vm.runInContext("formatSacRate(1)", context), "12.0 L/min");
    assert.equal(vm.runInContext("formatSacRate(1, 15)", context), "15.0 L/min");
    assert.equal(vm.runInContext("formatSacRate(1.25, 12)", context), "15.0 L/min");
    assert.equal(vm.runInContext("formatSacRate(1.25, 15)", context), "18.8 L/min");
    assert.equal(vm.runInContext("formatSacRate(0)", context), "0.0 L/min");
});

test("Missing pressure data never displays a fabricated volume", () => {
    assert.equal(vm.runInContext("formatSacRate(null)", context), "-");
    assert.equal(vm.runInContext("formatSacRate(NaN, 15)", context), "-");
});

test("The display reads the current radio selection without changing the pressure rate", () => {
    let tankSize = "12";
    const output = {};
    const unset = [];
    const calculator = {
        querySelector(selector) {
            if (selector === "[data-tank-size]:checked") return { value: tankSize };
            if (selector === "[data-sac-output]") return output;
            if (selector === ".sac-rate-summary") return { classList: { toggle: (name, value) => unset.push(value) } };
            throw new Error(`Unexpected selector: ${selector}`);
        },
    };
    context.calculator = calculator;
    vm.runInContext("renderSacRate(calculator, 1)", context);
    assert.equal(output.textContent, "12.0 L/min");
    tankSize = "15";
    vm.runInContext("renderSacRate(calculator, 1)", context);
    assert.equal(output.textContent, "15.0 L/min");
    vm.runInContext("renderSacRate(calculator, null)", context);
    assert.equal(output.textContent, "-");
    assert.deepEqual(unset, [false, false, true]);
});
