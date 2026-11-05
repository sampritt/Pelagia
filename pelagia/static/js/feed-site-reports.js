(() => {
    const POLL_MS = 2000;
    const DEADLINE_MS = 120000;

    function initFollowedSiteReports() {
        const feed = document.querySelector('[data-feed-report]');
        let cards = [...document.querySelectorAll('[data-followed-site-report]')];
        if (!cards.length && !feed) return;
        let stopped = false;
        const controllers = new Set();
        const timers = new Map();
        const loading = new Map();
        let generation = 0;
        let selectionTimer, selectionController;
        let carousel;

        const initCarousel = () => window.PelagiaSiteCarousel(feed, cards);

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

        const swellGrades = {calm: 'green', light: 'green', choppy: 'yellow', rough: 'orange', 'very rough': 'red'};
        const finiteNonnegative = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
        const windDescriptor = speed => speed < 10 ? ['green', 'Light'] : speed < 15 ? ['yellow', 'Moderate']
            : speed < 20 ? ['orange', 'Strong'] : ['red', 'Very strong'];
        function setCondition(card, selector, value, grade, descriptor) {
            const node = card.querySelector(selector);
            node.textContent = value;
            if (grade) node.dataset.grade = grade;
            else delete node.dataset.grade;
            if (descriptor && value !== '—') {
                node.title = descriptor;
                node.setAttribute('aria-label', `${value}, ${descriptor}`);
            } else {
                node.removeAttribute('title');
                node.removeAttribute('aria-label');
            }
        }

        async function loadConditions(card) {
            const controller = new AbortController();
            const loadGeneration = generation;
            const deadline = Date.now() + DEADLINE_MS;
            const timeout = window.setTimeout(() => controller.abort(), DEADLINE_MS);
            controllers.add(controller);
            loading.set(controller, {finish: () => {}, timeout});
            card.dataset.conditionsState = 'loading';
            try {
                const conditions = await warmDependency(card.dataset.conditionsUrl, 'GET', controller, deadline);
                if (stopped || loadGeneration !== generation) return;
                const current = conditions.status === 'complete' ? conditions.current || {} : {};
                const validSwell = finiteNonnegative(current.swell_height_m) && finiteNonnegative(current.swell_period_s)
                    && (current.swell_height_m === 0 || current.swell_period_s > 0);
                const feet = card.dataset.lengthUnit === 'ft';
                const height = validSwell ? (feet ? Math.round(current.swell_height_m * 3.28084) : Number(current.swell_height_m.toFixed(1))) : null;
                const period = validSwell ? Number(current.swell_period_s.toFixed(1)) : null;
                const swellDescriptor = typeof current.swell === 'string' ? current.swell : '';
                const swell = validSwell ? swellDescriptor || `${height} ${feet ? 'ft' : 'm'}` : '—';
                const swellDetail = validSwell ? `${height} ${feet ? 'ft' : 'm'} · ${period} s` : 'Height · period';
                card.querySelector('[data-followed-swell-detail]').textContent = swellDetail;
                setCondition(card, '[data-followed-swell]', swell, validSwell ? swellGrades[swellDescriptor.toLowerCase()] : null, validSwell ? `${height} ${feet ? 'feet' : 'meters'}, ${period} second period` : '');
                const validWind = finiteNonnegative(current.wind_speed_kn);
                const [windGrade, windLabel] = validWind ? windDescriptor(current.wind_speed_kn) : [];
                const windDetail = validWind ? `${Number(current.wind_speed_kn.toFixed(1))} kn` : 'Speed in knots';
                card.querySelector('[data-followed-wind-detail]').textContent = windDetail;
                setCondition(card, '[data-followed-wind]', windLabel || '—', windGrade, validWind ? windDetail : '');
                return conditions;
            } catch (_error) {
                // Keep unavailable values as dashes while preserving any conditions already loaded.
            } finally {
                window.clearTimeout(timeout);
                loading.delete(controller);
                controllers.delete(controller);
                if (!stopped && loadGeneration === generation) card.dataset.conditionsState = 'ready';
            }
        }

        async function loadCard(card, conditionsReady) {
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
                            const [, conditions] = await Promise.all([
                                warmDependency(card.dataset.descriptionUrl, 'POST', controller, deadline),
                                conditionsReady,
                            ]);
                            if (conditions?.status !== 'complete') throw new Error('Conditions unavailable');
                        } else await delay(POLL_MS);
                        continue;
                    }
                    throw new Error('Report unavailable');
                }
                throw new Error('Report timeout');
            } catch (_error) {
                if (stopped || loadGeneration !== generation) return;
                finishLoading();
                text.textContent = card.dataset.reportUnavailable || 'Today’s report is unavailable. Open the site for conditions and forecasts.';
                card.dataset.reportState = 'unavailable';
            } finally {
                controller.abort();
                window.clearTimeout(timeout);
                loading.delete(controller);
                controllers.delete(controller);
            }
        }

        function startCards() {
            cards.forEach((card) => {
                loadCard(card, loadConditions(card));
            });
        }

        function cancelLoads() {
            generation++;
            controllers.forEach((controller) => controller.abort());
            loading.forEach(({finish, timeout}) => { finish(); window.clearTimeout(timeout); });
            timers.forEach((resolve, timer) => { window.clearTimeout(timer); resolve(); });
            timers.clear();
        }

        function scheduleSelection(retry = false) {
            window.clearTimeout(selectionTimer);
            if (!feed || stopped) return;
            const milliseconds = retry ? 60000 : Math.max(1000, Number(feed.dataset.nextRefresh) * 1000 - Date.now() + 100);
            selectionTimer = window.setTimeout(() => {
                if (!document.hidden) refreshSelection();
            }, milliseconds);
        }

        async function refreshSelection() {
            if (!feed || stopped || selectionController) return;
            const controller = new AbortController();
            selectionController = controller;
            const timeout = window.setTimeout(() => controller.abort(), 15000);
            let retry = false;
            try {
                const {response, data} = await requestJson(feed.dataset.selectionUrl, 'GET', controller);
                if (stopped || controller.signal.aborted) return;
                if (!response.ok || typeof data.key !== 'string' || typeof data.html !== 'string'
                    || !Number.isFinite(data.next_refresh)) throw new Error('Selection unavailable');
                if (data.key !== feed.dataset.selectionKey) {
                    const restoreFocus = feed.contains(document.activeElement);
                    const currentUrl = cards[carousel?.index || 0]?.dataset.reportUrl;
                    const focusedDot = document.activeElement?.hasAttribute('data-report-dot');
                    carousel?.destroy();
                    cancelLoads();
                    feed.innerHTML = data.html;
                    feed.hidden = !data.html.trim();
                    feed.dataset.selectionKey = data.key;
                    cards = [...feed.querySelectorAll('[data-followed-site-report]')];
                    window.initStaticMaps?.(feed);
                    carousel = initCarousel();
                    const index = Math.max(0, cards.findIndex(card => card.dataset.reportUrl === currentUrl));
                    carousel?.goTo(index, 'instant');
                    startCards();
                    if (restoreFocus) (focusedDot && feed.querySelector(`[data-report-dot="${index}"]`)
                        || cards[index] || document.querySelector('.brief-card summary')
                        || document.querySelector('#mainContent'))?.focus({preventScroll: true});
                }
                feed.dataset.nextRefresh = data.next_refresh;
            } catch (_error) {
                // Preserve the visible cards and their site links while offline.
                retry = true;
            } finally {
                window.clearTimeout(timeout);
                if (selectionController === controller) {
                    selectionController = null;
                    scheduleSelection(retry);
                }
            }
        }

        carousel = initCarousel();
        startCards();
        scheduleSelection();

        window.addEventListener('pagehide', () => {
            stopped = true;
            cancelLoads();
            window.clearTimeout(selectionTimer);
            selectionController?.abort();
            selectionController = null;
        });
        window.addEventListener('pageshow', (event) => {
            if (!event.persisted) return;
            stopped = false;
            cards.forEach((card) => {
                const needsReport = card.dataset.reportState === 'loading';
                const conditionsReady = (card.dataset.conditionsState === 'loading' || needsReport)
                    ? loadConditions(card) : undefined;
                if (needsReport) loadCard(card, conditionsReady);
            });
            refreshSelection();
        });
        document.addEventListener?.('visibilitychange', () => {
            if (!document.hidden && feed) {
                if (Date.now() >= Number(feed.dataset.nextRefresh) * 1000) refreshSelection();
                else scheduleSelection();
            }
        });
        window.addEventListener('online', () => { if (feed) refreshSelection(); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFollowedSiteReports);
    else initFollowedSiteReports();
})();
