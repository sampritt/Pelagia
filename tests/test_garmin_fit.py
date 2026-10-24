import copy
import math
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from garmin_fit_sdk import Encoder

from pelagia.garmin_fit import FitImportError, nearest_dive_site, parse_garmin_fit, validate_computer_data


START = datetime(2026, 10, 10, 2, tzinfo=timezone.utc)


def fit_messages():
    return [
        {"mesg_num": 0, "type": "activity", "manufacturer": "garmin"},
        {"mesg_num": 18, "message_index": 0, "sport": "diving", "sub_sport": "single_gas_diving",
         "start_time": START, "timestamp": START + timedelta(seconds=3251),
         "total_timer_time": 3251.103, "total_elapsed_time": 3251.103, "avg_temperature": 28,
         "end_position_lat": -4734621, "end_position_long": -1077937447},
        {"mesg_num": 19, "message_index": 0},
        {"mesg_num": 268, "reference_mesg": "lap", "reference_index": 0,
         "max_depth": 99, "avg_depth": 50, "bottom_time": 999},
        {"mesg_num": 268, "reference_mesg": "session", "reference_index": 0,
         "max_depth": 21.038, "avg_depth": 13.049, "bottom_time": 3189.786},
        {"mesg_num": 259, "message_index": 0, "oxygen_content": 33, "helium_content": 0,
         "status": "enabled", "mode": "open_circuit"},
        {"mesg_num": 21, "event": "dive_gas_switched", "data": 0, "timestamp": START},
        *[{"mesg_num": 20, "timestamp": START + timedelta(seconds=t), "depth": d, "temperature": temp}
          for t, d, temp in [(0, 0, 29), (1, 20, 28), (4, 10, 26), (3250, 0, 29)]],
        {"mesg_num": 34, "timestamp": START + timedelta(seconds=3251),
         "local_timestamp": int((START + timedelta(seconds=3251, hours=-6)
                                 - datetime(1989, 12, 31, tzinfo=timezone.utc)).total_seconds())},
    ]


def make_fit(messages=None):
    encoder = Encoder()
    for message in messages if messages is not None else fit_messages():
        encoder.write_mesg(message)
    return bytes(encoder.close())


class GarminParserTest(unittest.TestCase):
    def test_normalized_fields_and_exact_profile(self):
        result = parse_garmin_fit(make_fit())
        fields = result["fields"]
        self.assertEqual({key: fields[key] for key in ["depth_m", "average_depth_m", "duration_min", "date",
                                                       "oxygen_pct", "helium_pct", "nitrogen_pct", "water_temp_c"]},
                         {"depth_m": 21.038, "average_depth_m": 13.049, "duration_min": 53,
                          "date": "2026-10-09", "oxygen_pct": 33, "helium_pct": 0, "nitrogen_pct": 67, "water_temp_c": 28})
        self.assertNotIn("air_temp_c", fields)
        self.assertAlmostEqual(fields["latitude"], -0.39685134775936604)
        self.assertAlmostEqual(fields["longitude"], -90.35167305730283)
        data = result["computer_data"]
        self.assertEqual(data["bottom_time_seconds"], 3189.786)
        self.assertEqual(data["recording_duration_seconds"], 3251.103)
        self.assertEqual([point["elapsed_seconds"] for point in data["depth_profile"]], [0, 1, 4, 3250])
        self.assertEqual(data, validate_computer_data(data))

    def test_fallbacks_use_elapsed_time_and_utc_date(self):
        messages = [message for message in fit_messages() if message["mesg_num"] not in (268, 34)]
        session = messages[1]
        session.pop("avg_temperature")
        records = [message for message in messages if message["mesg_num"] == 20]
        records[-1]["timestamp"] = START + timedelta(seconds=8)
        result = parse_garmin_fit(make_fit(messages))
        self.assertEqual(result["fields"]["depth_m"], 20)
        self.assertEqual(result["fields"]["average_depth_m"], 9.375)
        self.assertEqual(result["fields"]["water_temp_c"], 27)
        self.assertEqual(result["fields"]["date"], "2026-10-10")
        self.assertEqual(result["computer_data"]["bottom_time_seconds"], 3251.103)

    def test_coordinate_precedence_and_zero_coordinates(self):
        messages = fit_messages()
        messages[1].update(start_position_lat=0, start_position_long=0)
        messages[7].update(position_lat=1000, position_long=2000)
        self.assertEqual(parse_garmin_fit(make_fit(messages))["fields"]["latitude"], 0)
        messages[1].pop("start_position_lat")
        result = parse_garmin_fit(make_fit(messages))
        self.assertAlmostEqual(result["fields"]["latitude"], 1000 * 180 / 2**31)

    def test_missing_optional_data_does_not_invent_values(self):
        messages = [message for message in fit_messages() if message["mesg_num"] != 259]
        messages[1].pop("end_position_lat")
        messages[1].pop("avg_temperature")
        for message in messages:
            message.pop("temperature", None)
        result = parse_garmin_fit(make_fit(messages))
        for field in ("latitude", "longitude", "oxygen_pct", "helium_pct", "water_temp_c", "air_temp_c"):
            self.assertNotIn(field, result["fields"])
        self.assertTrue(any("GPS" in notice for notice in result["notices"]))

    def test_missing_records_can_use_summary_without_inventing_profile(self):
        messages = [message for message in fit_messages() if message["mesg_num"] != 20]
        result = parse_garmin_fit(make_fit(messages))
        self.assertEqual(result["computer_data"]["depth_profile"], [])
        self.assertTrue(any("No depth profile" in notice for notice in result["notices"]))

    def test_corrupt_truncated_and_wrong_type_files(self):
        valid = make_fit()
        for data in (b"hello", valid[:-1], valid[:60] + bytes([valid[60] ^ 1]) + valid[61:]):
            with self.subTest(length=len(data)), self.assertRaises(FitImportError):
                parse_garmin_fit(data)
        messages = fit_messages()
        messages[0]["manufacturer"] = "suunto"
        with self.assertRaisesRegex(FitImportError, "Garmin"):
            parse_garmin_fit(make_fit(messages))
        messages[0].update(manufacturer="garmin", type="settings")
        with self.assertRaisesRegex(FitImportError, "activity"):
            parse_garmin_fit(make_fit(messages))

    def test_unsupported_modes_sessions_and_gas_switches(self):
        for sport, sub_sport in [("swimming", "generic"), ("diving", "multi_gas_diving"),
                                ("diving", "apnea_diving"), ("diving", "ccr_diving")]:
            messages = fit_messages()
            messages[1].update(sport=sport, sub_sport=sub_sport)
            with self.subTest(sub_sport=sub_sport), self.assertRaisesRegex(FitImportError, "single-gas"):
                parse_garmin_fit(make_fit(messages))
        messages = fit_messages()
        messages.append(copy.deepcopy(messages[1]))
        with self.assertRaisesRegex(FitImportError, "one dive session"):
            parse_garmin_fit(make_fit(messages))
        for extra in [{"mesg_num": 259, "message_index": 1, "oxygen_content": 100, "status": "enabled"},
                      {"mesg_num": 21, "event": "dive_gas_switched", "data": 1, "timestamp": START}]:
            with self.subTest(extra=extra), self.assertRaisesRegex(FitImportError, "single-gas"):
                parse_garmin_fit(make_fit(fit_messages() + [extra]))
        messages = fit_messages()
        messages[5]["mode"] = "closed_circuit_diluent"
        with self.assertRaisesRegex(FitImportError, "closed-circuit"):
            parse_garmin_fit(make_fit(messages))

    def test_missing_required_depth_and_timing(self):
        messages = [message for message in fit_messages() if message["mesg_num"] not in (268, 20)]
        with self.assertRaisesRegex(FitImportError, "depth or duration"):
            parse_garmin_fit(make_fit(messages))
        messages = [message for message in fit_messages() if message["mesg_num"] != 20]
        messages[1].pop("start_time")
        with self.assertRaisesRegex(FitImportError, "start time"):
            parse_garmin_fit(make_fit(messages))

    def test_profile_submission_validation(self):
        good = parse_garmin_fit(make_fit())["computer_data"]
        for mutation in [lambda data: data.update(version=2), lambda data: data.update(started_at="invalid"),
                         lambda data: data.update(bottom_time_seconds=math.nan),
                         lambda data: data["depth_profile"][1].update(depth_m=-1),
                         lambda data: data["depth_profile"][1].update(elapsed_seconds=999999),
                         lambda data: data["depth_profile"][2].update(elapsed_seconds=0)]:
            data = copy.deepcopy(good)
            mutation(data)
            with self.assertRaises(FitImportError):
                validate_computer_data(data)

    @unittest.skipUnless(os.environ.get("PELAGIA_GARMIN_SAMPLE"), "Personal sample is supplied only for local acceptance")
    def test_real_sample_acceptance(self):
        result = parse_garmin_fit(Path(os.environ["PELAGIA_GARMIN_SAMPLE"]).read_bytes())
        self.assertEqual(result["fields"]["date"], "2026-10-09")
        self.assertEqual(result["fields"]["depth_m"], 21.038)
        self.assertEqual(result["fields"]["average_depth_m"], 13.049)
        self.assertEqual(result["fields"]["duration_min"], 53)
        self.assertEqual(result["fields"]["oxygen_pct"], 33)
        self.assertEqual(result["fields"]["water_temp_c"], 28)
        self.assertNotIn("air_temp_c", result["fields"])
        self.assertEqual(result["computer_data"]["bottom_time_seconds"], 3189.786)
        self.assertEqual(len(result["computer_data"]["depth_profile"]), 2959)


class NearestSiteTest(unittest.TestCase):
    def test_global_search_wraps_longitude_and_breaks_ties_by_id(self):
        rows = [{"id": 3, "latitude": 0, "longitude": -179.9},
                {"id": 2, "latitude": 0, "longitude": -179.9},
                {"id": 1, "latitude": 0, "longitude": 170},
                {"id": 4, "latitude": None, "longitude": 179.9},
                {"id": 5, "latitude": math.nan, "longitude": 179.9},
                {"id": 6, "latitude": 99, "longitude": 179.9}]
        nearest = nearest_dive_site(0, 179.9, rows)
        self.assertEqual(nearest["id"], 2)
        self.assertAlmostEqual(nearest["distance_m"], 22238.974, places=2)
        self.assertIsNone(nearest_dive_site(None, 0, rows))
        self.assertIsNone(nearest_dive_site(0, 0, []))

    def test_sample_coordinates_match_daphne(self):
        fields = parse_garmin_fit(make_fit())["fields"]
        site = nearest_dive_site(fields["latitude"], fields["longitude"], [
            {"id": 2544, "name": "Daphne", "latitude": -0.39688, "longitude": -90.35088},
            {"id": 3248, "name": "Daphne Minor", "latitude": -0.4, "longitude": -90.37},
        ])
        self.assertEqual(site["name"], "Daphne")
        self.assertAlmostEqual(site["distance_m"], 88.24, places=2)
