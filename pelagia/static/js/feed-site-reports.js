(() => {
    const POLL_MS = 2000;
    const DEADLINE_MS = 120000;

    function initFollowedSiteReports() {
        const cards = [...document.querySelectorAll('[data-followed-site-report]')];
        if (!cards.length) return;
        let stopped = false;
        const controllers = new Set();
        const timers = new Set();

        const delay = (milliseconds) => new Promise((resolve) => {
            const timer = window.setTimeout(() => { timers.delete(timer); resolve(); }, milliseconds);
            timers.add(timer);
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
            while (!stopped && Date.now() < deadline) {
                const {response, data} = await requestJson(url, method, controller);
                if (response.status === 202 || data?.status === 'pending') { await delay(POLL_MS); continue; }
                if (!response.ok) throw new Error('Dependency unavailable');
                return data;
            }
            throw new Error('Dependency timeout');
        }

        function setExpanded(card, expanded) {
            const text = card.querySelector('[data-followed-report-text]');
            const toggle = card.querySelector('[data-followed-report-toggle]');
            text.classList.toggle('is-expanded', expanded);
            toggle.setAttribute('aria-expanded', String(expanded));
            toggle.textContent = expanded ? 'Show less' : 'Read more';
        }

        function revealToggle(card) {
            const text = card.querySelector('[data-followed-report-text]');
            const toggle = card.querySelector('[data-followed-report-toggle]');
            window.requestAnimationFrame(() => {
                if (stopped || !text.isConnected) return;
                toggle.hidden = text.scrollHeight <= text.clientHeight + 1;
            });
        }

        async function loadCard(card) {
            const body = card.querySelector('[data-followed-report-body]');
            const text = card.querySelector('[data-followed-report-text]');
            const toggle = card.querySelector('[data-followed-report-toggle]');
            const controller = new AbortController();
            controllers.add(controller);
            const deadline = Date.now() + DEADLINE_MS;
            const finishLoading = window.PelagiaLoading?.begin(
                body, 'Loading daily dive site report',
                '<span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span>'
            ) || (() => {});
            let dependenciesStarted = false;
            try {
                while (!stopped && Date.now() < deadline) {
                    const {response, data} = await requestJson(card.dataset.reportUrl, 'POST', controller);
                    if (response.ok && data?.status === 'complete' && typeof data.report === 'string') {
                        finishLoading();
                        text.textContent = data.report;
                        card.dataset.reportState = 'ready';
                        setExpanded(card, false);
                        revealToggle(card);
                        return;
                    }
                    if (response.status === 202 || data?.status === 'pending') {
                        if (data?.reason === 'dependencies' && !dependenciesStarted) {
                            dependenciesStarted = true;
                            await Promise.all([
                                warmDependency(card.dataset.descriptionUrl, 'POST', controller, deadline),
                                warmDependency(card.dataset.conditionsUrl, 'GET', controller, deadline),
                            ]);
                        } else await delay(POLL_MS);
                        continue;
                    }
                    throw new Error('Report unavailable');
                }
                throw new Error('Report timeout');
            } catch (_error) {
                if (stopped || controller.signal.aborted) return;
                finishLoading();
                text.textContent = 'Today’s report is unavailable.';
                toggle.hidden = true;
                card.dataset.reportState = 'unavailable';
            } finally {
                controllers.delete(controller);
            }
        }

        cards.forEach((card) => {
            card.querySelector('[data-followed-report-toggle]').addEventListener('click', () => {
                const toggle = card.querySelector('[data-followed-report-toggle]');
                setExpanded(card, toggle.getAttribute('aria-expanded') !== 'true');
            });
            loadCard(card);
        });

        window.addEventListener('pagehide', () => {
            stopped = true;
            controllers.forEach((controller) => controller.abort());
            timers.forEach((timer) => window.clearTimeout(timer));
            timers.clear();
        }, {once: true});
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFollowedSiteReports);
    else initFollowedSiteReports();
})();
