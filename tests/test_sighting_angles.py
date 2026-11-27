import unittest

from scripts.sighting_angles import reported_angles


class SightingAnglesTests(unittest.TestCase):
    def test_pair_and_poles(self):
        rows = reported_angles("I saw a light at azimuth 360 and 15 degrees below the horizon.")
        self.assertEqual([(r["azimuth"], r["elevation"]) for r in rows], [(0, -15)])

    def test_angles_before_axis_names(self):
        rows = reported_angles("The object appeared at 285 degrees azimuth and 20 degrees elevation.")
        self.assertEqual([(r['azimuth'], r['elevation']) for r in rows], [(285, 20)])

    def test_adjacent_readings_and_ranges(self):
        rows = reported_angles("Star shaped object 120 degrees azimuth 75 degrees elevation.")
        self.assertEqual([(r['azimuth'], r['elevation']) for r in rows], [(120, 75)])
        self.assertFalse(reported_angles("The lights were 15-20 degrees of elevation and 245 to 260 degrees of azimuth."))

    def test_partial_and_ambiguous_directions(self):
        rows = reported_angles("I saw an object looking southwest. I saw lights at bearing 20 and bearing 40.")
        self.assertEqual([r["azimuth"] for r in rows], [225, 20, 40])
        self.assertTrue(all(r["elevation"] is None for r in rows))
        self.assertEqual(rows[0]["basis"], "reported compass sector")

    def test_reject_invalid_angles_and_unrelated_measurements(self):
        self.assertFalse(reported_angles("The antenna elevation was 45 degrees. A UFO was mentioned."))
        self.assertFalse(reported_angles("I saw a light at azimuth 361 at 91 degrees above the horizon."))
