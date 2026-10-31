const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
function node(tag = 'div') {
    return {tag, dataset: {}, attrs: {}, children: [], handlers: {},
        appendChild(child) { this.children.push(child); return child; },
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
        addEventListener(k, v) { const prior=this.handlers[k]; this.handlers[k] = prior ? (...args) => { prior(...args); v(...args); } : v; },
        matches(s) { return this.dataset.chart && s.includes('marine-chart'); },
    };
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function setup(coordinates = 'true', visibility = false) {
    const equipment=node(), exposureAdvice=node(), exposureName=node(), weightAsterisk=node(), exposureAsterisk=node(), exposureHistory=node(), exposureHistoryLink=node(), weightAdvice=node(), weightCaveat=node(), source=node();
    const host = node(), status = node(), retry = node(), charts = [node(), node(), node(), node()], values = ['temperature', 'tide', 'moon', 'wind'].map(v => { const n = node(); n.dataset.marineValue = v; return n; });
    const visibilityChart=node(), visibilityValue=node(), visibilityStatus=node(), visibilityRetry=node(), visibilityDate=node();
    charts.forEach(n => { n.dataset.chart = true; });
    const buttons = ['daily', 'hourly', 'daily', 'hourly'].map((v, i) => { const n = node(); n.dataset.marineRange = v; if (i > 1) n.dataset.marineTarget = 'wind'; return n; });
    host.dataset = {coordinates, url: '/api/dive-sites/1/conditions', temperatureUnit: 'f', lengthUnit: 'ft'};
    if (visibility) Object.assign(host.dataset,{visibilityMonthlyUrl:'/monthly',visibilityDailyUrl:'/daily'});
    host.querySelector = s => ({'[data-visibility-chart]':visibility ? visibilityChart : null,'[data-visibility-value]':visibilityValue,'[data-visibility-status]':visibilityStatus,'[data-visibility-retry]':visibilityRetry,'[data-visibility-date]':visibilityDate,'[data-equipment-advice]':equipment,'[data-exposure-advice]':exposureAdvice,'[data-exposure-name]':exposureName,'[data-weight-asterisk]':weightAsterisk,'[data-exposure-asterisk]':exposureAsterisk,'[data-exposure-history]':exposureHistory,'[data-exposure-history-link]':exposureHistoryLink,'[data-weight-advice]':weightAdvice,'[data-weight-caveat]':weightCaveat,'[data-marine-status]':status,'[data-marine-retry]':retry,'[data-marine-source]':source,'[data-marine-chart="current"]':charts[0],'[data-marine-chart="tide"]':charts[1],'[data-marine-chart="wind"]':charts[2],'[data-marine-chart="rainfall"]':charts[3]})[s];
    host.querySelectorAll = s => s.includes('value') ? values : buttons;
    const window = node(); let id = 0; const timers = new Map(); const requests = []; let ended = 0;
    window.setTimeout = (fn, delay) => { timers.set(++id, {fn, delay}); return id; }; window.clearTimeout = n => timers.delete(n);
    window.PelagiaLoading = {begin: () => () => { ended++; }};
    const document = {readyState: 'complete', querySelector: () => host, createElement: node, createElementNS: (_, tag) => node(tag)};
    const context = vm.createContext({window, document, Intl, Date, AbortController, module: {exports: {}}, fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}))});
    vm.runInContext(fs.readFileSync('pelagia/static/js/marine.js', 'utf8'), context);
    return {visibilityChart,visibilityValue,visibilityStatus,visibilityRetry,visibilityDate,equipment,exposureAdvice,exposureName,weightAsterisk,exposureAsterisk,exposureHistory,exposureHistoryLink,weightAdvice,weightCaveat,source,host, status, retry, charts, values, buttons, window, timers, requests, context, ended: () => ended};
}
function data() {
    const points = Array.from({length: 48}, (_, i) => ({time:1792940400 + i * 3600, value: .5}));
    return {status:'complete', timezone:'Pacific/Galapagos', fetched_at:1792940400,
        current:{strength:'Moderate', temperature_c:28.3, tide:'Rising', velocity_kn:.5, wind_speed_kn:12.3, moon_phase:'Full', timestamps:{ocean_current_velocity:1792940400}},
        charts:{current_daily:points.slice(0,7), current_hourly:points, tide_hourly:points.slice(0,24),
            rainfall_monthly:Array.from({length:12},(_,i)=>({time:Date.UTC(2025,9+i,1,12)/1000,value:40+i*5})),
            moon_phase_daily:[{time:points[0].time,phase:'Full'}],
            wind_daily:points.slice(0,7).map(p=>({...p,value:12,direction_deg:350})),
            wind_hourly:points.map(p=>({time:p.time,speed_kn:10,direction_deg:225}))}};
}
test('forecast renders Fahrenheit, accessible charts, and range toggle without another request', async () => {
    const s = setup(); s.requests[0].resolve({status:200,ok:true,json:async()=>data()}); await flush();
    assert.equal(s.values[0].textContent,'83°F'); assert.equal(s.values[1].textContent,'Rising');
    assert.equal(s.ended(),8); assert.equal(s.timers.size,0); assert.equal(s.retry.hidden,true);
    s.buttons[1].handlers.click(); assert.equal(s.requests.length,1); assert.equal(s.buttons[1].attrs['aria-pressed'],'true');
    assert.equal(s.charts[0].children[1].children[0].children.filter(n=>n.tag==='rect').length,24);
});
test('failure stops loading and retry issues one new request', async () => {
    const s=setup();s.requests[0].reject(new Error());await flush();
    assert.equal(s.status.textContent,'Forecast unavailable');assert.equal(s.retry.hidden,false);assert.equal(s.ended(),8);
    s.retry.handlers.click();assert.equal(s.requests.length,2);
});
test('non-ocean sites show availability messages without charts or retry', async () => {
    const s=setup();
    s.requests[0].resolve({status:200,ok:true,json:async()=>({status:'not_ocean',feature:'LAND'})});await flush();
    assert.equal(s.charts[0].children[0].textContent,'Current strength is only available for ocean dive sites');
    assert.equal(s.charts[1].children[0].textContent,'Tide level is only available for ocean dive sites');
    assert.equal(s.charts[0].children.length,1);assert.equal(s.charts[1].children.length,1);
    assert.equal(s.charts[2].children[0].textContent,'Wind forecast is only available for ocean dive sites');
    assert.equal(s.charts[3].children[0].textContent,'Rainfall history is only available for ocean dive sites');
    assert.equal(s.retry.hidden,true);assert.equal(s.source.hidden,true);assert.equal(s.ended(),8);
});
test('missing coordinates never fetch; leaving page aborts and cancels timers', () => {
    const missing=setup('false');assert.equal(missing.requests.length,0);assert.equal(missing.retry.hidden,true);
    const s=setup();s.window.handlers.pagehide();assert.equal(s.requests[0].options.signal.aborted,true);assert.equal(s.timers.size,0);assert.equal(s.ended(),8);
});
test('pending response polls; deadline aborts requests', async () => {
    const s=setup();s.requests[0].resolve({status:202});await flush();
    const poll=[...s.timers.values()].find(t=>t.delay===2000);assert.ok(poll);poll.fn();assert.equal(s.requests.length,2);
    [...s.timers.values()].find(t=>t.delay===30000).fn();assert.equal(s.requests[1].options.signal.aborted,true);
    assert.equal(s.status.textContent,'Forecast unavailable');
});
test('site-local labels include 12am and handle DST hours', () => {
    const s=setup('false'), api=s.context.module.exports;
    assert.equal(api.localHour(Date.parse('2026-10-25T06:00:00Z')/1000,'Pacific/Galapagos'),'12am');
    assert.equal(api.hourNumber(Date.parse('2026-11-01T06:00:00Z')/1000,'America/New_York'),1);
});
test('moon and wind fields render knots for both unit preferences, including zero and missing data', async () => {
    const imperial=setup();imperial.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    assert.equal(imperial.values[2].textContent,'Full');assert.equal(imperial.values[3].textContent,'12.3 kn');
    const metric=setup();metric.host.dataset.lengthUnit='m';
    const d=data();d.current.wind_speed_kn=8.76;d.current.moon_phase='Last Quarter';
    metric.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    assert.equal(metric.values[3].textContent,'8.8 kn');assert.equal(metric.values[2].textContent,'Last Quarter');
    const zero=setup();zero.requests[0].resolve({status:200,ok:true,json:async()=>({...data(),current:{...data().current,wind_speed_kn:0,moon_phase:null}})});await flush();
    assert.equal(zero.values[3].textContent,'0 kn');assert.equal(zero.values[2].textContent,'-');
    const missing=setup();missing.requests[0].resolve({status:200,ok:true,json:async()=>({...data(),current:{...data().current,wind_speed_kn:null}})});await flush();
    assert.equal(missing.values[3].textContent,'-');
});
test('moon markers align only with qualifying daily current bars and vanish in hourly view', async () => {
    const s=setup();s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const svg=s.charts[0].children[1].children[0];
    const moons=svg.children.filter(n=>n.attrs.class==='marine-moon-marker');
    assert.equal(moons.length,1);assert.equal(moons[0].attrs['aria-label'],'Full moon');
    const firstBar=svg.children.find(n=>n.tag==='rect');
    assert.ok(moons[0].attrs.transform.includes(String(Number(firstBar.attrs.x)+Number(firstBar.attrs.width)/2)));
    s.buttons[1].handlers.click();
    assert.equal(s.charts[0].children[1].children[0].children.filter(n=>n.attrs.class==='marine-moon-marker').length,0);
});
test('wind chart uses numeric knots and independently toggles daily and hourly arrows', async () => {
    const s=setup();s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const chart=s.charts[2];
    assert.ok(chart.children[0].children.every(n=>n.textContent.endsWith(' kn')));
    let svg=chart.children[1].children[0];
    assert.equal(svg.children.filter(n=>n.tag==='rect').length,7);
    let markers=svg.children.filter(n=>n.attrs.class==='marine-wind-marker');
    assert.equal(markers.length,7);
    assert.equal(markers[0].attrs['aria-label'],'Wind toward S');
    assert.equal(markers[0].children[2].attrs.transform,'rotate(180)');
    assert.equal(chart.children[2].children[1].textContent,'12 kn; wind from N');
    s.buttons[3].handlers.click();svg=chart.children[1].children[0];
    assert.equal(svg.children.filter(n=>n.tag==='rect').length,24);
    markers=svg.children.filter(n=>n.attrs.class==='marine-wind-marker');
    assert.equal(markers.length,24);
    assert.equal(markers[0].attrs['aria-label'],'Wind toward NE');
    assert.equal(markers[0].children[2].attrs.transform,'rotate(45)');
    assert.equal(chart.children[2].children[1].textContent,'10 kn; wind from SW');
    assert.equal(s.buttons[2].attrs['aria-pressed'],'false');assert.equal(s.buttons[3].attrs['aria-pressed'],'true');
    assert.equal(s.charts[0].children[1].children[0].children.filter(n=>n.tag==='rect').length,7);
    assert.equal(s.requests.length,1);
});
test('compass headings snap to 16 points and preserve north across wraparound', () => {
    const api=setup('false').context.module.exports;
    for (const [degrees,label] of [[0,'N'],[360,'N'],[359,'N'],[337.5,'NNW'],[315,'NW'],[22.5,'NNE'],[180,'S']]) {
        assert.equal(api.compassHeading(degrees).label,label);
    }
    assert.equal(api.compassHeading(null),null);assert.equal(api.compassHeading(-1),null);
    assert.equal(api.windHeading(0).label,'S');assert.equal(api.windHeading(225).label,'NE');
    assert.equal(api.windHeading(null),null);
});
test('chart inspection works with arrow keys, preserves selection on resize, and exposes exact values', async () => {
    const s=setup();const d=data();d.charts.current_daily[6].value=1.25;
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    const chart=s.charts[0], scroll=chart.children[1];
    let prevented=false;scroll.handlers.keydown({key:'End',preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(chart.dataset.selectedIndex,'6');
    assert.equal(chart.children[2].children[1].textContent,'1.25 kn');
    s.host.clientWidth=320; s.window.handlers.resize();assert.equal(chart.dataset.selectedIndex,'6');
    assert.equal(chart.children[2].children[1].textContent,'1.25 kn');
});
test('daily chart fits a narrow phone and pointer selection does not add dozens of tab stops', async () => {
    const s=setup();s.charts[0].clientWidth=270;
    s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const svg=s.charts[0].children[1].children[0];
    assert.equal(svg.attrs.width,'270');
    assert.equal(svg.children.filter(n=>n.attrs.tabindex).length,0);
    svg.getBoundingClientRect=()=>({left:0,width:270});
    svg.handlers.pointerdown({clientX:200,type:'pointerdown',pointerType:'touch'});
    assert.ok(Number(s.charts[0].dataset.selectedIndex)>0);
});

test('rainfall chart shows twelve monthly totals in millimeters and fits a narrow phone', async () => {
    const s=setup();s.charts[3].clientWidth=270;
    s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const chart=s.charts[3],axis=chart.children[0],svg=chart.children[1].children[0];
    assert.equal(svg.attrs.width,'270');
    assert.equal(svg.children.filter(n=>n.tag==='rect').length,12);
    assert.ok(axis.children.every(n=>n.textContent.endsWith(' mm')));
    assert.equal(chart.children[2].children[0].textContent,'Oct 2025 · Monthly total');
    assert.equal(chart.children[2].children[1].textContent,'40 mm');
    assert.equal(svg.children.filter(n=>n.attrs.class==='marine-moon-marker').length,0);
});

test('tide forecast is filled and chart readouts are not visible beneath the axes', async () => {
    const s=setup();s.requests[0].resolve({status:200,ok:true,json:async()=>data()});await flush();
    const tide=s.charts[1].children[1].children[0];
    assert.equal(tide.children.filter(n=>n.tag==='circle').length,0);
    assert.equal(tide.children.filter(n=>n.attrs.class==='marine-tide-fill').length,1);
    assert.equal(tide.children.filter(n=>n.tag==='polyline').length,1);
    assert.equal(s.charts[0].children[2].className,'sr-only');
    assert.equal(s.charts[1].children[2].className,'sr-only');
});

test('equipment advice shows personalized exposure, neutral weight and exact caveat marker', async () => {
    const s=setup(), d=data();
    d.recommendations={exposure:'5mm wetsuit',personalized:true,source_dive_id:42,source_dive_url:'/dive/42',weight:'6 kg'};
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    assert.equal(s.equipment.hidden,false);
    assert.equal(s.exposureName.textContent,'5mm wetsuit');
    assert.equal(s.weightAdvice.textContent,'6 kg');
    assert.equal(s.weightCaveat.hidden,false);
    assert.equal(s.weightAsterisk.hidden,false);
    assert.equal(s.exposureAsterisk.hidden,false);
    assert.equal(s.exposureHistory.hidden,false);
    assert.equal(s.exposureHistoryLink.attrs.href,'/dive/42');
});
test('no matching neutral weight shows a dash without the weight caveat', async () => {
    const s=setup(),d=data(); d.recommendations={exposure:'swimsuit or shorty',personalized:false,weight:null};
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    assert.equal(s.weightAdvice.textContent,'-');assert.equal(s.weightCaveat.hidden,true);assert.equal(s.weightAsterisk.hidden,true);assert.equal(s.exposureAsterisk.hidden,true);assert.equal(s.exposureHistory.hidden,true);assert.equal(s.exposureHistoryLink.attrs.href,undefined);
    assert.equal(s.exposureName.textContent,'swimsuit or shorty');
});
test('a corroborating dive shows history even when it does not override the default', async () => {
    const s=setup(), d=data();
    d.recommendations={exposure:'shorty',personalized:false,source_dive_id:43,source_dive_url:'/dive/43',weight:null};
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    assert.equal(s.exposureAsterisk.hidden,false);
    assert.equal(s.exposureHistory.hidden,false);
    assert.equal(s.exposureHistoryLink.attrs.href,'/dive/43');
    assert.equal(s.weightAdvice.textContent,'-');
    assert.equal(s.weightAsterisk.hidden,true);
});
test('weight advice preserves converted imperial units and a separate marker', async () => {
    const s=setup(), d=data();
    d.recommendations={exposure:'5mm wetsuit',personalized:false,weight:'17.5 lb'};
    s.requests[0].resolve({status:200,ok:true,json:async()=>d});await flush();
    assert.equal(s.weightAdvice.textContent,'17.5 lb');
    assert.equal(s.weightAsterisk.hidden,false);
    assert.equal(s.exposureHistory.hidden,true);
});
test('returning to the site refreshes the history destination and clears stale advice', async () => {
    const s=setup();
    const respond = async recommendations => {
        s.requests.at(-1).resolve({status:200,ok:true,json:async()=>({...data(),recommendations})});
        await flush();
    };
    await respond({exposure:'5mm wetsuit',source_dive_id:42,source_dive_url:'/dive/42',weight:'17.5 lb'});
    assert.equal(s.exposureHistoryLink.attrs.href,'/dive/42');
    const returnToSite = () => {
        s.window.handlers.pagehide();
        s.window.handlers.pageshow({persisted:true});
    };
    returnToSite();
    assert.equal(s.equipment.hidden,true);
    await respond({exposure:'3mm wetsuit',source_dive_id:43,source_dive_url:'/dive/43',weight:'8 kg'});
    assert.equal(s.exposureHistoryLink.attrs.href,'/dive/43');
    assert.equal(s.exposureName.textContent,'3mm wetsuit');
    assert.equal(s.weightAdvice.textContent,'8 kg');
    returnToSite();
    await respond({exposure:'swimsuit or shorty',source_dive_id:null,weight:null});
    assert.equal(s.requests.length,3);
    assert.equal(s.exposureHistoryLink.attrs.href,undefined);
    assert.equal(s.exposureHistory.hidden,true);
    assert.equal(s.exposureAsterisk.hidden,true);
    assert.equal(s.weightAdvice.textContent,'-');
    assert.equal(s.weightCaveat.hidden,true);
});
test('missing marine temperature or failed fetch keeps equipment advice hidden', async () => {
    const s=setup(); assert.equal(s.equipment.hidden,true);
    s.requests[0].resolve({status:200,ok:true,json:async()=>({...data(),recommendations:null})});await flush();
    assert.equal(s.equipment.hidden,true);
    const failed=setup(); failed.requests[0].reject(new Error());await flush();
    assert.equal(failed.equipment.hidden,true);
});

test('visibility shares monthly chart layout with a fixed clarity scale and exact source tooltips', () => {
    const s=setup('false'); const chart=node(); chart.clientWidth=320;
    const points=Array.from({length:12},(_,i)=>({time:Date.UTC(2025,i,1,12)/1000,value:i%5+1,kd490:.07,latitude:-.39375,longitude:-90.28125}));
    s.context.module.exports.renderChart(chart,points,{visibility:true,zone:'UTC'});
    assert.deepEqual(chart.children[0].children.map(n=>n.textContent),['Very poor','Poor','Fair','Good','Excellent']);
    const svg=chart.children[1].children[0];
    assert.equal(svg.attrs.width,'320'); assert.equal(svg.children.filter(n=>n.tag==='rect').length,12);
    assert.ok(svg.children.find(n=>n.tag==='rect').attrs['aria-label'].includes('Kd490 0.0700'));
    chart.children[1].handlers.keydown({key:'ArrowRight',preventDefault(){}});
    assert.ok(chart.children[2].children[0].textContent.includes('Monthly mean'));
});
test('visibility loads independently, shows observation date and survives a marine failure',async()=>{
    const s=setup('true',true);
    assert.equal(s.requests.length,3);
    const point={time:Date.UTC(2026,7,1,12)/1000,value:4,label:'Good',kd490:.07,latitude:-.39375,longitude:-90.28125};
    s.requests[0].resolve({status:200,ok:true,json:async()=>({status:'complete',points:[point]})});
    s.requests[1].resolve({status:200,ok:true,json:async()=>({status:'complete',latest:point})});
    s.requests[2].reject(new Error());await flush();
    assert.equal(s.visibilityValue.textContent,'Good'); assert.ok(s.visibilityDate.textContent.includes('UTC'));
    assert.equal(s.visibilityChart.children[0].children.length,5);assert.equal(s.visibilityRetry.hidden,true);
    s.window.handlers.pagehide();assert.ok(s.requests[0].options.signal.aborted);
});
test('visibility retry, pending polling and stale cached results are explicit',async()=>{
    const s=setup('true',true);
    s.requests[0].resolve({status:202,ok:true});s.requests[1].reject(new Error());await flush();
    assert.ok([...s.timers.values()].some(t=>t.delay===2000));
    const poll=[...s.timers.values()].find(t=>t.delay===2000);poll.fn();
    s.requests[3].resolve({status:200,ok:true,json:async()=>({status:'complete',points:[],stale:true})});await flush();
    assert.equal(s.visibilityRetry.hidden,false);
    s.visibilityRetry.handlers.click();assert.equal(s.requests.length,6);
});
