import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_reference_autocomplete as fixtures
from pelagia import db as database


class ObisCatalogDisplayTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, self.db_path, _ = self.make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    def test_site_combines_precomputed_catalog_and_logged_species(self):
        with self.app.app_context():
            db = database.get_db()
            dive_id = db.execute(
                "INSERT INTO dives (user_id, dive_site_id, date, site_name) "
                "VALUES (1, 1, '2026-01-01', 'Alert Rock')"
            ).lastrowid
            db.executemany(
                "INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                [(dive_id, "Coral"), (dive_id, "Harbor Seal")],
            )
            species_id = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM species").fetchone()[0]
            db.execute(
                "INSERT INTO species (id, country_or_area, common_name) VALUES (?, ?, ?)",
                (species_id, "Test Catalog", "Octopus"),
            )
            db.execute(
                "INSERT INTO obis_occurrences "
                "(obis_id, occurrence_id, queried_taxon_id, scientific_name, event_date, "
                "decimal_latitude, decimal_longitude, coordinate_uncertainty_m, raw_json) "
                "VALUES ('catalog-record', 'provider-record', 1, 'Octopus cyanea', "
                "'2026-03-01', 54.1, -132.9, 10, '{}')"
            )
            db.execute(
                "INSERT INTO dive_site_obis_occurrences "
                "(dive_site_id, species_id, obis_id, distance_meters) VALUES (1, ?, 'catalog-record', 12)",
                (species_id,),
            )
            db.commit()

        html = self.client.get("/dive-sites/1").get_data(as_text=True)
        sightings = html.split('<div class="site-sightings-panel">', 1)[1].split("</div>", 2)[0]
        self.assertEqual(sightings.count("Octopus"), 1)
        self.assertEqual(sightings.count("Coral"), 1)
        self.assertEqual(sightings.count("Harbor Seal"), 1)
        self.assertNotIn("data-obis-species-url", sightings)
        self.assertEqual(
            self.client.post(
                "/api/dive-sites/1/obis-species",
                headers={"X-Requested-With": "fetch"},
            ).status_code,
            404,
        )

    def test_runtime_enrichment_tables_are_removed_during_upgrade(self):
        with self.app.app_context():
            db = database.get_db()
            db.executescript(
                """
                CREATE TABLE dive_site_obis_species_cache (dive_site_id INTEGER PRIMARY KEY);
                CREATE TABLE dive_site_obis_species (dive_site_id INTEGER, common_name TEXT);
                CREATE TABLE dive_site_obis_species_attempts (dive_site_id INTEGER PRIMARY KEY);
                """
            )
            database.init_db()
        with sqlite3.connect(self.db_path) as db:
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertNotIn("dive_site_obis_species_cache", tables)
        self.assertNotIn("dive_site_obis_species", tables)
        self.assertNotIn("dive_site_obis_species_attempts", tables)


if __name__ == "__main__":
    unittest.main()
