document.addEventListener("DOMContentLoaded", async () => {
    const viewport = document.getElementById("oceanMap");
    if (!viewport || !window.PelagiaMaps) {
        return;
    }

    const dives = await fetchJson("/api/dives/mine");
    const plottable = dives.filter((dive) => window.PelagiaMaps.isValidLatLng(dive.latitude, dive.longitude));
    if (!plottable.length) {
        const empty = document.createElement("div");
        empty.className = "map-empty";
        empty.innerHTML = "<h2>No pins yet</h2><p>Logged dives with coordinates appear here.</p>";
        viewport.appendChild(empty);
        return;
    }

    const map = window.PelagiaMaps.createInteractiveMap(viewport, {
        markers: plottable,
        onMarkerClick: (dive) => openDive(dive.id),
    });

    document.getElementById("zoomIn")?.addEventListener("click", () => map.zoomIn());
    document.getElementById("zoomOut")?.addEventListener("click", () => map.zoomOut());
});
