"""Personal dive-equipment heuristics; never stored in the shared marine cache."""
import math
from datetime import datetime, timezone

from .metrics import format_metric
from .units import display_measurement

EXPOSURES = ('swimsuit', 'shorty', '2mm', '3mm', '5mm', '6mm', '7mm', 'dry suit')
LABELS = {value: f'{value} wetsuit' for value in EXPOSURES if value.endswith('mm')}
LABELS.update({'swimsuit': 'swimsuit', 'shorty': 'shorty', 'dry suit': 'drysuit'})
TEMPERATURE_MATCH_C = 3 * 5 / 9  # A 3 F difference, independently of display units.


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
    logs = db.execute('''SELECT d.id, d.date, d.exposure, d.water_temp_c, d.temperature_rating,
                         d.weight_kg, d.weight_rating, d.water_type,
                         COALESCE(NULLIF(TRIM(d.country_or_area), ''), s.country_or_area) AS country_or_area
                         FROM dives d LEFT JOIN dive_sites s ON s.id=d.dive_site_id
                         WHERE d.user_id=? AND COALESCE(d.is_deleted,0)=0 AND d.date<=?
                         ORDER BY d.date DESC, d.id DESC''', (user_id, today)).fetchall()
    site = db.execute('SELECT country_or_area FROM dive_sites WHERE id=?', (site_id,)).fetchone()
    region = (site['country_or_area'] or '').strip().casefold() if site else ''
    regional_logs = [row for row in logs if region
                     and (row['country_or_area'] or '').strip().casefold() == region]
    # Existing regional history restricts exposure matching, even if none of its
    # logs qualify for the temperature window. Weight matching still uses all logs.
    exposure_logs = regional_logs or logs
    choices = default_exposures(temperature_c)
    nearby = [row for row in exposure_logs if row['exposure'] in EXPOSURES
              and row['water_temp_c'] is not None and row['temperature_rating'] in (1, 2, 3, 4, 5)
              # Keep exact 3 F endpoints inclusive after floating-point conversion.
              and abs(row['water_temp_c'] - temperature_c) <= TEMPERATURE_MATCH_C + 1e-9]
    personalized = False
    source_dive_id = None
    if nearby:
        comfortable = [row for row in nearby if row['temperature_rating'] == 3]
        if comfortable:
            candidates = comfortable
        else:
            # Keep nearest-temperature feedback as the fallback when no suit was
            # rated comfortable anywhere in the matching window.
            closest_distance = min(abs(row['water_temp_c'] - temperature_c) for row in nearby)
            candidates = [row for row in nearby if math.isclose(abs(row['water_temp_c'] - temperature_c),
                                                               closest_distance, rel_tol=0, abs_tol=1e-9)]
        proposals = []
        for row in candidates:
            index = EXPOSURES.index(row['exposure'])
            step = 1 if row['temperature_rating'] < 3 else -1 if row['temperature_rating'] > 3 else 0
            proposals.append((row, max(0, min(len(EXPOSURES) - 1, index + step))))
        # Minimum protection wins. For that exposure, link the closest supporting
        # measurement, then the most recent log using SQL's newest-first order.
        reference, proposed = min(
            proposals,
            key=lambda proposal: (proposal[1], abs(proposal[0]['water_temp_c'] - temperature_c)),
        )
        personalized = EXPOSURES[proposed] not in choices
        source_dive_id = reference['id']
        choices = (EXPOSURES[proposed],)
    site_log = db.execute('''SELECT water_type FROM dives WHERE dive_site_id=?
                            AND COALESCE(is_deleted,0)=0 AND date<=?
                            AND water_type IN ('fresh', 'salt')
                            ORDER BY date DESC, id DESC LIMIT 1''', (site_id, today)).fetchone()
    salinity = site_log['water_type'] if site_log else None
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
