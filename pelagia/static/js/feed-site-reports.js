(() => {
    const POLL_MS = 2000;
    const DEADLINE_MS = 120000;

    function initFollowedSiteReports() {
        const cards = [...document.querySelectorAll('[data-followed-site-report]')];
        if (!cards.length) return;
        const track = document.querySelector('[data-site-reports-track]');
        let stopped = false;
        const controllers = new Set();
        const timers = new Map();
        const loading = new Map();
        let generation = 0;

        const delay = (milliseconds) => new Promise((resolve) => {
            const timer = window.setTimeout(() => { timers.delete(timer); resolve(); }, milliseconds);
            timers.set(timer, resolve);
        });

        async function requestJson(url, method, controller) {
            const response = await fetch(url, {
                method, credentials: 'same-origin', cache: 'no-store',
                headers: {'X-Requested-With': 'fetch'}, signal: controller.signal,
            });
            let data;
            try { data = await response.json(); } catch (_error) { throw new Error('Invalid response'); }
            return {response, data};
        }

        async function warmDependency(url, method, controller, deadline) {
            while (!stopped && !controller.signal.aborted && Date.now() < deadline) {
                const {response, data} = await requestJson(url, method, controller);
                if (response.status === 202 || data?.status === 'pending') { await delay(POLL_MS); continue; }
                if (!response.ok) throw new Error('Dependency unavailable');
                return data;
            }
            throw new Error('Dependency timeout');
        }

        async function loadCard(card) {
            const loadGeneration = generation;
            const body = card.querySelector('[data-followed-report-body]');
            const text = card.querySelector('[data-followed-report-text]');
            const controller = new AbortController();
            controllers.add(controller);
            const deadline = Date.now() + DEADLINE_MS;
            const finishLoading = window.PelagiaLoading?.begin(
                body, 'Loading daily dive site report',
                '<span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span>'
            ) || (() => {});
            const timeout = window.setTimeout(() => controller.abort(), DEADLINE_MS);
            loading.set(controller, {finish: finishLoading, timeout});
            let dependenciesStarted = false;
            try {
                while (!stopped && loadGeneration === generation && Date.now() < deadline) {
                    const {response, data} = await requestJson(card.dataset.reportUrl, 'POST', controller);
                    if (stopped || loadGeneration !== generation) return;
                    if (response.ok && data?.status === 'complete' && typeof data.report === 'string' && data.report.trim()) {
                        finishLoading();
                        text.textContent = data.report;
                        card.dataset.reportState = 'ready';
                        return;
                    }
                    if (response.status === 202 || data?.status === 'pending') {
                        if (data?.reason === 'dependencies' && !dependenciesStarted) {
                            dependenciesStarted = true;
                            await Promise.all([
                                warmDependency(card.dataset.descriptionUrl, 'POST', controller, deadline),
                                warmDependency(card.dataset.conditionsUrl, 'GET', controller, deadline),
                            ]);
                            await warmDependency(card.dataset.conditionsUrl.replace(/\/conditions$/, '/visibility'), 'GET', controller, deadline);
                        } else await delay(POLL_MS);
                        continue;
                    }
                    throw new Error('Report unavailable');
                }
                throw new Error('Report timeout');
            } catch (_error) {
                if (stopped || loadGeneration !== generation) return;
                finishLoading();
                text.textContent = 'Today’s report is unavailable. Open the site for conditions and forecasts.';
                card.dataset.reportState = 'unavailable';
            } finally {
                controller.abort();
                window.clearTimeout(timeout);
                loading.delete(controller);
                controllers.delete(controller);
            }
        }

        cards.forEach((card) => {
            loadCard(card);
        });

        track?.addEventListener('keydown', (event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            if (event.key === 'Home' || event.key === 'End') {
                track.scrollTo({left: event.key === 'Home' ? 0 : track.scrollWidth});
                return;
            }
            const distance = cards[0].getBoundingClientRect().width + 12;
            track.scrollBy({left: event.key === 'ArrowLeft' ? -distance : distance});
        });

        window.addEventListener('pagehide', () => {
            stopped = true;
            generation++;
            controllers.forEach((controller) => controller.abort());
            loading.forEach(({finish, timeout}) => { finish(); window.clearTimeout(timeout); });
            timers.forEach((resolve, timer) => { window.clearTimeout(timer); resolve(); });
            timers.clear();
        });
        window.addEventListener('pageshow', (event) => {
            if (!event.persisted) return;
            stopped = false;
            cards.forEach((card) => {
                if (card.dataset.reportState === 'loading') loadCard(card);
            });
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFollowedSiteReports);
    else initFollowedSiteReports();
})();
