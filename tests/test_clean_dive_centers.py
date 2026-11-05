import unittest

from scripts.clean_dive_centers import apply_website_evidence, clean, reference_key, website_key
from scripts.check_center_websites import check, is_contact, parked_page, read_evidence
from unittest.mock import patch


def center(name="Coral Dive", address="10 Ocean Road", website="https://coral.test", **extra):
    return {"name": name, "physical_address": address, "website": website,
            "location": "Town, US", "latitude": "10", "longitude": "20", **extra}


class CleanupTest(unittest.TestCase):
    def test_missing_either_contact_is_removed_and_contacts_are_kept(self):
        rows, audit = clean([center(address=""), center(website=""), center(website="mailto:coral@example.test")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit["removed_missing_contact"], 2)

    def test_different_names_same_website_collapse_and_keep_aliases(self):
        rows, audit = clean([center(padi_id="123"), center(name="Coral Scuba", overture_id="old")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(reference_key(rows[0]), "padi:123")
        self.assertIn("overture:old", rows[0]["merged_reference_keys"])
        self.assertEqual(audit["merged_duplicate_rows"], 1)
        self.assertEqual(clean(rows)[1]["merged_duplicate_rows"], 0)

    def test_shared_marina_different_businesses_are_preserved(self):
        rows, _ = clean([center(name="Hawaiian Diving Adventures", website="https://hawaiian.test"),
                         center(name="Manny's Diving Adventures", website="https://mannys.test")])
        self.assertEqual(len(rows), 2)

    def test_transitive_duplicate_group_keeps_every_identity(self):
        original = [center(name="Coral Diving", address="117 Beach", overture_id="a"),
                    center(name="Island Scuba", address="Island", latitude="10.015", overture_id="b"),
                    center(name="Island Scuba", address="Island", latitude="10.0001", overture_id="c")]
        rows, audit = clean(original)
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit["merged_duplicate_rows"], 2)
        import json
        keys = {reference_key(rows[0]), *json.loads(rows[0]["merged_reference_keys"])}
        self.assertTrue({"overture:a", "overture:b", "overture:c"} <= keys)

    def test_dead_website_uses_working_duplicate_alternative(self):
        original = [center(padi_id="1"), center(website="https://new-coral.test", overture_id="a")]
        rows, audit = clean(original)
        rows = apply_website_evidence(rows, audit, {
            "https://coral.test": {"classification": "dead_confirmed", "attempts": [{"outcome": "dead_http"}]},
            "https://new-coral.test": {"classification": "live"}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["website"], "https://new-coral.test")
        self.assertEqual(audit["removed_dead_website"], 0)

    def test_confirmed_hosting_failure_survives_inconclusive_url_variant(self):
        rows, audit = clean([center(website="http://coral.test/")])
        rows = apply_website_evidence(rows, audit, {
            "http://coral.test/": {"classification": "unresolved"},
            "https://coral.test/": {"classification": "dead_confirmed", "attempts": [
                {"url": "http://coral.test/", "outcome": "dead_hosting"}]}})
        self.assertEqual(rows, [])
        self.assertEqual(audit["removed_dead_website"], 1)

    def test_authoritative_dns_can_overturn_local_failure(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in [
                {"website": "https://coral.test", "classification": "dead_confirmed"},
                {"website": "https://coral.test", "classification": "needs_retry"},
                {"website": "https://coral.test", "classification": "unresolved", "dns_confirmation": {"coral.test": 0}},
            ]) + "\n")
            self.assertEqual(read_evidence(path)["https://coral.test"]["classification"], "unresolved")

    def test_chain_branches_are_preserved(self):
        rows, _ = clean([center(padi_id="1"), center(address="12 Ocean Road", padi_id="2", latitude="10.001"),
                         center(address="20 Island Road", latitude="11")])
        self.assertEqual(len(rows), 3)

    def test_social_profiles_and_contact_addresses_have_distinct_keys(self):
        self.assertNotEqual(website_key("https://facebook.com/profile.php?id=1"),
                            website_key("https://facebook.com/profile.php?id=2"))
        self.assertNotEqual(website_key("mailto:a@example.test"), website_key("mailto:b@example.test"))
        self.assertEqual(website_key("http://www.coral.test/?utm_source=padi"), website_key("https://coral.test"))

    def test_contacts_and_social_do_not_need_http_checks(self):
        for value in ("mailto:dive@example.test", "dive@example.test", "tel:+123456789", "whatsapp://send?phone=123"):
            self.assertTrue(is_contact(value))
            self.assertEqual(check(value)["classification"], "contact_preserved")
        self.assertEqual(check("https://facebook.com/example")["classification"], "social_preserved")

    @patch("scripts.check_center_websites.attempt")
    def test_blocked_and_transient_failures_are_not_deleted(self, attempt):
        for outcome in ("unresolved_http", "unresolved_timeout", "unresolved_tls"):
            attempt.return_value = {"outcome": outcome}
            self.assertEqual(check("https://example.test", retry=True)["classification"], "unresolved")
        attempt.return_value = {"outcome": "dead_http"}
        self.assertEqual(check("https://example.test", retry=True)["classification"], "dead_confirmed")

    def test_high_confidence_parking_page(self):
        self.assertIsNotNone(parked_page("https://example.test", "<title>This domain is for sale</title>"))
        self.assertIsNone(parked_page("https://example.test", "<title>Coral Diving</title>"))


if __name__ == "__main__":
    unittest.main()
