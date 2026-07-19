document.addEventListener("DOMContentLoaded", async () => {
    const viewport = document.getElementById("oceanMap");
    const world = document.getElementById("mapWorld");
    if (!viewport || !world) {
        return;
    }

    const state = {
        scale: 1,
        x: -800,
        y: -450,
        dragging: false,
        lastX: 0,
        lastY: 0,
    };

    const applyTransform = () => {
        world.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    };

    const centerWorld = () => {
        state.x = viewport.clientWidth / 2 - 800 * state.scale;
        state.y = viewport.clientHeight / 2 - 450 * state.scale;
        applyTransform();
    };

    const setScale = (nextScale, originX = viewport.clientWidth / 2, originY = viewport.clientHeight / 2) => {
        const oldScale = state.scale;
        const next = clamp(nextScale, 0.65, 4);
        const worldX = (originX - state.x) / oldScale;
        const worldY = (originY - state.y) / oldScale;
        state.scale = next;
        state.x = originX - worldX * next;
        state.y = originY - worldY * next;
        applyTransform();
    };

    centerWorld();
    window.addEventListener("resize", centerWorld);

    viewport.addEventListener("wheel", (event) => {
        event.preventDefault();
        const delta = event.deltaY > 0 ? -0.15 : 0.15;
        setScale(state.scale + delta, event.clientX, event.clientY);
    }, { passive: false });

    viewport.addEventListener("pointerdown", (event) => {
        state.dragging = true;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        viewport.classList.add("dragging");
        viewport.setPointerCapture(event.pointerId);
    });

    viewport.addEventListener("pointermove", (event) => {
        if (!state.dragging) {
            return;
        }
        state.x += event.clientX - state.lastX;
        state.y += event.clientY - state.lastY;
        state.lastX = event.clientX;
        state.lastY = event.clientY;
        applyTransform();
    });

    viewport.addEventListener("pointerup", (event) => {
        state.dragging = false;
        viewport.classList.remove("dragging");
        viewport.releasePointerCapture(event.pointerId);
    });

    document.getElementById("zoomIn")?.addEventListener("click", () => setScale(state.scale + 0.25));
    document.getElementById("zoomOut")?.addEventListener("click", () => setScale(state.scale - 0.25));

    const dives = await fetchJson("/api/dives/mine");
    const plottable = dives.filter((dive) => dive.latitude !== null && dive.longitude !== null);
    if (!plottable.length) {
        const empty = document.createElement("div");
        empty.className = "map-empty";
        empty.innerHTML = '<h2>No pins yet</h2><p>Logged dives with coordinates appear here.</p>';
        viewport.appendChild(empty);
        return;
    }

    plottable.forEach((dive) => {
        const point = coordinateToPoint(dive.latitude, dive.longitude);
        const pin = document.createElement("button");
        pin.type = "button";
        pin.className = "world-pin";
        pin.style.setProperty("--pin-x", `${point.x}%`);
        pin.style.setProperty("--pin-y", `${point.y}%`);
        pin.title = `${dive.site_name} | ${dive.date}`;
        pin.addEventListener("click", (event) => {
            event.stopPropagation();
            openDive(dive.id);
        });
        world.appendChild(pin);
    });
});
