const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(selected) {
    function element() {
        return {
            value: "", hidden: true, children: [], handlers: {},
            set innerHTML(value) { this.html = value; this.children = []; },
            get innerHTML() { return this.html || ""; },
            addEventListener(event, handler) { this.handlers[event] = handler; },
            appendChild(child) { this.children.push(child); },
            querySelector(selector) {
                if (selector !== "button") throw new Error(`Unexpected selector: ${selector}`);
                if (!this.button) this.button = element();
                return this.button;
            },
            classList: { add() {} },
        };
    }
    const hidden = element();
    hidden.value = JSON.stringify(selected);
    const parts = Object.fromEntries(["input", "results", "suggestions", "tags"].map(name => [name, element()]));
    const form = { querySelector: selector => parts[selector.match(/data-species-(\w+)/)[1]] };
    const document = {
        addEventListener() {}, createElement: element,
        getElementById: id => id === "speciesJson" ? hidden : null,
    };
    const context = vm.createContext({ document, window: {}, URLSearchParams });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pelagia/static/js/app.js"), "utf8"), context);
    context.form = form;
    // No country means initialization needs no request. Explicit suggestion
    // loading below supplies additions through the real click handlers.
    vm.runInContext("initSpeciesPicker(form, () => '')", context);
    return { hidden, parts, context };
}

test("saved species initialize as removable tags and survive an unchanged save", () => {
    const selected = ["Coral", "Reef Fish", 'Diver\'s "fish" & ray'];
    const { hidden, parts } = setup(selected);
    assert.equal(parts.tags.children.length, selected.length);
    assert.deepEqual(JSON.parse(hidden.value), selected);
    for (const [index, tag] of parts.tags.children.entries()) {
        assert.equal(tag.className, "tag");
        assert.match(tag.innerHTML, /<button type="button" aria-label="Remove .+">&times;<\/button>/);
        assert.equal(typeof tag.querySelector("button").handlers.click, "function");
        if (index === 2) assert.match(tag.innerHTML, /&quot;fish&quot; &amp; ray/);
    }
    parts.tags.children[1].querySelector("button").handlers.click();
    assert.deepEqual(JSON.parse(hidden.value), [selected[0], selected[2]]);
    assert.equal(parts.tags.children.length, 2);
});

test("editing allows adding, deduplicating, removing all, and reopening species", async () => {
    const { hidden, parts, context } = setup(["Coral", "Reef Fish"]);
    vm.runInContext("fetchJson = async () => ['Turtle', 'coral']", context);
    await vm.runInContext("window.loadSpeciesSuggestions({ siteId: 1 })", context);
    parts.suggestions.children[0].handlers.click();
    parts.suggestions.children[1].handlers.click();
    assert.deepEqual(JSON.parse(hidden.value), ["Coral", "Reef Fish", "Turtle"]);
    assert.equal(parts.tags.children.length, 3);
    parts.tags.children[0].querySelector("button").handlers.click();
    const updated = ["Reef Fish", "Turtle"];
    assert.deepEqual(JSON.parse(hidden.value), updated);
    const reopened = setup(updated);
    assert.equal(reopened.parts.tags.children.length, 2);
    while (parts.tags.children.length) {
        parts.tags.children[0].querySelector("button").handlers.click();
    }
    assert.equal(hidden.value, "[]");
    assert.equal(setup([]).parts.tags.children.length, 0);
});
