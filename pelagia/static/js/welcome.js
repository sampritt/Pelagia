(() => {
    const splash = document.querySelector('[data-welcome-splash]');
    if (!splash) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const background = [...document.body.children]
        .filter(element => element !== splash && !['SCRIPT', 'NOSCRIPT'].includes(element.tagName))
        .map(element => ({ element, inert: element.inert }));
    const previousTheme = document.querySelector('meta[name="theme-color"]');
    const theme = previousTheme?.content;
    let revealing = false;
    let finished = false;
    let revealTimer;
    let finishTimer;

    // Replace immediately so even refreshing or leaving mid-animation won't replay it.
    window.history.replaceState(window.history.state, '', splash.dataset.feedUrl);
    background.forEach(({ element }) => { element.inert = true; });
    if (previousTheme) previousTheme.content = '#062a36';
    splash.focus({ preventScroll: true });

    function finish(restoreFocus = true) {
        if (finished) return;
        finished = true;
        window.clearTimeout(revealTimer);
        window.clearTimeout(finishTimer);
        background.forEach(({ element, inert }) => { element.inert = inert; });
        document.body.classList.remove('welcome-pending', 'welcome-revealing');
        splash.remove();
        if (previousTheme) previousTheme.content = theme;
        if (restoreFocus) document.getElementById('mainContent')?.focus({ preventScroll: true });
    }

    function reveal() {
        if (revealing || finished) return;
        revealing = true;
        document.body.classList.add('welcome-revealing');
        finishTimer = window.setTimeout(finish, reducedMotion ? 180 : 900);
    }

    splash.querySelector('[data-welcome-continue]').addEventListener('click', event => {
        if (event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        reveal();
    });
    splash.addEventListener('keydown', event => {
        if (event.key === 'Escape') reveal();
        if (event.key === 'Tab') {
            event.preventDefault();
            splash.querySelector('[data-welcome-continue]').focus();
        }
    });
    window.addEventListener('pagehide', () => finish(false), { once: true });
    revealTimer = window.setTimeout(reveal, reducedMotion ? 450 : 1650);
})();
