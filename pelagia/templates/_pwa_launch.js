(() => {
    if (!window.matchMedia('(display-mode: standalone)').matches &&
        !window.matchMedia('(display-mode: fullscreen)').matches &&
        !window.navigator.standalone) return;

    const root = document.documentElement;
    root.classList.add('pwa-launching');
    function finish() {
        root.classList.remove('pwa-launching');
        window.clearTimeout(timeout);
    }
    // Deferred scripts and styles are ready at DOMContentLoaded; photos can
    // continue loading with the app's existing media placeholders.
    const timeout = window.setTimeout(finish, 15000);
    document.addEventListener('DOMContentLoaded', finish, { once: true });
    window.addEventListener('pagehide', finish, { once: true });
    window.addEventListener('pageshow', finish, { once: true });
})();
