(() => {
    function init() {
        const host = document.querySelector('[data-site-report]');
        if (!host) return;
        const body = host.querySelector('[data-report-body]');
        const text = host.querySelector('[data-report-text]');
        const retry = host.querySelector('[data-report-retry]');
        let active = false, stopped = false, timer, deadline, controller, endLoading = () => {};
        let generation = 0;
        let reportDate, zone;
        const localDate = () => new Intl.DateTimeFormat('en-CA', {
            timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
        }).format(new Date());
        function finish(ticket, message, canRetry = false, state = 'unavailable') {
            if (stopped || ticket !== generation) return;
            generation++;
            active = false;
            window.clearTimeout(timer);
            window.clearTimeout(deadline);
            endLoading();
            host.dataset.reportState = state;
            text.textContent = message;
            retry.hidden = !canRetry;
        }
        async function load() {
            if (active || stopped) return;
            if (reportDate && localDate() === reportDate) return;
            const ticket = ++generation;
            active = true;
            host.dataset.reportState = 'loading';
            retry.hidden = true;
            text.textContent = 'Preparing today’s report…';
            endLoading = window.PelagiaLoading?.begin(body, 'Loading today’s report',
                '<span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span><span class="skeleton skeleton-line"></span>') || (() => {});
            controller = new AbortController();
            const requestController = controller;
            deadline = window.setTimeout(() => {
                requestController.abort();
                finish(ticket, 'The full forecast isn’t available yet. Try again shortly.', true);
            }, 100000);
            const started = Date.now();
            async function poll() {
                try {
                    const response = await fetch(host.dataset.url, {
                        method: 'POST', credentials: 'same-origin', cache: 'no-store',
                        headers: { 'X-Requested-With': 'fetch' }, signal: requestController.signal,
                    });
                    if (stopped || ticket !== generation) return;
                    if (!response.ok) throw new Error('Unavailable');
                    const data = await response.json();
                    if (stopped || ticket !== generation) return;
                    if (data.status === 'pending') {
                        if (data.reason === 'dependencies') window.dispatchEvent(new Event('pelagia:report-refresh'));
                        if (Date.now() - started > 90000) throw new Error('Still waiting');
                        timer = window.setTimeout(poll, 2000);
                        return;
                    }
                    if (data.status === 'complete' && typeof data.report === 'string') {
                        reportDate = data.date;
                        zone = data.timezone;
                        // A response crossing local midnight must be checked again.
                        if (localDate() !== reportDate) {
                            active = false; window.clearTimeout(deadline); endLoading(); load(); return;
                        }
                        finish(ticket, data.report, false, 'ready');
                    } else {
                        // Once an upstream attempt has failed, the server preserves
                        // the daily claim to prevent another billable call.
                        if (data.date) { reportDate = data.date; zone = data.timezone; }
                        const permanent = ['coordinates', 'not_ocean', 'configuration'].includes(data.reason);
                        const message = data.reason === 'coordinates' || data.reason === 'not_ocean'
                            ? 'A conditions report isn’t available for this site yet.'
                            : data.date ? 'Today’s report is unavailable. Check back tomorrow.'
                                : 'Today’s report is unavailable. You can still explore the forecast below.';
                        finish(ticket, message, !data.date && !permanent);
                    }
                } catch (_error) {
                    finish(ticket, 'We couldn’t load today’s report. Try again shortly.', true);
                }
            }
            poll();
        }
        host.addEventListener('toggle', () => { if (host.open) load(); });
        retry.addEventListener('click', load);
        function openLinkedReport() {
            if (window.location.hash !== '#daily-report') return;
            host.open = true;
            load();
            window.requestAnimationFrame(() => host.scrollIntoView({block: 'start'}));
        }
        window.addEventListener('hashchange', openLinkedReport);
        openLinkedReport();
        // Recheck a report if this page stays open into the next local day.
        const checkDate = () => { if (host.open && reportDate && localDate() !== reportDate) load(); };
        let rollover = window.setInterval(checkDate, 60000);
        window.addEventListener('pagehide', () => {
            generation++;
            stopped = true; active = false; controller?.abort();
            window.clearTimeout(timer); window.clearInterval(rollover); endLoading();
            window.clearTimeout(deadline);
        });
        window.addEventListener('pageshow', event => {
            if (event.persisted) {
                stopped = false;
                rollover = window.setInterval(checkDate, 60000);
                if (host.open) load();
            }
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
