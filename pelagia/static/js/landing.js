(() => {
    const page = document.querySelector('.marketing-page');
    const toggle = document.querySelector('.marketing-menu-toggle');
    const navigation = document.querySelector('.marketing-navigation');
    if (!page || !toggle || !navigation) return;

    const setMenu = open => {
        page.toggleAttribute('data-menu-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    };
    page.setAttribute('data-navigation-ready', '');
    toggle.hidden = false;
    toggle.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
    toggle.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setMenu(true);
            navigation.querySelector('a')?.focus();
        }
    });
    navigation.addEventListener('click', event => {
        if (event.target.closest('a')) setMenu(false);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && page.hasAttribute('data-menu-open')) {
            setMenu(false);
            toggle.focus();
        }
    });
    document.addEventListener('click', event => {
        if (!event.target.closest('.marketing-header')) setMenu(false);
    });
    document.addEventListener('focusin', event => {
        if (!event.target.closest('.marketing-header')) setMenu(false);
    });
    window.matchMedia('(max-width: 900px)').addEventListener('change', () => setMenu(false));

    if ('IntersectionObserver' in window) {
        const links = [...navigation.querySelectorAll('a[href^="#"]')];
        const observer = new IntersectionObserver(entries => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue;
                for (const link of links) {
                    if (link.hash === `#${entry.target.id}`) link.setAttribute('aria-current', 'location');
                    else link.removeAttribute('aria-current');
                }
            }
        }, { rootMargin: '-18% 0px -60% 0px', threshold: 0 });
        for (const link of links) {
            const section = document.querySelector(link.hash);
            if (section) observer.observe(section);
        }
    }
})();
