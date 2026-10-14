const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(initial = {}) {
    const element = (value = "") => ({
        value, textContent: "", handlers: {}, dataset: {},
        addEventListener(name, handler) { this.handlers[name] = handler; },
        setAttribute(name, value) { this[name] = value; },
    });
    const names = ["depth", "averageDepth", "duration", "weight", "startingPressure", "endingPressure", "visibility", "airTemp", "waterTemp"];
    const pairs = Object.fromEntries(names.map(name => [name, {
        number: element(initial[name] ?? ({ depth: "12", duration: "80" }[name] || "")),
        range: element("0"), output: element(),
    }]));
    const fields = {depth: "depth_m", averageDepth: "average_depth_m", weight: "weight_kg", duration: "duration_min",
        startingPressure: "starting_pressure_bar", endingPressure: "ending_pressure_bar", visibility: "visibility_m",
        airTemp: "air_temp_c", waterTemp: "water_temp_c"};
    for (const name of names) pairs[name].number.name = fields[name];
    const unitInputs = Object.entries({length: ["m", "ft"], weight: ["kg", "lb"], pressure: ["bar", "psi"], temperature: ["c", "f"]})
        .flatMap(([group, units]) => units.map((unit, index) => Object.assign(element(unit), {checked: index === 0, dataset: {unitToggle: group}})));
    const labels = Object.fromEntries(names.map(name => [name, element()]));
    const calculator = { querySelector: selector => selector === "[data-tank-size]:checked" ? { value: "12" } : selector === "[data-sac-output]" ? sacOutput : null };
    const sacOutput = element();
    const form = {
        handlers: {}, addEventListener(name, handler) { this.handlers[name] = handler; },
        dataset: { isEdit: "true" },
        querySelector(selector) {
            const metric = selector.match(/\[data-(range|number)='(.+)'\]/);
            if (metric) return pairs[metric[2]][metric[1]];
            if (selector === "[data-sac-calculator]") return calculator;
            if (selector === ".pressure-slider") return null;
            const label = selector.match(/\[data-unit-label='(.+)'\]/);
            if (label) return labels[label[1]];
            return element();
        },
        querySelectorAll(selector) { return selector === "[data-unit-toggle]" ? unitInputs : []; },
    };
    const document = {
        querySelector: () => form,
        getElementById: id => id.endsWith("Output") ? pairs[id.slice(0, -6)].output : element(),
        addEventListener() {},
    };
    const context = vm.createContext({ document, window: {}, setTimeout, clearTimeout });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext(`
        initSpeciesPicker = initBuddyAutocomplete = initPhotoPreview = initPhotoRemoval = initArrowNavigation = initCurrentStrengthSlider = () => {};
        initDiveForm();
    `, context);
    const setUnit = (group, unit) => {
        for (const input of unitInputs.filter(input => input.dataset.unitToggle === group)) input.checked = input.value === unit;
        unitInputs.find(input => input.dataset.unitToggle === group && input.value === unit).handlers.change();
    };
    const submitted = () => {
        const values = new Map();
        form.handlers.formdata({formData: {set: (name, value) => values.set(name, value)}});
        return Object.fromEntries(values);
    };
    return { pairs, sacOutput, setUnit, submitted, labels };
}

test("typed depths retain decimal precision through blur and reopening; sliders use whole meters", () => {
    const { pairs } = setup({ depth: "15.0" });
    assert.equal(pairs.depth.number.value, "15");
    assert.equal(pairs.depth.output.textContent, "15 m");
    for (const value of ["15.3", "15.3456789"]) {
        pairs.depth.number.value = value;
        pairs.depth.number.handlers.input();
        pairs.depth.number.handlers.blur();
        assert.equal(pairs.depth.number.value, value);
        assert.equal(pairs.depth.output.textContent, `${value} m`);
        assert.equal(pairs.depth.range.value, 15);
        assert.equal(setup({ depth: value }).pairs.depth.number.value, value);
    }
    pairs.depth.range.value = "16";
    pairs.depth.range.handlers.input();
    assert.equal(pairs.depth.number.value, "16");
    assert.equal(pairs.depth.output.textContent, "16 m");
});

test("pressure inputs retain off-step integers and SAC uses the exact entered depth and pressure", () => {
    const { pairs, sacOutput } = setup({ depth: "15.3", duration: "40", startingPressure: "195", endingPressure: "47" });
    for (const [name, value, snapped] of [["startingPressure", "195", 200], ["endingPressure", "47", 50]]) {
        pairs[name].number.handlers.input();
        pairs[name].number.handlers.blur();
        assert.equal(pairs[name].number.value, value);
        assert.equal(pairs[name].output.textContent, `${value} bar`);
        assert.equal(pairs[name].range.value, snapped);
    }
    assert.equal(sacOutput.textContent, `${((195 - 47) / 40 / (15.3 / 10 + 1) * 12).toFixed(1)} L/min`);
    pairs.startingPressure.range.value = "190";
    pairs.startingPressure.range.handlers.input();
    assert.equal(pairs.startingPressure.number.value, "190");
});

test("duration and weight sliders advance by one while typed fractional weight stays exact", () => {
    const { pairs } = setup({ weight: "8.5" });
    assert.equal(pairs.weight.number.value, "8.5");
    pairs.duration.range.value = "81";
    pairs.duration.range.handlers.input();
    assert.equal(pairs.duration.number.value, "81");
    pairs.weight.range.value = "9";
    pairs.weight.range.handlers.input();
    assert.equal(pairs.weight.number.value, "9");
});

test("optional average depth drives SAC, including zero, and clearing restores max depth", () => {
    const { pairs, sacOutput } = setup({ depth: "20", duration: "50", startingPressure: "200", endingPressure: "50" });
    assert.equal(pairs.averageDepth.number.value, "");
    assert.equal(pairs.averageDepth.output.textContent, "-");
    assert.equal(sacOutput.textContent, "12.0 L/min");
    pairs.averageDepth.number.value = "10.3";
    pairs.averageDepth.number.handlers.input();
    pairs.averageDepth.number.handlers.blur();
    assert.equal(pairs.averageDepth.number.value, "10.3");
    assert.equal(pairs.averageDepth.range.value, 10);
    assert.equal(pairs.averageDepth.output.textContent, "10.3 m");
    assert.equal(sacOutput.textContent, `${(150 / 50 / 2.03 * 12).toFixed(1)} L/min`);
    // Max-depth changes must not override an explicitly entered average depth.
    pairs.depth.range.value = "30";
    pairs.depth.range.handlers.input();
    assert.equal(sacOutput.textContent, `${(150 / 50 / 2.03 * 12).toFixed(1)} L/min`);
    pairs.averageDepth.range.value = "0";
    pairs.averageDepth.range.handlers.input();
    assert.equal(pairs.averageDepth.number.value, "0");
    assert.equal(sacOutput.textContent, "36.0 L/min");
    pairs.averageDepth.number.value = "";
    pairs.averageDepth.number.handlers.input();
    pairs.averageDepth.number.handlers.blur();
    assert.equal(pairs.averageDepth.output.textContent, "-");
    assert.equal(sacOutput.textContent, "9.0 L/min");
    const reopened = setup({ depth: "30", averageDepth: "15.0", duration: "50", startingPressure: "200", endingPressure: "50" });
    assert.equal(reopened.pairs.averageDepth.number.value, "15");
    assert.equal(reopened.pairs.averageDepth.output.textContent, "15 m");
    assert.equal(reopened.sacOutput.textContent, "14.4 L/min");
});

test("unit toggles update values, bounds, labels and slider steps without changing SAC", () => {
    const state = setup({depth: "20", averageDepth: "10.3", duration: "50", weight: "8", startingPressure: "195",
        endingPressure: "47", visibility: "15", airTemp: "25", waterTemp: "20"});
    const sac = state.sacOutput.textContent;
    state.setUnit("length", "ft");
    state.setUnit("weight", "lb");
    state.setUnit("pressure", "psi");
    state.setUnit("temperature", "f");
    assert.equal(state.pairs.depth.number.value, "65.62");
    assert.equal(state.pairs.averageDepth.number.value, "33.79");
    assert.equal(state.pairs.visibility.number.value, "49.21");
    assert.equal(state.labels.depth.textContent, "Max depth (ft)");
    assert.equal(state.pairs.depth.number.max, "147.64");
    assert.equal(state.pairs.weight.number.max, "22.05");
    assert.equal(state.pairs.weight.number.value, "17.64");
    assert.equal(state.pairs.startingPressure.number.value, "2828");
    assert.equal(state.pairs.startingPressure.range.step, "100");
    assert.equal(state.pairs.startingPressure.number.max, "2901");
    assert.equal(state.pairs.airTemp.number.value, "77");
    assert.equal(state.pairs.waterTemp.number.value, "68");
    assert.equal(state.pairs.waterTemp.number.min, "-4");
    assert.equal(state.pairs.waterTemp.number.max, "104");
    assert.equal(state.sacOutput.textContent, sac);
    // Blur following a toggle must not replace the exact original with a
    // conversion of the rounded value visible in the numeric box.
    state.pairs.depth.number.handlers.blur();
    state.pairs.startingPressure.number.handlers.blur();
    for (let i = 0; i < 5; i++) {
        for (const [group, metric, alternate] of [["length", "m", "ft"], ["weight", "kg", "lb"], ["pressure", "bar", "psi"], ["temperature", "c", "f"]]) {
            state.setUnit(group, metric);
            state.setUnit(group, alternate);
        }
    }
    const values = state.submitted();
    assert.ok(Math.abs(Number(values.depth_m) * 0.3048 - 20) < 1e-12);
    assert.ok(Math.abs(Number(values.weight_kg) * 0.45359237 - 8) < 1e-12);
    state.setUnit("length", "m");
    state.setUnit("pressure", "bar");
    assert.equal(state.pairs.depth.number.value, "20");
    assert.equal(state.pairs.averageDepth.number.value, "10.3");
    assert.equal(state.pairs.startingPressure.number.value, "195");
    assert.equal(state.pairs.depth.range.max, "45");
    assert.equal(state.pairs.startingPressure.range.step, "10");
});

test("imperial edits and sliders use the selected units and serialize full precision", () => {
    const state = setup({depth: "20", duration: "50", startingPressure: "200", endingPressure: "50"});
    for (const [group, unit] of [["length", "ft"], ["weight", "lb"], ["pressure", "psi"], ["temperature", "f"]]) state.setUnit(group, unit);
    const edits = {depth: "100", averageDepth: "35", weight: "16", startingPressure: "2850", endingPressure: "600", airTemp: "75", waterTemp: "65", visibility: "50"};
    for (const [name, value] of Object.entries(edits)) {
        state.pairs[name].number.value = value;
        state.pairs[name].number.handlers.input();
        state.pairs[name].number.handlers.blur();
        assert.equal(state.pairs[name].number.value, value);
    }
    const psiToBar = 0.45359237 * 9.80665 / 0.0254 ** 2 / 100000;
    assert.equal(state.sacOutput.textContent, `${((2850 - 600) * psiToBar / 50 / (35 * 0.3048 / 10 + 1) * 12).toFixed(1)} L/min`);
    const saved = state.submitted();
    assert.ok(Math.abs(Number(saved.depth_m) - 100) < 1e-10);
    assert.ok(Math.abs(Number(saved.air_temp_c) - 75) < 1e-10);
    state.pairs.startingPressure.range.value = "2800";
    state.pairs.startingPressure.range.handlers.input();
    assert.equal(state.pairs.startingPressure.number.value, "2800");
    state.setUnit("length", "m");
    assert.equal(state.pairs.depth.number.value, "30.48");
    assert.equal(state.pairs.averageDepth.number.value, "10.668");
});

test("changing units preserves blanks and editing decimal text remains possible", () => {
    const state = setup();
    for (const [group, unit] of [["length", "ft"], ["weight", "lb"], ["pressure", "psi"], ["temperature", "f"]]) state.setUnit(group, unit);
    for (const name of ["averageDepth", "weight", "visibility", "startingPressure", "endingPressure", "airTemp", "waterTemp"]) {
        assert.equal(state.pairs[name].number.value, "");
        assert.equal(state.pairs[name].output.textContent, "-");
    }
    state.pairs.depth.number.value = "15.";
    state.pairs.depth.number.handlers.input();
    assert.equal(state.pairs.depth.number.value, "15.");
    state.pairs.depth.number.value = "15.3";
    state.pairs.depth.number.handlers.input();
    state.pairs.depth.number.handlers.blur();
    assert.equal(state.pairs.depth.number.value, "15.3");
    assert.equal(state.sacOutput.textContent, "-");
});
