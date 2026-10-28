/* Marine forecasts use Unix timestamps; labels always use the site's timezone. */
(() => {
    const finite = value => typeof value === 'number' && Number.isFinite(value);
    const svgNS = 'http://www.w3.org/2000/svg';
    const el = (tag, attributes = {}, text) => {
        const node = document.createElementNS(svgNS, tag);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        if (text !== undefined) node.textContent = text;
        return node;
    };
    const localDate = (time, zone) => new Intl.DateTimeFormat('en-US', {
        timeZone: zone, month: 'short', day: 'numeric',
    }).format(new Date(time * 1000));
    const localHour = (time, zone) => new Intl.DateTimeFormat('en-US', {
        timeZone: zone, hour: 'numeric', hour12: true,
    }).format(new Date(time * 1000)).replace(/\s/g, '').toLowerCase();
    const hourNumber = (time, zone) => Number(new Intl.DateTimeFormat('en-GB', {
        timeZone: zone, hour: 'numeric', hourCycle: 'h23',
    }).format(new Date(time * 1000)));
    const compassPoints = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const compassHeading = degrees => {
        if (!finite(degrees) || degrees < 0 || degrees > 360) return null;
        const index = Math.round(degrees / 22.5) % 16;
        return { label: compassPoints[index], degrees: index * 22.5 };
    };
    function moonMarker(phase, x) {
        const marker = el('g', { transform: `translate(${x} 12)`, class: 'marine-moon-marker', role: 'img', 'aria-label': `${phase} moon` });
        marker.appendChild(el('title', {}, `${phase} moon`));
        marker.appendChild(el('circle', { r: 6, class: 'marine-moon-disc' }));
        if (phase === 'Full') marker.appendChild(el('circle', { r: 6, class: 'marine-moon-light' }));
        if (phase === 'First Quarter' || phase === 'Last Quarter') {
            marker.appendChild(el('path', { d: `M0,-6 A6,6 0 0,${phase === 'First Quarter' ? 1 : 0} 0,6 Z`, class: 'marine-moon-light' }));
        }
        marker.appendChild(el('circle', { r: 6, class: 'marine-moon-outline' }));
        return marker;
    }
    function windMarker(heading, x) {
        const marker = el('g', { transform: `translate(${x} 12)`, class: 'marine-wind-marker', role: 'img', 'aria-label': `Wind from ${heading.label}` });
        marker.appendChild(el('title', {}, `Wind from ${heading.label} (${heading.degrees}°)`));
        marker.appendChild(el('circle', { r: 7, class: 'marine-compass-ring' }));
        const needle = el('g', { transform: `rotate(${heading.degrees})` });
        needle.appendChild(el('path', { d: 'M0,-6 L3,2 L0,0 L-3,2 Z', class: 'marine-compass-head' }));
        needle.appendChild(el('path', { d: 'M0,0 L0,5', class: 'marine-compass-tail' }));
        marker.appendChild(needle);
        return marker;
    }

    function renderChart(host, points, { tide = false, wind = false, daily = false, zone, lengthUnit = 'm', moons = [] }) {
        points = points || [];
        host.replaceChildren();
        if (!points.some(p => finite(p.value))) {
            const empty = document.createElement('p');
            empty.className = 'muted'; empty.textContent = 'Forecast unavailable'; host.appendChild(empty);
            return;
        }
        const left = 80, top = 32, bottom = 168;
        const name = tide ? 'Tide level' : wind ? 'Wind speed' : 'Current strength';
        const width = Math.max(daily ? 240 : tide ? 650 : 900, host.clientWidth || 550), height = 220;
        const values = points.map(p => p.value).filter(finite);
        let min = tide ? Math.min(...values) : 0;
        let max = tide ? Math.max(...values) : Math.max(2.5, Math.ceil(Math.max(...values) * 2) / 2);
        // A numeric wind scale shares the current chart's bar layout and fixed axis.
        const windStep = Math.max(...values) <= 8 ? 2 : Math.max(...values) <= 20 ? 5 : Math.max(...values) <= 40 ? 10 : Math.ceil(Math.max(...values) / 40) * 10;
        if (wind) max = windStep * 4;
        if (min === max) { min -= .05; max += .05; }
        const y = value => bottom - (value - min) / (max - min) * (bottom - top);
        const x = i => left + (i + .5) * (width - left - 22) / points.length;
        // Keep the Y axis visible while hourly data scrolls on narrow screens.
        const axis = el('svg', { viewBox: `0 0 ${left} ${height}`, class: 'marine-y-axis', 'aria-hidden': 'true' });
        const scroll = document.createElement('div'); scroll.className = 'marine-chart-scroll';
        scroll.tabIndex = 0;
        scroll.setAttribute('role', 'region');
        scroll.setAttribute('aria-label', `${name} forecast; scroll for more hours`);
        const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, width, height,
            role: 'img', 'aria-label': `${name} forecast in ${zone}. ${daily ? 'Daily maximum values.' : 'Hourly values.'}${wind ? ' Arrows indicate where the wind comes from, rounded to 16 compass points.' : ''}` });
        const readout = document.createElement('div'); readout.className = 'sr-only';
        readout.setAttribute('role', 'status');
        const readoutDate = document.createElement('span');
        const readoutValue = document.createElement('strong'); readout.append(readoutDate, readoutValue);
        const marks = [];
        const cursor = el('line', { y1: top, y2: bottom, class: 'marine-cursor' });
        const ticks = tide ? [{ value: min, label: 'Low' }, { value: max, label: 'High' }]
            : wind ? [0, 1, 2, 3, 4].map(i => ({ value: i * windStep, label: `${i * windStep} kn` }))
            : [{ value: .25, label: 'Light' }, { value: .75, label: 'Moderate' }, { value: 1.5, label: 'Strong' }, { value: 2.25, label: 'Very Strong' }];
        ticks.forEach(tick => {
            axis.appendChild(el('text', { x: left - 10, y: y(tick.value) + 4, 'text-anchor': 'end' }, tick.label));
        });
        (tide ? [min, max] : wind ? [windStep, windStep * 2, windStep * 3, max] : [.5, 1, 2]).forEach(value => {
            svg.appendChild(el('line', { x1: left, x2: width - 22, y1: y(value), y2: y(value), class: 'marine-guide' }));
        });
        svg.appendChild(el('line', { x1: left, x2: width - 22, y1: bottom, y2: bottom, class: 'marine-baseline' }));
        const valueLabel = value => tide
            ? `${(value * (lengthUnit === 'ft' ? 1 / .3048 : 1)).toFixed(2)} ${lengthUnit} above global mean sea level`
            : `${value.toFixed(2)} knots`;
        const moonLookup = new Map(moons.map(point => [point.time, point.phase]));
        const contextLabel = point => {
            const heading = wind && compassHeading(point.direction_deg);
            const phase = daily && !wind && !tide && moonLookup.get(point.time);
            return heading ? `; wind from ${heading.label}` : phase ? `; ${phase} moon` : '';
        };
        points.forEach((point, i) => {
            if (wind) {
                const heading = compassHeading(point.direction_deg);
                if (heading) svg.appendChild(windMarker(heading, x(i)));
            } else if (daily && !tide && moonLookup.get(point.time)) {
                svg.appendChild(moonMarker(moonLookup.get(point.time), x(i)));
            }
        });
        let segment = [];
        const flush = () => {
            if (segment.length > 1) svg.appendChild(el('polyline', { points: segment.join(' '), class: 'marine-tide-line' }));
            segment = [];
        };
        points.forEach((point, i) => {
            if (!finite(point.value)) { flush(); return; }
            const title = `${localDate(point.time, zone)}${daily ? ', daily maximum' : ', ' + localHour(point.time, zone)}: ${valueLabel(point.value)}${contextLabel(point)}`;
            let mark;
            if (tide) {
                segment.push(`${x(i)},${y(point.value)}`);
                return;
            } else {
                const barWidth = Math.min(daily ? 34 : 20, (width - left - 22) / points.length * .65);
                mark = el('rect', { x: x(i) - barWidth / 2, y: y(point.value), width: barWidth,
                    height: Math.max(1, bottom - y(point.value)), rx: 3, class: 'marine-current-bar', 'aria-label': title });
            }
            marks.push({ mark, index: i });
            mark.appendChild(el('title', {}, title)); svg.appendChild(mark);
        });
        flush();
        points.forEach((point, i) => {
            const hour = hourNumber(point.time, zone);
            if (daily || hour % 3 === 0) {
                svg.appendChild(el('text', { x: x(i), y: bottom + 25, 'text-anchor': 'middle' }, daily ? (width < 550 ? new Intl.DateTimeFormat('en-US', { timeZone: zone, day: 'numeric' }).format(new Date(point.time * 1000)) : localDate(point.time, zone)) : localHour(point.time, zone)));
                if ((daily && width < 550 && (i === 0 || new Intl.DateTimeFormat('en-US', { timeZone: zone, day: 'numeric' }).format(new Date(point.time * 1000)) === '1')) || (!daily && (hour === 0 || i === 0))) svg.appendChild(el('text', { x: x(i), y: bottom + 45, 'text-anchor': 'middle' }, daily ? new Intl.DateTimeFormat('en-US', { timeZone: zone, month: 'short' }).format(new Date(point.time * 1000)) : localDate(point.time, zone)));
            }
        });
        if (!tide) svg.appendChild(cursor);
        let selected = Math.min(Number(host.dataset.selectedIndex) || 0, points.length - 1);
        function select(index, reveal = false) {
            selected = Math.max(0, Math.min(points.length - 1, index));
            host.dataset.selectedIndex = String(selected);
            const point = points[selected];
            readoutDate.textContent = `${localDate(point.time, zone)} · ${daily ? 'Daily max' : localHour(point.time, zone)}`;
            readoutValue.textContent = finite(point.value) ? (tide
                ? `${(point.value * (lengthUnit === 'ft' ? 1 / .3048 : 1)).toFixed(2)} ${lengthUnit}`
                : `${Number(point.value.toFixed(2))} kn`) : '—';
            readoutValue.textContent += contextLabel(point);
            cursor.setAttribute('x1', x(selected)); cursor.setAttribute('x2', x(selected));
            marks.forEach(({ mark, index }) => {
                mark.setAttribute('data-selected', String(index === selected));
            });
            if (reveal && typeof scroll.scrollTo === 'function') {
                const position = x(selected) - left - (scroll.clientWidth - left) / 2;
                scroll.scrollTo({ left: Math.max(0, position), behavior: 'auto' });
            }
        }
        const inspect = event => {
            if (event.type === 'pointermove' && event.pointerType !== 'mouse') return;
            const bounds = svg.getBoundingClientRect();
            const position = (event.clientX - bounds.left) * width / bounds.width;
            select(Math.round((position - left) / (width - left - 22) * points.length - .5));
        };
        svg.addEventListener('pointerdown', inspect);
        svg.addEventListener('pointermove', inspect);
        scroll.addEventListener('keydown', event => {
            const index = { ArrowLeft: selected - 1, ArrowRight: selected + 1, Home: 0, End: points.length - 1 }[event.key];
            if (index === undefined) return;
            event.preventDefault(); select(index, true);
        });
        scroll.setAttribute('aria-label', `${name} forecast. Use left and right arrow keys to inspect values.`);
        readout.title = tide ? 'Height above global mean sea level' : wind ? 'Wind speed in knots and source direction' : 'Current velocity in knots';
        const list = document.createElement('ul'); list.className = 'sr-only';
        points.forEach(point => {
            const item = document.createElement('li');
            item.textContent = `${localDate(point.time, zone)} ${daily ? 'Daily maximum' : localHour(point.time, zone)}: ${finite(point.value) ? valueLabel(point.value) : 'Unavailable'}${contextLabel(point)}`;
            list.appendChild(item);
        });
        select(selected);
        scroll.appendChild(svg); host.append(axis, scroll, readout, list);
        const edge = () => host.setAttribute('data-can-scroll', String(scroll.scrollWidth > scroll.clientWidth + scroll.scrollLeft + 2));
        scroll.addEventListener('scroll', edge, { passive: true });
        edge();
    }

    function initMarine() {
        const host = document.querySelector('[data-marine-forecast]');
        if (!host) return;
        const status = host.querySelector('[data-marine-status]');
        const retry = host.querySelector('[data-marine-retry]');
        const source = host.querySelector('[data-marine-source]');
        const equipment = host.querySelector('[data-equipment-advice]');
        const exposureAdvice = host.querySelector('[data-exposure-advice]');
        const exposureName = host.querySelector('[data-exposure-name]');
        const weightAsterisk = host.querySelector('[data-weight-asterisk]');
        const exposureAsterisk = host.querySelector('[data-exposure-asterisk]');
        const exposureHistory = host.querySelector('[data-exposure-history]');
        const exposureHistoryLink = host.querySelector('[data-exposure-history-link]');
        const weightAdvice = host.querySelector('[data-weight-advice]');
        const weightCaveat = host.querySelector('[data-weight-caveat]');
        const values = [...host.querySelectorAll('[data-marine-value]')];
        const currentChart = host.querySelector('[data-marine-chart="current"]');
        const tideChart = host.querySelector('[data-marine-chart="tide"]');
        const windChart = host.querySelector('[data-marine-chart="wind"]');
        const chartNodes = [currentChart, tideChart, windChart].filter(Boolean);
        const buttons = [...host.querySelectorAll('[data-marine-range]')];
        let result, range = 'daily', windRange = 'daily', controller, deadline, poll, ends = [], stopped = false, generation = 0;
        const finish = () => { ends.forEach(end => end()); ends = []; };
        const clear = () => { window.clearTimeout(poll); window.clearTimeout(deadline); finish(); };
        const charts = (target) => {
            if (!target || target === 'current') renderChart(currentChart, result.charts[range === 'daily' ? 'current_daily' : 'current_hourly'], { daily: range === 'daily', zone: result.timezone, moons: result.charts.moon_phase_daily || [] });
            if (!target) renderChart(tideChart, result.charts.tide_hourly, { tide: true, zone: result.timezone, lengthUnit: host.dataset.lengthUnit });
            if (windChart && (!target || target === 'wind')) {
                const points = windRange === 'daily' ? result.charts.wind_daily : result.charts.wind_hourly?.map(point => ({ ...point, value: point.speed_kn }));
                renderChart(windChart, points, { wind: true, daily: windRange === 'daily', zone: result.timezone });
            }
        };
        const unavailable = (noCoordinates = false) => {
            clear(); result = null;
            if (equipment) equipment.hidden = true;
            values.forEach(node => { node.textContent = '-'; node.removeAttribute('title'); });
            chartNodes.forEach(node => { node.replaceChildren(); const p = document.createElement('p'); p.className = 'muted'; p.textContent = 'Forecast unavailable'; node.appendChild(p); });
            status.textContent = 'Forecast unavailable';
            retry.hidden = noCoordinates;
            buttons.forEach(button => { button.disabled = true; });
        };
        const notOcean = () => {
            clear(); result = null;
            if (equipment) equipment.hidden = true;
            values.forEach(node => { node.textContent = '-'; node.removeAttribute('title'); });
            const messages = [
                'Current strength is only available for ocean dive sites',
                'Tide level is only available for ocean dive sites',
                'Wind forecast is only available for ocean dive sites',
            ];
            chartNodes.forEach((node, index) => {
                node.replaceChildren();
                const message = document.createElement('p');
                message.className = 'muted';
                message.textContent = messages[index];
                node.appendChild(message);
            });
            status.textContent = 'Marine forecast unavailable for non-ocean dive sites';
            retry.hidden = true;
            if (source) source.hidden = true;
            buttons.forEach(button => { button.disabled = true; });
        };
        async function requestForecast(ticket = generation) {
            try {
                const response = await fetch(host.dataset.url, { credentials: 'same-origin', cache: 'no-store',
                    headers: { 'X-Requested-With': 'fetch' }, signal: controller.signal });
                if (stopped || ticket !== generation) return;
                if (response.status === 202) { poll = window.setTimeout(() => requestForecast(ticket), 2000); return; }
                if (!response.ok) throw new Error('Unavailable');
                const data = await response.json();
                if (stopped || ticket !== generation) return;
                if (data.status === 'not_ocean') { notOcean(); return; }
                if (data.status !== 'complete') { unavailable(data.reason === 'coordinates'); return; }
                if (!data.charts || !data.current) throw new Error('Incomplete');
                result = data; clear();
                const current = data.current;
                const advice = data.recommendations;
                if (equipment) {
                    equipment.hidden = !advice?.exposure;
                    if (advice?.exposure) {
                        exposureName.textContent = advice.exposure;
                        const hasHistory = Number.isInteger(advice.source_dive_id) && advice.source_dive_id > 0 && !!advice.source_dive_url;
                        exposureAsterisk.hidden = !hasHistory;
                        exposureHistory.hidden = !hasHistory;
                        if (hasHistory) exposureHistoryLink.setAttribute('href', advice.source_dive_url);
                        else exposureHistoryLink.removeAttribute('href');
                        exposureAdvice.title = hasHistory ? 'Based on your temperature feedback from logged dives' : 'Based on water temperature';
                        weightAdvice.textContent = advice.weight || '-';
                        weightAsterisk.hidden = !advice.weight;
                        weightCaveat.hidden = !advice.weight;
                    }
                }
                values.forEach(node => {
                    if (node.dataset.marineValue === 'tide') node.textContent = current.tide || '-';
                    if (node.dataset.marineValue === 'moon') {
                        node.textContent = current.moon_phase || '-';
                        node.title = 'Nearest major moon phase for today at this dive site';
                    }
                    if (node.dataset.marineValue === 'swell') {
                        const unit = host.dataset.lengthUnit === 'ft' ? 'ft' : 'm';
                        const height = current.swell_height_m * (unit === 'ft' ? 1 / .3048 : 1);
                        node.textContent = finite(current.swell_height_m) ? `${Number(height.toFixed(1))} ${unit}` : '-';
                    }
                    if (node.dataset.marineValue === 'temperature') {
                        const fahrenheit = host.dataset.temperatureUnit === 'f';
                        node.textContent = finite(current.temperature_c) ? `${Math.round(fahrenheit ? current.temperature_c * 9 / 5 + 32 : current.temperature_c)}°${fahrenheit ? 'F' : 'C'}` : '-';
                    }
                });
                buttons.forEach(button => { button.disabled = false; });
                const timestamps = Object.values(current.timestamps).filter(finite);
                const timestamp = timestamps.length ? Math.min(...timestamps) : data.fetched_at;
                status.textContent = `Forecast · ${localDate(timestamp, data.timezone)}, ${new Intl.DateTimeFormat('en-US', { timeZone: data.timezone, hour: 'numeric', minute: '2-digit' }).format(new Date(timestamp * 1000)).replace(/\s/g, '').toLowerCase()} local`;
                status.title = `Site timezone: ${data.timezone}. Modeled surface conditions.`;
                retry.hidden = true; charts();
            } catch (_error) { if (!stopped && ticket === generation) unavailable(); }
        }
        function load() {
            generation++; clear(); controller?.abort(); controller = new AbortController(); stopped = false;
            status.textContent = 'Updating forecast…';
            if (source) source.hidden = false;
            if (equipment) equipment.hidden = true; retry.hidden = true;
            buttons.forEach(button => { button.disabled = true; });
            const line = '<span class="skeleton skeleton-line"></span>';
            const chart = '<span class="skeleton skeleton-chart"></span>';
            ends = [...values, ...chartNodes].map(node => window.PelagiaLoading?.begin(node, 'Loading marine forecast', node.matches('[data-marine-chart]') ? chart : line) || (() => {}));
            deadline = window.setTimeout(() => { generation++; controller.abort(); unavailable(); }, 20000);
            requestForecast();
        }
        buttons.forEach(button => button.addEventListener('click', () => {
            if (!result) return;
            const target = button.dataset.marineTarget || 'current';
            if (target === 'wind') { windRange = button.dataset.marineRange; windChart.dataset.selectedIndex = '0'; }
            else { range = button.dataset.marineRange; currentChart.dataset.selectedIndex = '0'; }
            buttons.filter(item => (item.dataset.marineTarget || 'current') === target)
                .forEach(item => item.setAttribute('aria-pressed', String(item === button)));
            charts(target);
        }));
        retry.addEventListener('click', load);
        let chartWidth = host.clientWidth;
        window.addEventListener('resize', () => {
            if (host.clientWidth === chartWidth) return;
            chartWidth = host.clientWidth;
            if (result && !stopped) charts();
        });
        window.addEventListener('pagehide', () => { generation++; stopped = true; controller?.abort(); clear(); });
        window.addEventListener('pageshow', event => { if (event.persisted && host.dataset.coordinates === 'true') load(); });
        if (host.dataset.coordinates === 'true') load(); else unavailable(true);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initMarine);
    else initMarine();
    if (typeof module !== 'undefined') module.exports = { renderChart, localDate, localHour, hourNumber, compassHeading };
})();
