/* Shared full-width, snap-scrolling site cards with accessible dot navigation. */
(() => {
    function initCarousel(feed, cards, label = "Report") {
        const track = feed?.querySelector('[data-site-reports-track]');
        if (!track || cards.length < 2) return null;
        const dots = [...feed.querySelectorAll('[data-report-dot]')];
        const position = feed.querySelector('[data-report-position]');
        let index = 0;
        const announce = () => {
            dots.forEach((dot, i) => {
                if (i === index) dot.setAttribute('aria-current', 'true');
                else dot.removeAttribute('aria-current');
            });
            const message = `${label} ${index + 1} of ${cards.length}: ${cards[index].querySelector('h3').textContent}`;
            if (position && position.textContent !== message) position.textContent = message;
        };
        const goTo = (next, behavior = 'smooth') => {
            index = Math.max(0, Math.min(cards.length - 1, next));
            const left = track.scrollLeft + cards[index].getBoundingClientRect().left - track.getBoundingClientRect().left;
            track.scrollTo({left, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : behavior});
            announce();
        };
        const onScroll = () => {
            const left = track.getBoundingClientRect().left;
            index = cards.reduce((nearest, card, i) =>
                Math.abs(card.getBoundingClientRect().left - left) < Math.abs(cards[nearest].getBoundingClientRect().left - left) ? i : nearest, 0);
            announce();
        };
        const onKey = (event) => {
            if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
            const next = {ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: cards.length - 1}[event.key];
            if (next === undefined) return;
            event.preventDefault();
            goTo(next);
            if (cards.includes(document.activeElement)) cards[index].focus({preventScroll: true});
        };
        const onDot = (event) => {
            const dot = event.target.closest('[data-report-dot]');
            if (dot) goTo(Number(dot.dataset.reportDot));
        };
        const onResize = () => goTo(index, 'instant');
        track.addEventListener('scroll', onScroll, {passive: true});
        track.addEventListener('keydown', onKey);
        feed.addEventListener('click', onDot);
        const observer = window.ResizeObserver ? new window.ResizeObserver(onResize) : null;
        observer?.observe(track);
        window.addEventListener('resize', onResize);
        onScroll();
        return {goTo, get index() { return index; }, destroy() {
            track.removeEventListener('scroll', onScroll);
            track.removeEventListener('keydown', onKey);
            feed.removeEventListener('click', onDot);
            window.removeEventListener('resize', onResize);
            observer?.disconnect();
        }};
    }

    window.PelagiaSiteCarousel = initCarousel;
})();
