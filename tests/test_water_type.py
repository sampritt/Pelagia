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
        with patch("pelagia.water_type.requests.get", side_effect=[self.upstream("OCEAN"), self.upstream("LAKE")]) as get:
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

    def test_site_classification_is_persistent_and_coordinates_invalidate_it(self):
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
            self.assertEqual(changed.get_json()["feature"], "LAND")
            self.assertEqual(get.call_count, 2)
