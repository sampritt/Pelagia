(() => {
    function init() {
        const deck = document.querySelector('[data-nearby-carousel]');
        if (deck) window.PelagiaSiteCarousel(deck, [...deck.querySelectorAll('.nearby-place-card')], deck.dataset.nearbyLabel || 'Dive site');
        const form = document.querySelector('.place-review-form');
        form?.addEventListener('submit', () => {
            const button = form.querySelector('[type="submit"]');
            button.disabled = true;
            button.textContent = 'Saving…';
        });
        window.addEventListener('pageshow', () => {
            const button = form?.querySelector('[type="submit"]');
            if (button) {
                button.disabled = false;
                button.textContent = form.dataset.savedLabel;
            }
        });
        if (form) form.dataset.savedLabel = form.querySelector('[type="submit"]').textContent;
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
    else init();
})();
