const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup() {
    const origin = "https://pelagia.example";
    const handlers = {};
    const storage = new Map();
    const deleted = [];
    const calls = [];
    let claims = 0;
    let skips = 0;
    const source = fs.readFileSync(path.join(__dirname, "../pelagia/static/service-worker.js"), "utf8")
        .replace("__PELAGIA_CACHE_VERSION__", "release2")
        .replace("__PELAGIA_PRECACHE__", JSON.stringify(["/offline.html", "/static/css/app.css?v=release2", "/manifest.webmanifest"]));
    const caches = {
        async open(name) {
            if (!storage.has(name)) storage.set(name, new Map());
            const entries = storage.get(name);
            return {
                async addAll(paths) { paths.forEach(url => entries.set(new URL(url, origin).href, {cached: url})); },
                async match(request) { return entries.get(new URL(request.url || request, origin).href); },
            };
        },
        async keys() { return [...storage.keys()]; },
        async delete(name) { deleted.push(name); return storage.delete(name); },
    };
    const state = {offline: false, response: {live: true}};
    const context = vm.createContext({URL, Response, caches,
        fetch: async request => {
            calls.push(request);
            if (state.offline) throw new TypeError("Network unavailable");
            return state.response;
        },
        self: {location: {origin}, addEventListener: (name, handler) => { handlers[name] = handler; },
            clients: {async claim() { claims++; }}, async skipWaiting() { skips++; }},
    });
    vm.runInContext(source, context);
    async function emit(name, event = {}) {
        const pending = [];
        const result = {intercepted: false};
        handlers[name]({...event, waitUntil(promise) { pending.push(promise); },
            respondWith(promise) { result.intercepted = true; pending.push(Promise.resolve(promise).then(value => { result.response = value; })); }});
        await Promise.all(pending);
        return result;
    }
    const request = (url, method = "GET", mode = "cors") => ({url: new URL(url, origin).href, method, mode});
    return {state, calls, storage, deleted, emit, request, get claims() {return claims;}, get skips() {return skips;}};
}

test("install caches public assets without forcing activation; activation only deletes Pelagia caches", async () => {
    const s = setup();
    s.storage.set("other-app", new Map());
    s.storage.set("pelagia-public-release1", new Map());
    await s.emit("install");
    assert.equal(s.skips, 0);
    assert.equal(s.storage.get("pelagia-public-release2").size, 3);
    await s.emit("activate");
    assert.deepEqual(s.deleted, ["pelagia-public-release1"]);
    assert.equal(s.claims, 1);
    await s.emit("message", {data: {type: "UNRECOGNIZED"}});
    assert.equal(s.skips, 0);
    await s.emit("message", {data: {type: "SKIP_WAITING"}});
    assert.equal(s.skips, 1);
});

test("navigation stays live across accounts and falls back offline without caching private HTML", async () => {
    const s = setup();
    await s.emit("install");
    for (const url of ["/home", "/you", "/dive/7", "/auth/google/callback?code=secret"]) {
        s.state.response = {username: "user1", url};
        assert.equal((await s.emit("fetch", {request: s.request(url, "GET", "navigate")})).response, s.state.response);
        s.state.response = {username: "user2", url};
        assert.equal((await s.emit("fetch", {request: s.request(url, "GET", "navigate")})).response, s.state.response);
    }
    assert.equal(s.storage.get("pelagia-public-release2").size, 3);
    s.state.offline = true;
    assert.deepEqual((await s.emit("fetch", {request: s.request("/dive/7", "GET", "navigate")})).response, {cached: "/offline.html"});
});

test("API requests, uploads, maps, unknown assets and every mutation bypass the cache", async () => {
    const s = setup();
    await s.emit("install");
    for (const [url, method, mode] of [
        ["/api/dives/mine", "GET", "cors"], ["/uploads/profiles/avatar.jpg", "GET", "no-cors"],
        ["https://tile.openstreetmap.org/1/0/0.png", "GET", "no-cors"],
        ["/static/uploads/dives/private.jpg", "GET", "no-cors"], ["/static/css/app.css?v=release1", "GET", "cors"],
        ["/login", "POST", "navigate"], ["/logout", "POST", "navigate"], ["/dive/new", "POST", "navigate"],
        ["/api/dives/7/like", "POST", "cors"], ["/dive/7", "DELETE", "cors"],
    ]) assert.equal((await s.emit("fetch", {request: s.request(url, method, mode)})).intercepted, false, url);
    assert.equal(s.calls.length, 0);
});

test("only exact versioned assets work offline and server HTTP errors remain visible", async () => {
    const s = setup();
    await s.emit("install");
    s.state.offline = true;
    assert.deepEqual((await s.emit("fetch", {request: s.request("/static/css/app.css?v=release2")})).response, {cached: "/static/css/app.css?v=release2"});
    assert.deepEqual((await s.emit("fetch", {request: s.request("/manifest.webmanifest")})).response, {cached: "/manifest.webmanifest"});
    s.state.offline = false;
    s.state.response = new Response("Unavailable", {status: 503});
    assert.equal((await s.emit("fetch", {request: s.request("/home", "GET", "navigate")})).response.status, 503);
});
