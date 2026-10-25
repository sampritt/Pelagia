"""Personal dive-equipment heuristics; never stored in the shared marine cache."""
import math
from datetime import datetime, timezone

from .metrics import format_metric
from .units import display_measurement

EXPOSURES = ('swimsuit', 'shorty', '2mm', '3mm', '5mm', '6mm', '7mm', 'dry suit')
LABELS = {value: f'{value} wetsuit' for value in EXPOSURES if value.endswith('mm')}
LABELS.update({'swimsuit': 'swimsuit', 'shorty': 'shorty', 'dry suit': 'drysuit'})


def default_exposures(temperature_c):
    # Strictly "above" each threshold; exactly 50 F belongs to the drysuit band.
    for fahrenheit, choices in ((80, ('swimsuit', 'shorty')), (68, ('3mm',)),
                                (60, ('5mm',)), (50, ('7mm',))):
        if temperature_c > (fahrenheit - 32) * 5 / 9:
            return choices
    return ('dry suit',)


def recommend(db, user_id, site_id, temperature_c, now):
    if not isinstance(temperature_c, (int, float)) or isinstance(temperature_c, bool):
        return None
    if not math.isfinite(temperature_c):
        return None
    today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    logs = db.execute('''SELECT id, date, exposure, water_temp_c, temperature_rating,
                         weight_kg, weight_rating, water_type FROM dives
                         WHERE user_id=? AND COALESCE(is_deleted,0)=0 AND date<=?
                         ORDER BY date DESC, id DESC''', (user_id, today)).fetchall()
    choices = default_exposures(temperature_c)
    nearby = [row for row in logs if row['exposure'] in EXPOSURES
              and row['water_temp_c'] is not None and row['temperature_rating'] in (1, 2, 3, 4, 5)
              and abs(row['water_temp_c'] - temperature_c) <= 3]
    # Personal feedback may shift protection by one step around the current
    # temperature band, but an old thick-suit log cannot replace a warm-water rule.
    minimum = max(0, min(EXPOSURES.index(choice) for choice in choices) - 1)
    maximum = min(len(EXPOSURES) - 1, max(EXPOSURES.index(choice) for choice in choices) + 1)
    proposals = []
    for row in nearby:
        index = EXPOSURES.index(row['exposure'])
        step = 1 if row['temperature_rating'] < 3 else -1 if row['temperature_rating'] > 3 else 0
        proposed = max(0, min(len(EXPOSURES) - 1, index + step))
        if minimum <= proposed <= maximum:
            proposals.append((row, proposed))
    comfortable = [proposal for proposal in proposals if proposal[0]['temperature_rating'] == 3]
    candidates = comfortable or proposals
    personalized = False
    source_dive_id = None
    if candidates:
        # SQL order provides newest-first tie breaking for equal temperatures.
        reference, proposed = min(candidates, key=lambda proposal: abs(proposal[0]['water_temp_c'] - temperature_c))
        personalized = EXPOSURES[proposed] not in choices
        source_dive_id = reference['id']
        choices = (EXPOSURES[proposed],)
    site_log = db.execute('''SELECT water_type FROM dives WHERE dive_site_id=?
                            AND COALESCE(is_deleted,0)=0 AND date<=?
                            ORDER BY date DESC, id DESC LIMIT 1''', (site_id, today)).fetchone()
    salinity = site_log['water_type'] if site_log and site_log['water_type'] in ('fresh', 'salt') else None
    match = next((row for row in logs if row['exposure'] in choices and salinity
                  and row['water_type'] == salinity and row['weight_rating'] == 3
                  and row['weight_kg'] is not None and math.isfinite(row['weight_kg']) and row['weight_kg'] >= 0), None)
    weight = None
    if match:
        unit = db.execute('SELECT weight_unit FROM users WHERE id=?', (user_id,)).fetchone()['weight_unit']
        amount = format_metric(display_measurement(match['weight_kg'], unit), weight=True)
        weight = f"{amount} {unit}"
    return dict(exposure=' or '.join(LABELS[choice] for choice in choices), personalized=personalized,
                weight=weight, salinity=salinity, source_dive_id=source_dive_id)
