const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(initial = {}, stored = {}, preferred = {}) {
    const element = (value = "") => ({
        value, textContent: "", handlers: {}, dataset: {},
        classList: {toggle() {}},
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
    for (const name of names) {
        pairs[name].number.name = fields[name];
        if (name in stored) pairs[name].number.dataset.metricValue = stored[name];
    }
    const unitInputs = Object.entries({length: ["m", "ft"], weight: ["kg", "lb"], pressure: ["bar", "psi"], temperature: ["c", "f"]})
        .flatMap(([group, units]) => units.map((unit) => Object.assign(element(unit), {checked: unit === (preferred[group] || units[0]), dataset: {unitToggle: group}})));
    const labels = Object.fromEntries(names.map(name => [name, element()]));
    const calculator = { querySelector: selector => selector === "[data-tank-size]:checked" ? { value: "12" } : selector === "[data-sac-output]" ? sacOutput : null };
    const sacOutput = element();
    const trackStyles = {};
    const pressureTrack = {style: {setProperty(name, value) {trackStyles[name] = value;}}, classList: {toggle() {}}};
    const namedFields = Object.fromEntries(["date", "site_name", "dive_site_id", "country_or_area", "latitude", "longitude"].map(name => [name, element()]));
    const computerData = element(), importStatus = element(), averageDetails = element();
    const gasFields = Object.fromEntries(["oxygen", "helium", "nitrogen"].map(gas => [gas, {range: element(), number: element()}]));
    const gasLabel = element();
    const gasControls = {querySelector(selector) {
        if (selector === "[data-gas-mix-label]") return gasLabel;
        const match = selector.match(/data-gas-(range|number)='(.+)'/);
        return gasFields[match[2]][match[1]];
    }};
    const form = {
        elements: {namedItem: name => namedFields[name]},
        handlers: {}, addEventListener(name, handler) { this.handlers[name] = handler; },
        dataset: { isEdit: "true" },
        querySelector(selector) {
            const metric = selector.match(/\[data-(range|number)='(.+)'\]/);
            if (metric) return pairs[metric[2]][metric[1]];
            if (selector === "[data-sac-calculator]") return calculator;
            if (selector === ".pressure-slider") return pressureTrack;
            if (selector === "[data-computer-data]") return computerData;
            if (selector === "[data-computer-import-status]") return importStatus;
            if (selector === "[data-average-depth]") return averageDetails;
            if (selector === "[data-gas-mix]") return gasControls;
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
    const context = vm.createContext({ document, window: {setTimeout, clearTimeout}, setTimeout, clearTimeout, loadSpeciesSuggestions() {} });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    vm.runInContext(`
        initSpeciesPicker = initBuddyAutocomplete = initPhotoPreview = initPhotoRemoval = initArrowNavigation = initCurrentStrengthSlider = () => {};
        initDiveComputerImport = (_form, applyImport) => { globalThis.applyImported = applyImport; };
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
    return { pairs, sacOutput, setUnit, submitted, labels, trackStyles, namedFields, computerData, importStatus, gasFields, gasLabel,
        applyImported: context.applyImported, averageDetails };
}

test("typed depths round on blur and reopening; sliders use whole meters", () => {
    const { pairs } = setup({ depth: "15.0" });
    assert.equal(pairs.depth.number.value, "15");
    assert.equal(pairs.depth.output.textContent, "15 m");
    for (const value of ["15.3", "15.3456789"]) {
        pairs.depth.number.value = value;
        pairs.depth.number.handlers.input();
        pairs.depth.number.handlers.blur();
        assert.equal(pairs.depth.number.value, "15");
        assert.equal(pairs.depth.output.textContent, "15 m");
        assert.equal(pairs.depth.range.value, 15);
        assert.equal(setup({ depth: value }).pairs.depth.number.value, "15");
    }
    pairs.depth.range.value = "16";
    pairs.depth.range.handlers.input();
    assert.equal(pairs.depth.number.value, "16");
    assert.equal(pairs.depth.output.textContent, "16 m");
});

test("preferred units initialize the form while retaining exact measurements and allowing overrides", () => {
    const state = setup({depth: "31", averageDepth: "11", weight: "7.5", visibility: "15", airTemp: "24", startingPressure: "195", endingPressure: "47", duration: "50"},
        {depth: "31.1234", averageDepth: "10.668", weight: "7.25747792", visibility: "15.3", airTemp: "23.7", startingPressure: "195.3"},
        {length: "ft", weight: "lb", pressure: "psi", temperature: "f"});
    assert.equal(state.pairs.depth.output.textContent, "102 ft");
    assert.equal(state.pairs.averageDepth.output.textContent, "35 ft");
    assert.equal(state.pairs.weight.output.textContent, "16 lb");
    assert.equal(state.pairs.visibility.output.textContent, "50 ft");
    assert.equal(state.pairs.airTemp.output.textContent, "75°F");
    assert.equal(state.pairs.waterTemp.output.textContent, "-");
    assert.equal(state.pairs.startingPressure.output.textContent, "2833 psi");
    assert.equal(state.pairs.depth.range.max, "148");
    assert.equal(state.pairs.startingPressure.range.max, "3000");
    const sac = state.sacOutput.textContent;
    assert.ok(Math.abs(Number(state.submitted().depth_m) * 0.3048 - 31.1234) < 1e-10);
    assert.ok(Math.abs(Number(state.submitted().weight_kg) - 16) < 1e-10);
    for (const name of ["depth", "averageDepth", "weight", "visibility", "airTemp", "startingPressure"]) {
        state.pairs[name].number.handlers.blur();
    }
    state.setUnit("length", "m");
    state.setUnit("weight", "kg");
    state.setUnit("pressure", "bar");
    state.setUnit("temperature", "c");
    assert.equal(state.submitted().depth_m, "31.1234");
    assert.equal(state.submitted().average_depth_m, "10.668");
    assert.equal(state.submitted().weight_kg, "7.25747792");
    assert.equal(state.submitted().starting_pressure_bar, "195.3");
    assert.equal(state.sacOutput.textContent, sac);
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
    assert.equal(sacOutput.textContent, `${Math.round((195 - 47) / 40 / (15.3 / 10 + 1) * 12)} L/min`);
    pairs.startingPressure.range.value = "190";
    pairs.startingPressure.range.handlers.input();
    assert.equal(pairs.startingPressure.number.value, "190");
});

test("weight sliders support half units and duration sliders use integers", () => {
    const { pairs } = setup({ weight: "8.5" });
    assert.equal(pairs.weight.number.value, "8.5");
    pairs.duration.range.value = "81";
    pairs.duration.range.handlers.input();
    assert.equal(pairs.duration.number.value, "81");
    pairs.weight.range.value = "9.5";
    pairs.weight.range.handlers.input();
    assert.equal(pairs.weight.number.value, "9.5");
});

test("optional average depth drives SAC, including zero, and clearing restores max depth", () => {
    const { pairs, sacOutput } = setup({ depth: "20", duration: "50", startingPressure: "200", endingPressure: "50" });
    assert.equal(pairs.averageDepth.number.value, "");
    assert.equal(pairs.averageDepth.output.textContent, "-");
    assert.equal(sacOutput.textContent, "12 L/min");
    pairs.averageDepth.number.value = "10.3";
    pairs.averageDepth.number.handlers.input();
    pairs.averageDepth.number.handlers.blur();
    assert.equal(pairs.averageDepth.number.value, "10");
    assert.equal(pairs.averageDepth.range.value, 10);
    assert.equal(pairs.averageDepth.output.textContent, "10 m");
    assert.equal(sacOutput.textContent, `${Math.round(150 / 50 / 2.03 * 12)} L/min`);
    // Max-depth changes must not override an explicitly entered average depth.
    pairs.depth.range.value = "30";
    pairs.depth.range.handlers.input();
    assert.equal(sacOutput.textContent, `${Math.round(150 / 50 / 2.03 * 12)} L/min`);
    pairs.averageDepth.range.value = "0";
    pairs.averageDepth.range.handlers.input();
    assert.equal(pairs.averageDepth.number.value, "0");
    assert.equal(sacOutput.textContent, "36 L/min");
    pairs.averageDepth.number.value = "";
    pairs.averageDepth.number.handlers.input();
    pairs.averageDepth.number.handlers.blur();
    assert.equal(pairs.averageDepth.output.textContent, "-");
    assert.equal(sacOutput.textContent, "9 L/min");
    const reopened = setup({ depth: "30", averageDepth: "15.0", duration: "50", startingPressure: "200", endingPressure: "50" });
    assert.equal(reopened.pairs.averageDepth.number.value, "15");
    assert.equal(reopened.pairs.averageDepth.output.textContent, "15 m");
    assert.equal(reopened.sacOutput.textContent, "14 L/min");
});

test("unit toggles update values, bounds, labels and slider steps without changing SAC", () => {
    const state = setup({depth: "20", averageDepth: "10.3", duration: "50", weight: "8", startingPressure: "195",
        endingPressure: "47", visibility: "15", airTemp: "25", waterTemp: "20"});
    const sac = state.sacOutput.textContent;
    state.setUnit("length", "ft");
    state.setUnit("weight", "lb");
    state.setUnit("pressure", "psi");
    state.setUnit("temperature", "f");
    assert.equal(state.pairs.depth.number.value, "66");
    assert.equal(state.pairs.averageDepth.number.value, "34");
    assert.equal(state.pairs.visibility.number.value, "50");
    assert.equal(state.labels.depth.textContent, "Max depth (ft)");
    assert.equal(state.pairs.depth.number.max, "");
    assert.equal(state.pairs.depth.range.max, "148");
    assert.equal(state.pairs.weight.number.max, "22");
    assert.equal(state.pairs.weight.number.value, "17.5");
    assert.equal(state.pairs.startingPressure.number.value, "2828");
    assert.equal(state.pairs.startingPressure.range.step, "100");
    assert.equal(state.pairs.startingPressure.range.max, "3000");
    assert.equal(state.pairs.startingPressure.number.max, "4351");
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
    assert.equal(state.pairs.averageDepth.number.value, "10");
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
    assert.equal(state.sacOutput.textContent, `${Math.round((2850 - 600) * psiToBar / 50 / (35 * 0.3048 / 10 + 1) * 12)} L/min`);
    const saved = state.submitted();
    assert.ok(Math.abs(Number(saved.depth_m) - 100) < 1e-10);
    assert.ok(Math.abs(Number(saved.air_temp_c) - 75) < 1e-10);
    state.pairs.startingPressure.range.value = "2800";
    state.pairs.startingPressure.range.handlers.input();
    assert.equal(state.pairs.startingPressure.number.value, "2800");
    state.setUnit("length", "m");
    assert.equal(state.pairs.depth.number.value, "30");
    assert.equal(state.pairs.averageDepth.number.value, "11");
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
    assert.equal(state.pairs.depth.number.value, "15");
    assert.equal(state.sacOutput.textContent, "-");
});

test("converted displays use whole or half units without rounding saved measurements", () => {
    const state = setup({depth: "12", averageDepth: "15.3", weight: "8.3", visibility: "15.3",
        startingPressure: "195.3", endingPressure: "47", airTemp: "25.3", waterTemp: "-17.7"});
    const sac = state.sacOutput.textContent;
    for (const [group, unit] of [["length", "ft"], ["weight", "lb"], ["pressure", "psi"], ["temperature", "f"]]) state.setUnit(group, unit);
    const alternate = {depth: "39", averageDepth: "50", weight: "18.5", visibility: "50",
        startingPressure: "2833", airTemp: "78", waterTemp: "0"};
    for (const [name, value] of Object.entries(alternate)) {
        assert.equal(state.pairs[name].number.value, value);
        assert.equal(state.pairs[name].output.textContent, `${value}${["airTemp", "waterTemp"].includes(name) ? "°F" : name === "weight" ? " lb" : name === "startingPressure" ? " psi" : " ft"}`);
        state.pairs[name].number.handlers.blur();
    }
    assert.equal(state.sacOutput.textContent, sac);
    for (const [group, unit] of [["length", "m"], ["weight", "kg"], ["pressure", "bar"], ["temperature", "c"]]) state.setUnit(group, unit);
    const metric = {depth: "12", averageDepth: "15", weight: "8.5", visibility: "15", startingPressure: "195", airTemp: "25", waterTemp: "-18"};
    for (const [name, value] of Object.entries(metric)) {
        assert.equal(state.pairs[name].number.value, value);
        state.pairs[name].number.handlers.blur();
    }
    const submitted = state.submitted();
    assert.equal(submitted.depth_m, "12");
    assert.equal(submitted.average_depth_m, "15.3");
    assert.equal(submitted.weight_kg, "8.3");
    assert.equal(submitted.starting_pressure_bar, "195.3");
    assert.equal(submitted.air_temp_c, "25.3");
    assert.equal(submitted.water_temp_c, "-17.7");
    // Re-entering a rounded value is an edit, rather than another unit switch.
    state.pairs.averageDepth.number.value = "15";
    state.pairs.averageDepth.number.handlers.input();
    state.pairs.averageDepth.number.handlers.blur();
    assert.equal(state.submitted().average_depth_m, "15");
});

test("pressure sliders use 200 bar or 3000 psi while typed values can reach 300 bar equivalent", () => {
    const state = setup({depth: "20", duration: "50", startingPressure: "250", endingPressure: "50"});
    for (const name of ["startingPressure", "endingPressure"]) {
        assert.equal(state.pairs[name].range.max, "200");
        assert.equal(state.pairs[name].number.max, "300");
    }
    assert.equal(state.pairs.startingPressure.range.value, 200);
    assert.equal(state.pairs.startingPressure.number.value, "250");
    assert.equal(state.sacOutput.textContent, "16 L/min");
    assert.equal(state.trackStyles["--pressure-low"], "0%");
    assert.equal(state.trackStyles["--pressure-high"], "75%");
    state.setUnit("pressure", "psi");
    for (const name of ["startingPressure", "endingPressure"]) {
        assert.equal(state.pairs[name].range.max, "3000");
        assert.equal(state.pairs[name].number.max, "4351");
    }
    assert.equal(state.pairs.startingPressure.number.value, "3626");
    assert.equal(state.pairs.startingPressure.range.value, 3000);
    assert.equal(state.trackStyles["--pressure-low"], "0%");
    assert.equal(state.sacOutput.textContent, "16 L/min");
    for (const name of ["startingPressure", "endingPressure"]) {
        state.pairs[name].number.value = "4000";
        state.pairs[name].number.handlers.input();
        state.pairs[name].number.handlers.blur();
        assert.equal(state.pairs[name].number.value, "4000");
        assert.equal(state.pairs[name].range.value, 3000);
    }
    assert.ok(Math.abs(Number(state.submitted().starting_pressure_bar) - 4000) < 1e-8);
    assert.equal(state.sacOutput.textContent, "0 L/min");
    state.setUnit("pressure", "bar");
    state.pairs.startingPressure.number.value = "300";
    state.pairs.startingPressure.number.handlers.input();
    state.pairs.startingPressure.number.handlers.blur();
    assert.equal(state.pairs.startingPressure.number.value, "300");
    assert.equal(state.pairs.startingPressure.range.value, 200);
    assert.equal(state.submitted().starting_pressure_bar, "300");
    state.pairs.startingPressure.number.value = "350";
    state.pairs.startingPressure.number.handlers.input();
    state.pairs.startingPressure.number.handlers.blur();
    assert.equal(state.pairs.startingPressure.number.value, "300");
    // Moving the slider replaces the typed pressure with its chosen value.
    state.pairs.startingPressure.range.value = "190";
    state.pairs.startingPressure.range.handlers.input();
    assert.equal(state.pairs.startingPressure.number.value, "190");
    state.setUnit("pressure", "psi");
    state.pairs.startingPressure.range.value = "3000";
    state.pairs.startingPressure.range.handlers.input();
    assert.equal(state.pairs.startingPressure.number.value, "3000");
    assert.ok(Math.abs(Number(state.submitted().starting_pressure_bar) - 3000) < 1e-8);
});


test("rounded edit inputs restore exact stored measurements and preserve them on blur", () => {
    const initial = {depth: "31", averageDepth: "11", weight: "7.5", visibility: "15", airTemp: "24", waterTemp: "-2", startingPressure: "195"};
    const stored = {depth: "31.1234", averageDepth: "10.668", weight: "7.25747792", visibility: "15.3", airTemp: "23.7", waterTemp: "-2.4", startingPressure: "195.3"};
    const state = setup(initial, stored);
    for (const name of Object.keys(stored)) {
        assert.equal(state.pairs[name].number.value, initial[name]);
        state.pairs[name].number.handlers.blur();
    }
    const saved = state.submitted();
    for (const [name, field] of Object.entries({depth: "depth_m", averageDepth: "average_depth_m", weight: "weight_kg", visibility: "visibility_m", airTemp: "air_temp_c", waterTemp: "water_temp_c", startingPressure: "starting_pressure_bar"})) {
        assert.equal(saved[field], stored[name]);
    }
});


test("visibility slider caps at 30 m or 100 ft while numeric entries can exceed it", () => {
    const state = setup({visibility: "60"});
    assert.equal(state.pairs.visibility.range.max, "30");
    assert.equal(state.pairs.visibility.number.max, "");
    assert.equal(state.pairs.visibility.range.value, 30);
    assert.equal(state.pairs.visibility.number.value, "60");
    state.setUnit("length", "ft");
    assert.equal(state.pairs.visibility.range.max, "100");
    assert.equal(state.pairs.visibility.range.step, "5");
    assert.equal(state.pairs.visibility.range.value, 100);
    assert.equal(state.pairs.visibility.number.value, "195");
    state.pairs.visibility.number.value = "150";
    state.pairs.visibility.number.handlers.input();
    state.pairs.visibility.number.handlers.blur();
    assert.equal(state.pairs.visibility.number.value, "150");
    assert.equal(state.pairs.visibility.range.value, 100);
    assert.ok(Math.abs(Number(state.submitted().visibility_m) - 150) < 1e-8);
    state.setUnit("length", "m");
    assert.equal(state.pairs.visibility.number.value, "46");
    assert.equal(state.pairs.visibility.range.max, "30");
    state.setUnit("length", "ft");
    state.pairs.visibility.range.value = "100";
    state.pairs.visibility.range.handlers.input();
    assert.equal(state.pairs.visibility.number.value, "100");
    assert.ok(Math.abs(Number(state.submitted().visibility_m) - 100) < 1e-8);
});

test("pressure unit switches use the standard 200 bar and 3000 psi pairing", () => {
    const state = setup({startingPressure: "200"});
    state.setUnit("pressure", "psi");
    assert.equal(state.pairs.startingPressure.number.value, "3000");
    state.setUnit("pressure", "bar");
    assert.equal(state.pairs.startingPressure.number.value, "200");
    assert.equal(state.submitted().starting_pressure_bar, "200");
    state.setUnit("pressure", "psi");
    state.pairs.startingPressure.number.value = "3000";
    state.pairs.startingPressure.number.handlers.input();
    state.pairs.startingPressure.number.handlers.blur();
    state.setUnit("pressure", "bar");
    assert.equal(state.pairs.startingPressure.number.value, "200");
    state.pairs.startingPressure.number.handlers.blur();
    assert.ok(Math.abs(Number(state.submitted().starting_pressure_bar) - 206.8427187951) < 1e-7);
});


test("gas sliders update nitrogen, preserve the other editable gas, and clamp the total", () => {
    const field = value => ({value: String(value), handlers: {}, addEventListener(name, handler) {this.handlers[name] = handler;}});
    const gases = Object.fromEntries([["oxygen", 21], ["helium", 0], ["nitrogen", 79]].map(([gas, value]) => [gas, {range: field(value), number: field(value)}]));
    const summary = {textContent: ""};
    const controls = {querySelector(selector) {
        if (selector === "[data-gas-mix-label]") return summary;
        const [, kind, gas] = selector.match(/data-gas-(range|number)='(\w+)'/);
        return gases[gas][kind];
    }};
    const context = vm.createContext({document: {addEventListener() {}}, window: {}});
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    context.form = {querySelector: () => controls};
    vm.runInContext("initGasMix(form)", context);
    const set = (gas, kind, value) => {gases[gas][kind].value = String(value); gases[gas][kind].handlers.input();};
    assert.equal(summary.textContent, "Air");
    set("oxygen", "range", 20);
    assert.equal(gases.helium.number.value, "1");
    assert.equal(gases.nitrogen.number.value, "79");
    assert.equal(summary.textContent, "Trimix 20/1");
    set("oxygen", "number", 18);
    assert.equal(gases.helium.number.value, "3");
    assert.equal(gases.nitrogen.number.value, "79");
    set("oxygen", "range", 20);
    assert.equal(gases.helium.number.value, "1");
    set("helium", "number", 0);
    assert.equal(gases.helium.number.value, "1");
    set("oxygen", "range", 21);
    set("helium", "number", 0);
    assert.equal(summary.textContent, "Air");
    set("oxygen", "range", 32);
    assert.equal(summary.textContent, "EANx 32%");
    assert.equal(gases.nitrogen.number.value, "68");
    set("helium", "number", 35);
    assert.equal(summary.textContent, "Trimix 32/35");
    assert.equal(gases.oxygen.number.value, "32");
    assert.equal(gases.nitrogen.range.value, "33");
    set("oxygen", "number", 99);
    assert.equal(gases.oxygen.number.value, "65");
    assert.equal(gases.helium.number.value, "35");
    assert.equal(gases.nitrogen.number.value, "0");
    set("helium", "range", 100);
    assert.equal(gases.helium.number.value, "35");
    set("oxygen", "number", -5);
    assert.equal(gases.oxygen.number.value, "0");
    assert.equal(gases.helium.number.value, "100");
    assert.equal(gases.nitrogen.number.value, "0");
    set("helium", "number", 22.6);
    assert.equal(gases.helium.number.value, "23");
    assert.equal(gases.nitrogen.number.value, "77");
    assert.deepEqual(Object.keys(gases.nitrogen.number.handlers), []);
    assert.deepEqual(Object.keys(gases.nitrogen.range.handlers), []);
});

test("import fills canonical measurements, keeps unrelated values, and survives unit switches", () => {
    const state = setup({airTemp: "31", weight: "7.5", startingPressure: "200", endingPressure: "50"}, {}, {length: "ft", temperature: "f"});
    const data = {version: 1, depth_profile: [{elapsed_seconds: 0, depth_m: 1.602}]};
    state.applyImported({fields: {depth_m: 21.038, average_depth_m: 13.049, duration_min: 53, water_temp_c: 28,
        date: "2026-10-09", dive_site_id: 2544, site_name: "Daphne", country_or_area: "Ecuador",
        latitude: -0.39685134775936604, longitude: -90.35167305730283, oxygen_pct: 33, helium_pct: 0, nitrogen_pct: 67},
        computer_data: data, matched_site: {name: "Daphne"}, notices: ["No separate air temperature was recorded."]});
    assert.equal(state.namedFields.site_name.value, "Daphne");
    assert.equal(state.namedFields.dive_site_id.value, 2544);
    assert.equal(state.namedFields.latitude.value, -0.39685134775936604);
    assert.equal(state.gasFields.oxygen.number.value, 33);
    assert.equal(state.gasLabel.textContent, "EANx 33%");
    assert.equal(state.pairs.duration.number.value, "53");
    assert.equal(state.pairs.depth.number.value, "69");
    assert.equal(state.pairs.waterTemp.number.value, "82");
    assert.equal(state.averageDetails.open, true);
    assert.deepEqual(JSON.parse(state.computerData.value), data);
    assert.match(state.importStatus.textContent, /Matched Daphne/);
    assert.match(state.importStatus.textContent, /1 depth measurements ready to save/);
    state.setUnit("length", "m");
    state.setUnit("temperature", "c");
    const values = state.submitted();
    assert.equal(values.depth_m, "21.038");
    assert.equal(values.average_depth_m, "13.049");
    assert.equal(values.air_temp_c, "31");
    assert.equal(values.water_temp_c, "28");
    assert.equal(values.weight_kg, "7.5");
    assert.equal(values.starting_pressure_bar, "200");
});

test("numeric depth and duration exceed convenient slider ranges without loss", () => {
    const state = setup({depth: "83.123", averageDepth: "50.125", duration: "183"});
    assert.equal(state.pairs.depth.number.max, "");
    assert.equal(state.pairs.duration.number.max, "");
    assert.equal(state.pairs.depth.range.max, "45");
    assert.equal(state.pairs.duration.range.max, "120");
    assert.equal(state.pairs.duration.number.value, "183");
    state.setUnit("length", "ft");
    state.setUnit("length", "m");
    assert.equal(state.submitted().depth_m, "83.123");
    assert.equal(state.submitted().average_depth_m, "50.125");
    state.pairs.depth.number.value = "102.45";
    state.pairs.depth.number.handlers.input();
    state.pairs.depth.number.handlers.blur();
    assert.equal(state.submitted().depth_m, "102.45");
    assert.equal(state.pairs.depth.range.value, 45);
});
