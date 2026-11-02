from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import test_reference_autocomplete as fixtures
from pelagia import water_type
from pelagia import db as database


class WaterTypeEndpointTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app, _, _ = self.make_app(Path(temp.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    @staticmethod
    def upstream(feature):
        response = Mock()
        response.json.return_value = {"feature": feature}
        response.raise_for_status.return_value = None
        return response

    def test_ocean_is_salt_and_every_other_feature_is_fresh(self):
        with patch("pelagia.water_type.requests.get", side_effect=[self.upstream("OCEAN")] + [self.upstream("LAKE")] * 9) as get:
            ocean = self.client.get("/api/water-type?latitude=-0.5667634&longitude=-90.14297416")
            lake = self.client.get("/api/water-type?latitude=20.137461&longitude=-87.5782533")
        self.assertEqual(ocean.get_json(), {"status": "complete", "feature": "OCEAN", "water_type": "salt"})
        self.assertEqual(lake.get_json(), {"status": "complete", "feature": "LAKE", "water_type": "fresh"})
        self.assertEqual(ocean.headers["Cache-Control"], "private, no-store")
        self.assertEqual(get.call_args_list[0].args[0], f"{water_type.DEFAULT_API_URL}/-0.5667634/-90.14297416")
        self.assertEqual(get.call_args_list[0].kwargs["timeout"], (2, 5))

    def test_auth_coordinates_and_upstream_failures(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/api/water-type?latitude=1&longitude=2").status_code, 302)
        for query in ("", "?latitude=x&longitude=2", "?latitude=91&longitude=2", "?latitude=1&longitude=181"):
            self.assertEqual(self.client.get("/api/water-type" + query).status_code, 400)
        with patch("pelagia.water_type.requests.get", side_effect=requests.Timeout("offline")):
            response = self.client.get("/api/water-type?latitude=1&longitude=2")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "unavailable", "reason": "upstream"})

    def test_invalid_upstream_payload_is_unavailable(self):
        with patch("pelagia.water_type.requests.get", return_value=self.upstream(None)):
            self.assertEqual(self.client.get("/api/water-type?latitude=1&longitude=2").status_code, 503)

    def test_site_classification_is_persistent_even_if_coordinates_change(self):
        with patch(
            "pelagia.water_type.requests.get",
            side_effect=[self.upstream("OCEAN"), self.upstream("LAND")],
        ) as get:
            first = self.client.get("/api/water-type?site_id=1")
            second = self.client.get("/api/water-type?site_id=1")
            self.assertEqual(first.get_json()["feature"], "OCEAN")
            self.assertEqual(second.get_json()["feature"], "OCEAN")
            self.assertEqual(get.call_count, 1)
            with self.app.app_context():
                database.init_db()
                db = database.get_db()
                cached = db.execute(
                    "SELECT feature FROM dive_site_water_classifications WHERE dive_site_id=1"
                ).fetchone()
                self.assertEqual(cached["feature"], "OCEAN")
                db.execute("UPDATE dive_sites SET latitude=20.137461, longitude=-87.5782533 WHERE id=1")
                db.commit()
            changed = self.client.get("/api/water-type?site_id=1")
            self.assertEqual(changed.get_json()["feature"], "OCEAN")
            self.assertEqual(get.call_count, 1)

    def test_nearby_ocean_and_all_land(self):
        with patch("pelagia.water_type.requests.get", side_effect=[self.upstream("LAND")] * 5 + [self.upstream("OCEAN")] + [self.upstream("LAND")] * 3) as get:
            result = self.client.get("/api/water-type?latitude=19.3083&longitude=-81.3833")
            self.assertEqual(result.get_json()["water_type"], "salt")
            self.assertEqual(result.get_json()["feature"], "OCEAN")
            self.assertEqual(get.call_count, 9)
        with patch("pelagia.water_type.requests.get", return_value=self.upstream("LAND")) as get:
            result = self.client.get("/api/water-type?latitude=20.1375&longitude=-87.5778")
            self.assertEqual(result.get_json()["water_type"], "fresh")
            self.assertEqual(get.call_count, 9)

    def test_incomplete_nearby_lookup_is_not_cached_as_fresh(self):
        responses = [self.upstream("LAND")] * 8 + [requests.Timeout("offline")]
        with patch("pelagia.water_type.requests.get", side_effect=responses):
            response = self.client.get("/api/water-type?site_id=1")
        self.assertEqual(response.status_code, 503)
        with self.app.app_context():
            row = database.get_db().execute("SELECT feature FROM dive_site_water_classifications WHERE dive_site_id=1").fetchone()
            self.assertIsNone(row["feature"])

    def test_nearby_points_are_half_a_mile_away(self):
        import math
        lat, lon = 19.3083, -81.3833
        points = list(water_type.nearby_coordinates(lat, lon))
        self.assertEqual(len(points), 8)
        for target_lat, target_lon in points:
            lat1, lat2 = math.radians(lat), math.radians(target_lat)
            dlat = lat2 - lat1
            dlon = math.radians(target_lon - lon)
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            self.assertAlmostEqual(2 * 6371000 * math.asin(math.sqrt(a)), 804.672, places=4)

    def test_cache_migration_runs_only_once(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM pelagia_migrations WHERE name='nearby_ocean_classification_v1'")
            db.execute("INSERT INTO dive_site_water_classifications (dive_site_id, latitude, longitude, feature) VALUES (1, 1, 2, 'LAND')")
            db.commit()
            database.init_db()
            self.assertEqual(db.execute("SELECT count(*) FROM dive_site_water_classifications").fetchone()[0], 0)
            db.execute("INSERT INTO dive_site_water_classifications (dive_site_id, latitude, longitude, feature) VALUES (1, 1, 2, 'OCEAN')")
            db.commit()
            database.init_db()
            self.assertEqual(db.execute("SELECT feature FROM dive_site_water_classifications").fetchone()[0], 'OCEAN')
