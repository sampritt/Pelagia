/* Site tags select forecasts; all eight forecast rows share one horizontal scroll. */
(() => {
    const finite = value => typeof value === 'number' && Number.isFinite(value);
    const valid = value => finite(value) && value >= 0;
    const tenth = value => finite(value) ? (Math.round(value * 10) / 10).toFixed(1) : '—';
    const hour = (stamp, zone) => new Intl.DateTimeFormat('en-US', {
        timeZone: zone, hour: 'numeric', hour12: true,
    }).format(stamp * 1000).replace(/\s/g, '').toLowerCase();
    const date = (stamp, zone) => new Intl.DateTimeFormat('en-US', {
        timeZone: zone, month: 'short', day: 'numeric',
    }).format(stamp * 1000);
    const currentGrade = value => !valid(value) ? null : value < .5 ? ['green', 'Light']
        : value < 1 ? ['yellow', 'Moderate'] : value < 2 ? ['orange', 'Strong'] : ['red', 'Very Strong'];
    const windGrade = value => !valid(value) ? null : value < 10 ? ['green', 'Light']
        : value < 15 ? ['yellow', 'Moderate'] : value < 20 ? ['orange', 'Strong'] : ['red', 'Very strong'];
    const swellGrades = {calm: 'green', light: 'green', choppy: 'yellow', rough: 'orange', 'very rough': 'red'};
    const compass = degrees => {
        if (!finite(degrees) || degrees < 0 || degrees > 360) return null;
        const index = Math.round(degrees / 22.5) % 16;
        return {label: ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][index], degrees: index * 22.5};
    };
    const temperature = (value, unit) => finite(value) ? `${Math.round(unit === 'f' ? value * 9 / 5 + 32 : value)}°${unit === 'f' ? 'F' : 'C'}` : '—';
    const linkUrl = (base, target, stamp) => `${base}?forecast_time=${stamp}#forecast-${target}`;
    const svgEl = (tag, attrs, text) => {
        const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
        if (text !== undefined) node.textContent = text;
        return node;
    };

    function renderRows(panel, data, units, {loading = false} = {}) {
        const body = panel.querySelector('[data-forecast-rows]');
        body.replaceChildren();
        const base = panel.dataset.siteUrl;
        data.forecast.slots.forEach(point => {
            const row = document.createElement('tr');
            const time = document.createElement('th'); time.scope = 'row';
            const timeLink = document.createElement('a');
            timeLink.href = linkUrl(base, 'current', point.time);
            timeLink.textContent = hour(point.time, data.timezone);
            timeLink.setAttribute('aria-label', `${date(point.time, data.timezone)}, ${hour(point.time, data.timezone)} local. Open current chart`);
            time.appendChild(timeLink); row.appendChild(time);
            function cell(target, label, value, grade) {
                const td = document.createElement('td');
                const link = document.createElement('a'); link.href = linkUrl(base, target, point.time);
                if (loading) {
                    const skeleton = document.createElement('span');
                    skeleton.className = 'skeleton forecast-placeholder'; skeleton.setAttribute('aria-hidden', 'true');
                    link.appendChild(skeleton);
                } else link.textContent = value;
                link.setAttribute('aria-label', `${label}: ${loading ? 'loading' : value === '—' ? 'unavailable' : value}${!loading && grade ? `, ${grade[1]}` : ''}. ${hour(point.time, data.timezone)} local. Open ${target === 'conditions' ? 'site conditions' : target + ' chart'}`);
                if (!loading && grade) { link.dataset.grade = grade[0]; link.title = grade[1]; }
                td.appendChild(link); row.appendChild(td);
                return link;
            }
            cell('current', 'Current strength', valid(point.current_kn) ? `${tenth(point.current_kn)} kn` : '—', currentGrade(point.current_kn));
            cell('wind', 'Wind speed', valid(point.wind_speed_kn) ? `${tenth(point.wind_speed_kn)} kn` : '—', windGrade(point.wind_speed_kn));
            const heading = compass(point.wind_direction_deg);
            const direction = cell('wind', 'Wind from', heading?.label || '—');
            if (heading && !loading) {
                const arrow = svgEl('svg', {viewBox: '-9 -9 18 18', class: 'forecast-wind-marker', 'aria-hidden': 'true'});
                arrow.appendChild(svgEl('circle', {r: 7, class: 'marine-compass-ring'}));
                const needle = svgEl('g', {transform: `rotate(${(heading.degrees + 180) % 360})`});
                needle.appendChild(svgEl('path', {d: 'M0,-6 L3,2 L0,0 L-3,2 Z', class: 'marine-compass-head'}));
                needle.appendChild(svgEl('path', {d: 'M0,0 L0,5', class: 'marine-compass-tail'}));
                arrow.appendChild(needle); direction.appendChild(arrow);
                direction.title = `Wind from ${heading.label}; arrow points toward the direction of travel`;
            }
            const swellValid = valid(point.swell_height_m) && valid(point.swell_period_s) && (point.swell_height_m === 0 || point.swell_period_s > 0);
            const descriptor = typeof point.swell === 'string' ? point.swell : '';
            const swellGrade = swellValid && swellGrades[descriptor.toLowerCase()];
            const coupledGrade = swellGrade ? [swellGrade, descriptor] : null;
            cell('swell', 'Swell height', valid(point.swell_height_m)
                ? `${tenth(point.swell_height_m * (units.length === 'ft' ? 1 / .3048 : 1))} ${units.length}` : '—', coupledGrade);
            cell('swell', 'Swell period', valid(point.swell_period_s)
                ? `${Math.round(point.swell_period_s)}s` : '—', coupledGrade);
            cell('conditions', 'Water temperature', temperature(point.water_temperature_c, units.temperature));
            cell('conditions', 'Air temperature', temperature(point.air_temperature_c, units.temperature));
            body.appendChild(row);
        });
    }

    // Monotone cubic segments keep the hourly model smooth without overshooting turns.
    function tidePath(points) {
        if (points.length < 2) return '';
        const dx = points.slice(1).map((p, i) => p.x - points[i].x);
        const slopes = points.slice(1).map((p, i) => (p.y - points[i].y) / dx[i]);
        const tangents = points.map((_, i) => {
            if (!i) return slopes[0];
            if (i === points.length - 1) return slopes.at(-1);
            const a = slopes[i - 1], b = slopes[i];
            if (a * b <= 0) return 0;
            const w1 = 2 * dx[i] + dx[i - 1], w2 = dx[i] + 2 * dx[i - 1];
            return (w1 + w2) / (w1 / a + w2 / b);
        });
        return `M${points[0].x},${points[0].y}` + points.slice(1).map((p, i) => {
            const a = points[i], step = dx[i] / 3;
            return ` C${a.x + step},${a.y + tangents[i] * step} ${p.x - step},${p.y - tangents[i + 1] * step} ${p.x},${p.y}`;
        }).join('');
    }

    function renderTide(panel, data) {
        const host = panel.querySelector('[data-forecast-tide]'); host.replaceChildren();
        const points = data.forecast.tide || [];
        const values = points.map(point => point.value).filter(finite);
        if (!values.length) { host.textContent = 'Tide forecast unavailable'; return; }
        const width = Math.max(200, host.clientWidth), height = 180;
        const top = 48, bottom = 108;
        let min = Math.min(...values), max = Math.max(...values);
        if (min === max) { min -= .1; max += .1; }
        const x = stamp => (stamp - data.forecast.start) / (data.forecast.end - data.forecast.start) * width;
        const y = value => bottom - (value - min) / (max - min) * (bottom - top);
        const svg = svgEl('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `${date(data.forecast.start, data.timezone)} tide at ${panel.getAttribute('aria-label')}. High and low times are estimates interpolated from hourly model samples, in local time.`});
        const events = document.createElement('ul'); events.className = 'sr-only';
        svg.appendChild(svgEl('line', {x1: 0, x2: width, y1: bottom, y2: bottom, class: 'forecast-tide-guide'}));
        let segment = [];
        const flush = () => {
            if (segment.length > 1) {
                const path = tidePath(segment);
                svg.appendChild(svgEl('path', {d: `${path} L${segment.at(-1).x},${bottom} L${segment[0].x},${bottom} Z`, class: 'forecast-tide-fill'}));
                svg.appendChild(svgEl('path', {d: path, class: 'forecast-tide-line'}));
            }
            segment = [];
        };
        points.forEach((point, i) => {
            if (i && point.time - points[i - 1].time > 3600) flush();
            if (finite(point.value)) segment.push({x: x(point.time), y: y(point.value)}); else flush();
        }); flush();
        (data.forecast.extrema || []).filter(point => finite(point.value)).forEach(point => {
            const px = x(point.time), py = y(point.value);
            const high = point.kind === 'High';
            const labelX = Math.max(28, Math.min(width - 28, px));
            const tideTime = new Intl.DateTimeFormat('en-US', {timeZone: data.timezone, hour: 'numeric', minute: '2-digit', hour12: true})
                .format(Math.round(point.time / 60) * 60000).replace(/\s/g, '').toLowerCase();
            svg.appendChild(svgEl('line', {x1: labelX, x2: px, y1: high ? 37 : 120, y2: high ? py - 5 : py + 5, class: 'forecast-tide-connector'}));
            svg.appendChild(svgEl('circle', {cx: px, cy: py, r: 3.5, class: 'forecast-tide-point'}));
            svg.appendChild(svgEl('text', {x: labelX, y: high ? 13 : 134, 'text-anchor': 'middle', class: 'forecast-tide-label'}, point.kind));
            svg.appendChild(svgEl('text', {x: labelX, y: high ? 31 : 152, 'text-anchor': 'middle', class: 'forecast-tide-time'}, tideTime));
            const item = document.createElement('li'); item.textContent = `${point.kind} tide, approximately ${tideTime} local`; events.appendChild(item);
        });
        const ticks = [data.forecast.start, ...data.forecast.times.filter((_, i) => i > 0 && i % 2 === 0), data.forecast.end];
        for (const [i, stamp] of ticks.entries()) {
            const anchor = i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle';
            svg.appendChild(svgEl('text', {x: x(stamp), y: 176, 'text-anchor': anchor, class: 'forecast-tide-axis'}, hour(stamp, data.timezone)));
        }
        host.append(svg, events);
    }

    function initForecast() {
        const host = document.querySelector('[data-forecast]'); if (!host) return;
        const track = host.querySelector('[data-forecast-track]');
        const originals = [...track.querySelectorAll('[data-forecast-site]')]; if (!originals.length) return;
        const selectors = [...host.querySelectorAll('[data-forecast-select]')];
        const units = {length: host.dataset.lengthUnit, temperature: host.dataset.temperatureUnit};
        const count = originals.length;
        const cache = new Map(), pending = new Map();
        let stopped = false, refreshTimer, index = 0;
        let selectedDay = Math.max(0, Math.min(6, Number(window.history.state?.forecastDay) || 0));
        const saved = window.history.state?.forecastSite;
        index = Math.max(0, originals.findIndex(panel => panel.dataset.forecastSite === saved));
        const panels = originals;
        const matching = id => panels.filter(panel => panel.dataset.forecastSite === id);
        const status = (panel, text, retry = false) => {
            panel.querySelector('[data-forecast-status]').textContent = text;
            panel.querySelector('[data-forecast-feedback]').hidden = !text.includes('unavailable');
            panel.querySelector('[data-forecast-retry]').hidden = !retry;
        };
        function render(id, data) {
            const selected = data.forecast.days[selectedDay];
            const view = {...data, forecast: selected};
            matching(id).forEach(panel => {
                renderRows(panel, view, units); renderTide(panel, view);
                renderDates(panel, data.forecast.days);
                status(panel, 'Forecast ready');
                panel.setAttribute('aria-busy', 'false');
                panel.dataset.forecastState = 'ready';
            });
        }
        function renderDates(panel, days) {
            if (panel !== originals[index]) return;
            host.querySelectorAll('[data-forecast-day]').forEach((button, i) => {
                const day = days[i];
                if (!day) return;
                button.setAttribute('aria-pressed', String(i === selectedDay));
                button.setAttribute('aria-label', `${day.label}, ${day.month} ${day.day}`);
                button.querySelector('[data-calendar-month]').textContent = day.month;
                button.querySelector('[data-calendar-date]').textContent = day.day;
                button.querySelector('[data-calendar-label]').textContent = day.label;
            });
            const day = days[selectedDay];
            if (!day) return;
            panel.querySelector('.forecast-tide').href = linkUrl(panel.dataset.siteUrl, 'tide', day.start);
        }
        function placeholders(panel, loading = true) {
            const cached = cache.get(panel.dataset.forecastSite)?.data;
            const zone = cached?.timezone || panel.dataset.timezone;
            const days = cached?.forecast.days || JSON.parse(panel.dataset.days);
            renderDates(panel, days);
            if (!zone || !days[selectedDay]) return;
            renderRows(panel, {timezone: zone, forecast: {slots: days[selectedDay].times.map(time => ({time}))}}, units, {loading});
        }
        function showLoading(id) {
            matching(id).forEach(panel => {
                placeholders(panel);
                const skeleton = document.createElement('span');
                skeleton.className = 'skeleton forecast-tide-placeholder'; skeleton.setAttribute('aria-hidden', 'true');
                panel.querySelector('[data-forecast-tide]').replaceChildren(skeleton);
                panel.setAttribute('aria-busy', 'true'); panel.dataset.forecastState = 'loading';
                status(panel, 'Loading forecast');
            });
        }
        function unavailable(id, reason) {
            const cached = cache.get(id)?.data;
            if (cached) render(id, cached);
            matching(id).forEach(panel => {
                if (!cached) {
                    placeholders(panel, false);
                    panel.querySelectorAll('.skeleton').forEach(node => {node.className = ''; node.textContent = '—';});
                    panel.querySelector('[data-forecast-tide]').textContent = '—';
                }
                status(panel, 'Forecast unavailable', !['coordinates', 'not_ocean'].includes(reason));
                panel.setAttribute('aria-busy', 'false');
                panel.dataset.forecastState = 'unavailable';
            });
        }
        function load(panel, force = false) {
            const id = panel.dataset.forecastSite;
            if (pending.has(id) || stopped) return;
            const saved = cache.get(id);
            if (!force && saved && Date.now() - saved.loaded < 300000) return;
            if (panel.dataset.coordinates !== 'true') { unavailable(id, 'coordinates'); return; }
            const controller = new AbortController();
            const request = {controller, poll: null, deadline: null, skeleton: null, revealed: !saved}; pending.set(id, request);
            matching(id).forEach(p => {status(p, 'Loading forecast'); p.setAttribute('aria-busy', 'true');});
            if (!saved) showLoading(id);
            else request.skeleton = window.setTimeout(() => {request.revealed = true; showLoading(id);}, 160);
            const finish = () => {
                window.clearTimeout(request.poll); window.clearTimeout(request.deadline); window.clearTimeout(request.skeleton);
                if (pending.get(id) === request) pending.delete(id);
            };
            request.deadline = window.setTimeout(() => {controller.abort(); finish(); unavailable(id);}, 90000);
            async function fetchForecast() {
                try {
                    const response = await fetch(panel.dataset.url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
                        headers: {'X-Requested-With': 'fetch'}});
                    if (stopped || controller.signal.aborted) return;
                    if (response.status === 202) {request.poll = window.setTimeout(fetchForecast, 2000); return;}
                    if (!response.ok) throw new Error('Unavailable');
                    const data = await response.json();
                    if (stopped || controller.signal.aborted) return;
                    finish();
                    if (data.status !== 'complete') {unavailable(id, data.reason || data.status); return;}
                    if (!data.timezone || data.forecast?.days?.length !== 7 || data.forecast.days.some(day => day.slots?.length !== 8)) throw new Error('Incomplete forecast');
                    cache.set(id, {data, loaded: Date.now()}); render(id, data);
                } catch (_error) {
                    finish();
                    if (!stopped && !controller.signal.aborted) unavailable(id);
                }
            }
            fetchForecast();
        }
        function announce() {
            panels.forEach(panel => {
                const active = panel === originals[index]; panel.inert = !active; panel.hidden = !active;
                if (active) panel.removeAttribute('aria-hidden'); else panel.setAttribute('aria-hidden', 'true');
            });
            selectors.forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
            host.querySelector('[data-forecast-position]').textContent = `Site ${index + 1} of ${count}: ${originals[index].getAttribute('aria-label')}`;
            remember(); revealDay();
            const panel = originals[index], cached = cache.get(panel.dataset.forecastSite)?.data;
            if (cached && !pending.get(panel.dataset.forecastSite)?.revealed) render(panel.dataset.forecastSite, cached);
            if (!cached) placeholders(panel, panel.dataset.forecastState !== 'unavailable');
            load(panel);
        }
        function remember() {
            try {window.history.replaceState({...window.history.state, forecastSite: originals[index].dataset.forecastSite, forecastDay: selectedDay}, '');} catch (_error) { /* Preserve navigation if history writes are throttled. */ }
        }
        function revealDay() {
            const rail = host.querySelector('.forecast-dates');
            const button = rail.querySelector(`[data-forecast-day="${selectedDay}"]`);
            const area = rail.getBoundingClientRect(), target = button.getBoundingClientRect();
            if (target.left < area.left) rail.scrollLeft -= area.left - target.left;
            if (target.right > area.right) rail.scrollLeft += target.right - area.right;
        }
        function selectDay(next) {
            selectedDay = next; remember();
            new Set(panels.map(panel => panel.dataset.forecastSite)).forEach(id => {
                const cached = cache.get(id)?.data;
                if (pending.get(id)?.revealed || !cached) {
                    matching(id).forEach(panel => placeholders(panel, panel.dataset.forecastState !== 'unavailable'));
                } else render(id, cached);
            });
        }
        function goTo(next) {
            index = Math.max(0, Math.min(count - 1, next)); announce();
        }
        host.addEventListener('click', event => {
            const selector = event.target.closest('[data-forecast-select]'); if (selector) goTo(Number(selector.dataset.forecastSelect));
            if (event.target.closest('[data-forecast-retry]')) load(event.target.closest('[data-forecast-site]'), true);
            const dayButton = event.target.closest('[data-forecast-day]');
            if (dayButton) {
                selectDay(Number(dayButton.dataset.forecastDay));
                revealDay();
            }
        });
        host.addEventListener('keydown', event => {
            if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest('.forecast-table-scroll')) return;
            const dayButton = event.target.closest('[data-forecast-day]');
            if (dayButton) {
                const next = {ArrowLeft: selectedDay - 1, ArrowRight: selectedDay + 1, Home: 0, End: 6}[event.key];
                if (next === undefined) return;
                event.preventDefault(); selectDay(Math.max(0, Math.min(6, next)));
                const button = host.querySelector(`[data-forecast-day="${selectedDay}"]`);
                button.focus({preventScroll: true});
                revealDay(); return;
            }
            if (!event.target.closest('[data-forecast-select]')) return;
            const next = {ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: count - 1}[event.key];
            if (next === undefined) return;
            event.preventDefault(); goTo(next); selectors[index]?.focus({preventScroll: true});
        });
        const tideResize = new ResizeObserver(() => {
            const panel = originals[index], data = cache.get(panel.dataset.forecastSite)?.data;
            if (data && !pending.get(panel.dataset.forecastSite)?.revealed) renderTide(panel, {...data, forecast: data.forecast.days[selectedDay]});
        });
        panels.forEach(panel => tideResize.observe(panel.querySelector('[data-forecast-tide]')));
        function tick() {
            if (stopped) return;
            if (!document.hidden) load(originals[index]);
            refreshTimer = window.setTimeout(tick, 30000);
        }
        window.addEventListener('pagehide', () => {
            stopped = true; window.clearTimeout(refreshTimer);
            pending.forEach(request => {request.controller.abort(); window.clearTimeout(request.poll); window.clearTimeout(request.deadline); window.clearTimeout(request.skeleton);}); pending.clear();
            cache.forEach(({data}, id) => render(id, data));
        });
        window.addEventListener('pageshow', event => {if (event.persisted) {stopped = false; announce(); tick();}});
        window.addEventListener('online', () => {if (!stopped) load(originals[index], true);});
        document.addEventListener('visibilitychange', () => {if (!document.hidden && !stopped) load(originals[index]);});
        panels.forEach(placeholders);
        announce(); tick();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initForecast); else initForecast();
    if (typeof module !== 'undefined') module.exports = {currentGrade, windGrade, compass, temperature, hour, linkUrl, renderRows, renderTide, tidePath};
})();
