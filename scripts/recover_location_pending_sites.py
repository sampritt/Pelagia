"""Review missing-geography records against a Natural Earth country GeoJSON.

python scripts/recover_location_pending_sites.py --countries /path/to/countries.geojson [--write]
The review is heuristic: only clear non-site names and near-name duplicates are
excluded automatically; source OSM observations still require validation.
"""
import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data/global_dive_sites_master.csv'
REMOVED = ROOT / 'data/dive_site_location_pending_review.csv'
REVIEW = ROOT / 'data/dive_site_location_recovery_review.csv'


def norm(s):
    s = unicodedata.normalize('NFKD', s.casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in s if not unicodedata.combining(c))))


def distance(a, b):
    p1, p2 = map(math.radians, (float(a['latitude']), float(b['latitude'])))
    dl = math.radians(float(b['longitude']) - float(a['longitude']))
    h = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 12742 * math.asin(min(1, math.sqrt(h)))


def in_ring(x, y, ring):
    inside = False
    x1, y1 = ring[-1]
    for x2, y2 in ring:
        if (y1 > y) != (y2 > y) and x < (x2-x1)*(y-y1)/(y2-y1)+x1:
            inside = not inside
        x1, y1 = x2, y2
    return inside


class Countries:
    def __init__(self, path):
        self.grid = defaultdict(list)
        features = json.loads(path.read_text())['features']
        for feature in features:
            p = feature['properties']; name, code = p['name'], p['ISO3166-1-Alpha-2']
            if code == '-99': continue
            geom = feature['geometry']; polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
            for rings in polys:
                outer = rings[0]; xs = [p[0] for p in outer]; ys = [p[1] for p in outer]
                bounds = min(xs), min(ys), max(xs), max(ys)
                # The geography has a few antimeridian rings spanning 360°;
                # ignore those instead of claiming points on the other side.
                if bounds[2]-bounds[0] > 180: continue
                item = (name, code, rings, bounds)
                for i in range(math.floor(bounds[0]), math.floor(bounds[2])+1):
                    for j in range(math.floor(bounds[1]), math.floor(bounds[3])+1): self.grid[i,j].append(item)

    def locate(self, lat, lon, source_code):
        cell = math.floor(lon), math.floor(lat)
        for name, code, rings, (x1,y1,x2,y2) in self.grid[cell]:
            if x1 <= lon <= x2 and y1 <= lat <= y2 and in_ring(lon,lat,rings[0]) and not any(in_ring(lon,lat,r) for r in rings[1:]):
                return name, code, 'inside country boundary', 0
        # Offshore: identify the closest shoreline segment, but only assign if
        # the source agrees, or the coast is very close and clearly unambiguous.
        candidates = {}
        lonrad = min(10, math.ceil(0.65/max(0.1, abs(math.cos(math.radians(lat))))))
        seen = set()
        for i in range(cell[0]-lonrad, cell[0]+lonrad+1):
            for j in range(cell[1]-1,cell[1]+2):
                for item in self.grid[i,j]:
                    if id(item) in seen: continue
                    seen.add(id(item)); name, code, rings, (x1,y1,x2,y2)=item
                    sx=111.2*math.cos(math.radians(lat)); sy=111.2
                    if max(x1-lon,0,lon-x2)*sx > 50 or max(y1-lat,0,lat-y2)*sy > 50: continue
                    best = candidates.get(code, (1e9,name))[0]
                    for ring in rings:
                        ax,ay=ring[-1]
                        for bx,by in ring:
                            x,y=(ax-lon)*sx,(ay-lat)*sy; dx,dy=(bx-ax)*sx,(by-ay)*sy
                            t=max(0,min(1,-(x*dx+y*dy)/(dx*dx+dy*dy))) if dx or dy else 0
                            best=min(best,math.hypot(x+t*dx,y+t*dy)); ax,ay=bx,by
                    candidates[code]=(best,name)
        choices=sorted((v[0],v[1],k) for k,v in candidates.items())
        if not choices:return '', '', 'no nearby country boundary', ''
        best,name,code=choices[0]; second=choices[1][0] if len(choices)>1 else 1e9
        if (best <= 40 and code == source_code and second-best >= 3) or (best <= 5 and second-best >= 10):
            return name,code,'nearest coast; source country agrees' if code == source_code else 'nearest coast; unambiguous',round(best,2)
        return '', '', f'uncertain offshore: nearest {name} {best:.1f} km',round(best,2)


# Names that are businesses, facilities, landmarks, individual underwater
# props or generic unnamed points rather than independently identified sites.
NON_SITE = re.compile(r'\b(divers?|diving|scuba|plong[eé]e|buceo|tauch(?:schule|club|sport|basis|gruppe|verein|station|gemeinschaft|verband)|duikvereniging|sportsdykkerklub|dive\s*(?:center|centre|club|shop|school|academy|tribe)|centre de|centro de|club de|centre international|restaurant|hotel|camping|dive medicine|hyperbaric|verein|societ[eé]|[eé]cole|platform|plattform|plataforma|bojen|mooring|parking|parkplatz|piscine|schwimmbad|swim center|entry point|exit|ausstieg|taucheinstieg|tauchereinstieg|strandbad|badi|bootsrampe|bootshaus|clubhaus|schiffl[aä]nde|ausbildungs|ansaug|kabelrolle|kabelhaspel|autowrack|pkw|lkw|wohnwagen|briefkasten|schweiß|tisch|r[uü]ttler|segelclub|segelyacht|nurse|deco international)\b',re.I)
# Phrases involving 'dive' or its translations can describe an actual site.
SITE_EXCEPTION = re.compile(r'(dive site|dive park|dive spot|dive & shipwreck|site de plong[eé]e|tauchplatz|tauchspot|duikplaats|dive site)', re.I)
GENERIC = re.compile(r'^(dive site|diving spot|diving zone|site de plong[eé]e|tauchen|tauchplatz|tauchspot|taucher|taucheinstieg|tauchereinstieg|tauchzone|instap|snorkel(?:ing|ling)?|snorkelling reef|reef|the wall|wall|house reef|shipwreck|wreck|the pipeline|hafen|port|boot|pont|ponton|lido|strandbad|badeplatz|wasserfall|waterfall|insel|eg[g]|berg|wald|rampe|exit|route|tunnel|platform|plattform|seemitte|seezeichen|treppe|br[uü]cke|stollen|kraftwerk|padi|naut i lus|blue lagoon|paradise|paradies|nirvana|bajo|channel|chinatown|coral reef|marine sanctuary)(?:\s*[0-9a-z]+)?$',re.I)


# Explicitly reviewed sites whose names do not carry a generic site-type word.
VERIFIED = {'DS010933', 'DS011329', 'DS011470', 'DS011707', 'DS012832'}
# Sites where the same name is already represented but coordinates disagree,
# or a published location conflicts enough to warrant a separate check.
EXPLICIT_DUPLICATES = {'DS011673': 'DS001780', 'DS011973': 'DS010603', 'DS012130': 'DS007281',
                       'DS012567': 'DS000089', 'DS012644': 'DS007124', 'DS012926': 'DS005657',
                       'DS012927': 'DS005662', 'DS012928': 'DS005566', 'DS012929': 'DS005581',
                       'DS012944': 'DS002350'}
HOLD = {'DS011034': 'possibly dive centre at Attersee',
        'DS011407': 'generic name; exact site is unclear', 'DS011765': 'name does not identify a dive site',
        'DS012122': 'multiple sites combined into one record', 'DS012270': 'uncertain unnamed point of interest',
        'DS012648': 'shipwreck identity and nearby Olympia Maru need verification',
        'DS011154': 'Blue Magic already represented 1.8 km away',
        'DS011546': 'Fish Head already represented 2.3 km away',
        'DS011893': 'Kyokuzan Maru location needs independent verification',
        'DS012082': 'Manta Bowl already represented 7.4 km away',
        'DS011617': 'Aquarium likely already represented 70 m away'}
NOT_SITE = re.compile(r'(?:\b(?:club|sportsclub|sportclub|sportsdykker|dykkerklub|underwater club|dive|dives|diving|scuba|subaquatique|nurkowe|nurkowa|nurkowy|water ?sport|watersport|loisirs|subacque|submarin[ae]s|tauchsport|tauchclub|tauchschule|tauchbasis|tauchverein|tauchstation|tauchsportclub|tauchergruppe|duikvereniging|plong[eé]e|buceo|b[uú]v[aá]riskola|nautic|aquanaut|aquablue|aquamarina|fundiving|extradivers|training|fo[sß]e|fosse|piscine|plongeoir|basis|campingplatz|pflegeheim|altersheim|restaurant|bahnhof|auto[b]ahnbr[uü]cke|ansaug|einm[uü]ndung|flieger|flugzeug|f[oö]rderband|bohrhammer|betonbombe|betonschute|bestelbus|container|segelboot|schulhaus|stromleitung|wasserrettung|pumpwerk|seepolizei|sportplatz|hafenmauer|schiffsstation|kostenlos|bus|fischerei)\b|^(?:cb\s|duc\b|g\.m\.a\.p|dfh$|200 bar$|b\&j$))', re.I)
POSITIVE = re.compile(r'(?:\b(?:wreck|wrack|wrecks|shipwreck|maru|hmas|uss|hms|ss|u-\d|reef|riff|rif|shoal|shoel|pinnacle|coral|canyon|grotto|grotte|grotta|cave|cavern|caverne|sinkhole|quarry|carri[eè]re|steinbruch|baggersee|kiessee|kiesgrube|badesee|tauchsee|tauchzone|duikplaats|dive site|dive park|site de plong[eé]e|tauchplatz|tauchspot|duikplas|dive spot|island|isla|islas|ilha|ilhao|isole|insel|islet|isola|eiland|lake|lago|lac|see|weiher|teich|mare|meer|meeresschutzgebiet|atoll|wall|steilwand|steilhange|wand|dropoff|slope|ledge|garden|gardens|garden[s]?|bommie|bommies|boulder|tunnel|underwater park|unterwasserpark|trinchera|bah[ií]a|bay|cove|bucht|baie|cala|calanque|cabo|cap|cape|point|pointe|punta|ponta|rock|rocks|stein|felsen|jardin|jard[ií]n|blue hole|spring|spring[s]?|source|fontaine|gouffre|goul|exsurgence|emergence|source|jetty|pier|ste[gg]|br[uü]cke|arch|arche|arco|arrecife|cantil|bajo|piedra|pedra|secca|secche|tombant|hav[n]?|schliff|kessel|bassin)\b|(?:see|weiher|talsperre|fels|riff|steinbruch|grotte|cave|wrack|maru)$|^(?:attersee|traunsee|mondsee|walchensee|starnberger see|teg er nsee|lac l[eé]man|lago di|hohenwarte stausee|ossiacher see|millst[aä]tter see|je zioro|jezioro|redang|lankayan|eckernf[oö]rde|plansee|vorderer|lake|lac|lago)\s*[-–:])', re.I)


def near_name(a,b):
    x,y=norm(a),norm(b)
    if x==y:return 'same normalized name'
    def tidy(s):
        s=re.sub(r'\b(dive site|diving site|wreck dive site)\b','',s).strip()
        return re.sub(r'\s+',' ',s)
    tx,ty=tidy(x),tidy(y)
    if tx and tx==ty:return 'same name without dive-site label'
    # A one-character spelling variation is safe only for longer names.
    if min(len(tx),len(ty))>=10 and abs(len(tx)-len(ty))<=1 and SequenceMatcher(None,tx,ty).ratio()>=0.94:
        return 'near-identical spelling'
    return ''


def main():
    p=argparse.ArgumentParser();p.add_argument('--countries',type=Path,required=True);p.add_argument('--write',action='store_true');args=p.parse_args()
    with CATALOG.open(newline='') as f:r=csv.DictReader(f);fields=r.fieldnames;kept=list(r)
    with REMOVED.open(newline='') as f:removed=list(csv.DictReader(f))
    already = {r['master_site_id'] for r in kept} & {r['master_site_id'] for r in removed}
    if already:
        raise SystemExit('Some removed records are already in the catalogue; refusing to overwrite the review.')
    countries=Countries(args.countries)
    kept_by_id = {r['master_site_id']: r for r in kept}
    source_codes={}
    for row in kept:
        c=row['country_code']; loc=norm(row['country_or_area'])
        if len(c)==2 and c!='NA':source_codes.setdefault(loc,c)
    source_codes.update({'united states':'US','united kingdom':'GB','czech republic':'CZ','micronesia':'FM','bonaire':'BQ','cabo verde':'CV','saint vincent and the grenadines':'VC'})
    grid=defaultdict(list)
    def add(row):grid[math.floor(float(row['latitude'])*10),math.floor(float(row['longitude'])*10)].append(row)
    for row in kept:
        try:add(row)
        except (ValueError,TypeError):pass
    results=[];restored=[]
    for row in removed:
        name=row['dive_site_name'];lat=float(row['latitude']);lon=float(row['longitude']);cell=math.floor(lat*10),math.floor(lon*10)
        near=[]
        for i in range(cell[0]-1,cell[0]+2):
            for j in range(cell[1]-3,cell[1]+4):
                for other in grid[i,j]:
                    why=near_name(name,other['dive_site_name'])
                    if why and (km:=distance(row,other))<=5:near.append((km,other,why))
        m=re.search(r'/([^/]+)_divesites_osm\.csv',row['source_urls']);src=norm(m.group(1).replace('_',' ')) if m else ''
        geo,code,method,coast=countries.locate(lat,lon,source_codes.get(src,''))
        info={'master_site_id':row['master_site_id'],'name':name,'latitude':row['latitude'],'longitude':row['longitude'],
              'decision':'','reason':'','assigned_geography':geo,'assigned_country_code':code,'location_method':method,
              'coast_distance_km':coast,'match_id':'','match_name':'','match_distance_km':'','source_collection':src}
        if row['master_site_id'] in EXPLICIT_DUPLICATES:
            other = kept_by_id[EXPLICIT_DUPLICATES[row['master_site_id']]]
            info.update(decision='duplicate',reason='reviewed alias of existing site',match_id=other['master_site_id'],match_name=other['dive_site_name'],match_distance_km=round(distance(row,other),3))
        elif near:
            km,other,why=min(near,key=lambda x:x[0]);info.update(decision='duplicate' if km<=1 else 'review',reason=why if km<=1 else 'similar nearby name; coordinates differ by more than 1 km',match_id=other['master_site_id'],match_name=other['dive_site_name'],match_distance_km=round(km,3))
        elif row['master_site_id'] in HOLD:info.update(decision='review',reason=HOLD[row['master_site_id']])
        elif GENERIC.fullmatch(name.strip()):info.update(decision='review',reason='generic or ambiguous name')
        elif NOT_SITE.search(name) and not (SITE_EXCEPTION.search(name) and not re.search(r'club|school|shop|training|academy|center|centre|centro|basis', name, re.I)):info.update(decision='review',reason='possible business, facility, access point or object')
        elif NON_SITE.search(name) and not SITE_EXCEPTION.search(name):info.update(decision='review',reason='possible business, facility, access point or object')
        elif row['master_site_id'] not in VERIFIED and not POSITIVE.search(name):info.update(decision='review',reason='site identity unclear from name and source')
        elif not geo:info.update(decision='review',reason='geography unresolved')
        else:
            info.update(decision='restore',reason='individually reviewed site' if row['master_site_id'] in VERIFIED else 'source record with site-like name; not individually verified')
            site=dict(row);site['country_or_area']=geo;site['country_code']=code
            site['data_quality_notes'] += '; geography inferred from Natural Earth country boundary' if method=='inside country boundary' else '; geography inferred from nearby coast and source collection; approximate'
            restored.append(site);add(site)
        results.append(info)
    with REVIEW.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    if args.write:
        allrows=sorted(kept+restored,key=lambda x:int(x['legacy_import_id']))
        with CATALOG.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(allrows)
    print(Counter(r['decision'] for r in results));print(Counter(r['location_method'] for r in results).most_common(12))

if __name__=='__main__':main()
