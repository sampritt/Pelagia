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

        const swellGrades = {calm: 'green', light: 'green', choppy: 'yellow', rough: 'orange', 'very rough': 'red'};
        const visibilityGrades = {excellent: 'green', good: 'green', fair: 'yellow', poor: 'orange', 'very poor': 'red'};
        const finiteNonnegative = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
        const windDescriptor = speed => speed < 10 ? ['green', 'Light'] : speed < 15 ? ['yellow', 'Moderate']
            : speed < 20 ? ['orange', 'Fresh'] : ['red', 'Strong'];
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
                const swell = validSwell ? `${height}${feet ? 'ft' : 'm'} @ ${period}s` : '—';
                const swellDescriptor = typeof current.swell === 'string' ? current.swell : '';
                setCondition(card, '[data-followed-swell]', swell, validSwell ? swellGrades[swellDescriptor.toLowerCase()] : null, swellDescriptor);
                const validWind = finiteNonnegative(current.wind_speed_kn);
                const [windGrade, windLabel] = validWind ? windDescriptor(current.wind_speed_kn) : [];
                setCondition(card, '[data-followed-wind]', validWind ? `${Number(current.wind_speed_kn.toFixed(1))} kn` : '—', windGrade, windLabel);
                if (conditions.status === 'complete') {
                    const visibility = await warmDependency(card.dataset.visibilityUrl, 'GET', controller, deadline);
                    if (stopped || loadGeneration !== generation) return;
                    const clarity = visibility.status === 'complete' && typeof visibility.clarity === 'string' ? visibility.clarity : '';
                    setCondition(card, '[data-followed-visibility]', clarity ? clarity.charAt(0).toUpperCase() + clarity.slice(1) : '—', visibilityGrades[clarity.toLowerCase()]);
                }
            } catch (_error) {
                // Keep unavailable values as dashes while preserving any conditions already loaded.
            } finally {
                window.clearTimeout(timeout);
                loading.delete(controller);
                controllers.delete(controller);
                if (!stopped && loadGeneration === generation) card.dataset.conditionsState = 'ready';
            }
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
            loadConditions(card);
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
                if (card.dataset.conditionsState === 'loading') loadConditions(card);
            });
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFollowedSiteReports);
    else initFollowedSiteReports();
})();
