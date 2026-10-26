import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import test_reference_autocomplete as fixtures
from pelagia import db as database, obis_species


def api_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


def openai_payload(tags):
    return {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search"}},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(tags)}]},
        ],
    }


class ObisSpeciesTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, self.db_path, _ = self.make_app(Path(self.directory.name))
        self.app.config["OPENAI_API_KEY"] = "test-secret"
        self.client = self.app.test_client()
        self.signup(self.client)
        self.headers = {"X-Requested-With": "fetch"}

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def test_database_upgrade_is_idempotent_and_separate_from_logged_species(self):
        with self.app.app_context():
            database.init_db()
            database.init_db()
            tables = {
                row[0] for row in database.get_db().execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({
            "dive_site_obis_species_cache",
            "dive_site_obis_species",
            "dive_site_obis_species_attempts",
        }.issubset(tables))
        self.assertIn("dive_species", tables)

    def test_fetch_filters_distance_uncertainty_absence_and_deduplicates_species(self):
        valid = {
            "id": "valid", "absence": False, "decimalLatitude": 54.1002,
            "decimalLongitude": -132.9002, "coordinateUncertaintyInMeters": 100,
            "species": "Triaenodon obesus", "speciesid": 218253,
            "genus": "Triaenodon", "family": "Carcharhinidae",
        }
        rows = [
            valid,
            {**valid, "id": "duplicate"},
            {**valid, "id": "uncertain", "species": "Mobula kuhlii", "speciesid": 102,
             "coordinateUncertaintyInMeters": 805},
            {**valid, "id": "far", "species": "Octopus cyanea", "speciesid": 103,
             "decimalLatitude": 54.12},
            {**valid, "id": "absent", "species": "Chelonia mydas", "speciesid": 104,
             "absence": True},
            {**valid, "id": "genus", "species": "", "speciesid": None},
            {**valid, "id": "missing-uncertainty", "species": "Aetobatus ocellatus",
             "speciesid": 105, "coordinateUncertaintyInMeters": None},
        ]
        response = api_response({"total": len(rows), "results": rows})
        with self.app.app_context(), patch.object(obis_species.requests, "get", return_value=response) as get:
            result = obis_species.fetch_obis_species(54.1, -132.9)
        self.assertEqual(result, [{
            "scientific_name": "Triaenodon obesus", "aphia_id": 218253,
            "genus": "Triaenodon", "family": "Carcharhinidae", "order": None, "class": None,
        }])
        self.assertEqual(get.call_args.kwargs["params"]["startdate"], "2020-01-01")
        self.assertEqual(get.call_args.kwargs["params"]["size"], 1000)
        self.assertIn("POLYGON", get.call_args.kwargs["params"]["geometry"])
        self.assertEqual(get.call_args.kwargs["timeout"], (3, 20))
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        response.close.assert_called_once()

    def test_antimeridian_search_uses_two_geometries_and_deduplicates_occurrences(self):
        row = {
            "id": "same", "absence": False, "decimalLatitude": 0,
            "decimalLongitude": 179.999, "coordinateUncertaintyInMeters": 2,
            "species": "Mobula kuhlii", "speciesid": 1,
        }
        responses = [api_response({"results": [row]}), api_response({"results": [row]})]
        with self.app.app_context(), patch.object(obis_species.requests, "get", side_effect=responses) as get:
            result = obis_species.fetch_obis_species(0, 179.9999, 1)
        self.assertEqual(len(get.call_args_list), 2)
        self.assertEqual([taxon["scientific_name"] for taxon in result], ["Mobula kuhlii"])

    def test_normalizer_uses_description_model_parameters_and_validates_tags(self):
        response = api_response(openai_payload(["Coral", "reef fish", "Coral"]))
        taxa = [{"scientific_name": "Example species", "aphia_id": 7}]
        with self.app.app_context(), patch.object(obis_species.requests, "post", return_value=response) as post:
            tags = obis_species.normalize_species(taxa, ["Coral", "Reef Fish"])
        self.assertEqual(tags, ["Coral", "Reef Fish"])
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "gpt-5.6-luna")
        self.assertEqual(body["tools"], [{"type": "web_search", "search_context_size": "low"}])
        self.assertEqual(body["tool_choice"], "required")
        self.assertEqual(body["max_tool_calls"], 1)
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertEqual(body["max_output_tokens"], 1000)
        self.assertFalse(body["store"])
        self.assertEqual(post.call_args.kwargs["timeout"], (3, 20))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertIn("Example species", body["input"])
        self.assertIn("most specific", body["instructions"])
        response.close.assert_called_once()
        with self.assertRaises(obis_species.EnrichmentError):
            obis_species.parse_normalized_tags(openai_payload(["Invented animal"]), ["Coral"])

    def test_cold_endpoint_persists_once_and_warm_requests_do_not_call_upstreams(self):
        taxa = [{"scientific_name": "Triaenodon obesus", "aphia_id": 218253}]
        with patch.object(obis_species, "fetch_obis_species", return_value=taxa) as fetch, \
             patch.object(obis_species, "normalize_species", return_value=["Reef Fish", "Coral"]) as normalize:
            first = self.client.post("/api/dive-sites/1/obis-species", headers=self.headers)
            second = self.client.post("/api/dive-sites/1/obis-species", headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["Cache-Control"], "no-store")
        self.assertEqual(first.get_json(), {"status": "complete", "species": ["Coral", "Reef Fish"]})
        self.assertEqual(second.get_json(), first.get_json())
        fetch.assert_called_once_with(54.1, -132.9)
        normalize.assert_called_once()
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_obis_species_cache").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_obis_species").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_species").fetchone()[0], 0)

    def test_empty_obis_result_is_permanent_without_openai(self):
        with patch.object(obis_species, "fetch_obis_species", return_value=[]) as fetch, \
             patch.object(obis_species, "normalize_species") as normalize:
            result = self.client.post("/api/dive-sites/1/obis-species", headers=self.headers)
            warm = self.client.post("/api/dive-sites/1/obis-species", headers=self.headers)
        self.assertEqual(result.get_json()["species"], [])
        self.assertEqual(warm.get_json()["species"], [])
        fetch.assert_called_once()
        normalize.assert_not_called()

    def test_endpoint_auth_missing_site_and_retryable_failure(self):
        self.assertEqual(self.app.test_client().post("/api/dive-sites/1/obis-species").status_code, 302)
        self.assertEqual(self.client.post("/api/dive-sites/1/obis-species").status_code, 403)
        self.assertEqual(self.client.post("/api/dive-sites/999/obis-species", headers=self.headers).status_code, 404)
        with patch.object(obis_species, "fetch_obis_species", side_effect=obis_species.EnrichmentError("nope")):
            failed = self.client.post("/api/dive-sites/1/obis-species", headers=self.headers)
        self.assertEqual(failed.status_code, 503)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_obis_species_cache").fetchone()[0], 0)
            self.assertGreater(db.execute("SELECT retry_after FROM dive_site_obis_species_attempts").fetchone()[0], 0)

    def test_concurrent_claims_allow_only_one_worker(self):
        barrier = threading.Barrier(2)

        def claim():
            with self.connect() as db:
                barrier.wait()
                return obis_species.claim_generation(db, 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: claim(), range(2)))
        self.assertEqual(sorted(result[0] for result in results), ["claimed", "pending"])

    def test_profile_unifies_cached_and_logged_species_without_duplicates(self):
        with self.app.app_context():
            db = database.get_db()
            dive = db.execute(
                "INSERT INTO dives (user_id, dive_site_id, date, site_name) "
                "VALUES (1, 1, '2026-01-01', 'Alert Rock')"
            ).lastrowid
            db.executemany(
                "INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                [(dive, "Coral"), (dive, "Harbor Seal")],
            )
            db.execute(
                "INSERT INTO dive_site_obis_species_cache "
                "(dive_site_id, latitude, longitude, radius_miles, start_date, model) "
                "VALUES (1, 54.1, -132.9, 0.5, '2020-01-01', 'test')"
            )
            db.executemany(
                "INSERT INTO dive_site_obis_species (dive_site_id, common_name) VALUES (1, ?)",
                [("coral",), ("Reef Fish",)],
            )
            db.commit()
        html = self.client.get("/dive-sites/1").get_data(as_text=True)
        self.assertEqual(html.count('data-species-name="coral"'), 1)
        self.assertIn('data-species-name="harbor seal"', html)
        self.assertIn('data-species-name="reef fish"', html)
        self.assertNotIn("data-obis-species-url", html)
        self.assertEqual(self.app.test_client().get("/share/dive-site/1").get_data(as_text=True).count("Reef Fish"), 1)


if __name__ == "__main__":
    unittest.main()
