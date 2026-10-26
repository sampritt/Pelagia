import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pelagia import obis_catalog


class FakeApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class ObisCatalogTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE species (id INTEGER PRIMARY KEY, country_or_area TEXT, common_name TEXT);
            CREATE TABLE dive_sites (
                id INTEGER PRIMARY KEY, name TEXT, latitude REAL, longitude REAL
            );
            INSERT INTO species VALUES (1, 'Global', 'Whale Shark');
            INSERT INTO species VALUES (2, 'Global', 'Octopus');
            INSERT INTO dive_sites VALUES (10, 'Test Site', 0, 0);
        """)
        obis_catalog.initialize_schema(self.db)
        self.addCleanup(self.db.close)

    def test_cartesian_distance_and_grid_are_antimeridian_safe_and_strict(self):
        self.assertAlmostEqual(
            obis_catalog.cartesian_distance_m(0, 179.9995, 0, -179.9995),
            111.2,
            delta=0.5,
        )
        index = obis_catalog.DiveSiteIndex(
            [obis_catalog.DiveSite(1, 0, 179.9995)], 200
        )
        matches = index.nearby(0, -179.9995)
        self.assertEqual([site.id for site, _distance in matches], [1])
        boundary = obis_catalog.DiveSiteIndex(
            [obis_catalog.DiveSite(2, 0, 0)], 0
        )
        self.assertEqual(boundary.nearby(0, 0), [])

    def test_resolution_uses_most_specific_exact_marine_taxa(self):
        api = FakeApi([[
            {
                "AphiaID": 105706, "valid_AphiaID": 105706,
                "scientificname": "Rhincodontidae", "valid_name": "Rhincodontidae",
                "rank": "Family", "isMarine": 1,
            },
            {
                "AphiaID": 105847, "valid_AphiaID": 105847,
                "scientificname": "Rhincodon typus", "valid_name": "Rhincodon typus",
                "rank": "Species", "isMarine": 1,
            },
        ]])
        taxa, source = obis_catalog.resolve_name(api, "Whale Shark")
        self.assertEqual(source, "worms_vernacular")
        self.assertEqual(taxa, [{
            "taxon_id": 105847,
            "scientific_name": "Rhincodon typus",
            "taxon_rank": "Species",
        }])

    def test_qualifying_occurrence_requires_strict_uncertainty_and_presence(self):
        radius = 0.5 * obis_catalog.METERS_PER_MILE
        base = {
            "decimalLatitude": 0,
            "decimalLongitude": 0,
            "coordinateUncertaintyInMeters": 100,
        }
        self.assertEqual(obis_catalog.qualifying_occurrence(base, radius), (0.0, 0.0, 100.0))
        self.assertIsNone(obis_catalog.qualifying_occurrence(
            {**base, "coordinateUncertaintyInMeters": radius}, radius
        ))
        self.assertIsNone(obis_catalog.qualifying_occurrence(
            {**base, "occurrenceStatus": "absent"}, radius
        ))
        self.assertIsNone(obis_catalog.qualifying_occurrence(
            {**base, "coordinateUncertaintyInMeters": None}, radius
        ))

    def test_ingestion_saves_full_record_all_site_species_links_and_resumes(self):
        self.db.executemany(
            "INSERT INTO pelagia_species_obis_taxa "
            "(species_id, taxon_id, scientific_name, taxon_rank, source) "
            "VALUES (?, 105847, 'Rhincodon typus', 'Species', 'test')",
            [(1,), (2,)],
        )
        self.db.commit()
        record = {
            "id": "obis-row-1",
            "occurrenceID": "provider-1",
            "scientificName": "Rhincodon typus",
            "eventDate": "2026-01-02",
            "decimalLatitude": 0.001,
            "decimalLongitude": 0.001,
            "coordinateUncertaintyInMeters": 25,
            "datasetName": "Example",
        }
        api = FakeApi([{"results": [
            record,
            {**record, "id": "too-uncertain", "coordinateUncertaintyInMeters": 900},
            {**record, "id": "too-far", "decimalLatitude": 1},
        ]}])
        index = obis_catalog.DiveSiteIndex(
            obis_catalog.load_sites(self.db), 0.5 * obis_catalog.METERS_PER_MILE
        )
        obis_catalog.ingest_taxon(
            self.db, api, 105847, [1, 2], index,
            date(2020, 1, 1), date(2026, 1, 3), progress=lambda _message: None,
        )
        stored = self.db.execute("SELECT * FROM obis_occurrences").fetchone()
        self.assertEqual(stored["obis_id"], "obis-row-1")
        self.assertEqual(json.loads(stored["raw_json"])["datasetName"], "Example")
        self.assertEqual(
            self.db.execute("SELECT taxon_id FROM obis_occurrence_queries").fetchone()[0],
            105847,
        )
        links = self.db.execute(
            "SELECT species_id FROM dive_site_obis_occurrences ORDER BY species_id"
        ).fetchall()
        self.assertEqual([row[0] for row in links], [1, 2])
        self.assertEqual(
            self.db.execute("SELECT status FROM obis_taxon_ingestion").fetchone()[0],
            "complete",
        )
        obis_catalog.ingest_taxon(
            self.db, api, 105847, [1, 2], index,
            date(2020, 1, 1), date(2026, 1, 3), progress=lambda _message: None,
        )
        self.assertEqual(len(api.calls), 1)


if __name__ == "__main__":
    unittest.main()
