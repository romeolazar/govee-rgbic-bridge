import os
import unittest
from unittest.mock import patch

from govee_bridge import Settings, decode_colors, smooth_colors


class SettingsTests(unittest.TestCase):
    def test_device_ip_is_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "GOVEE_IP is required"):
                Settings.from_env()

    def test_environment_configuration(self):
        with patch.dict(
            os.environ,
            {
                "GOVEE_IP": "192.0.2.10",
                "SEGMENTS_PER_BAR": "6",
                "REVERSE_RIGHT": "true",
            },
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.govee_ip, "192.0.2.10")
        self.assertEqual(settings.segments_per_bar, 6)
        self.assertTrue(settings.reverse_right)


class DecodeTests(unittest.TestCase):
    def test_segment_order_and_right_reversal(self):
        settings = Settings(
            govee_ip="192.0.2.10",
            segments_per_bar=10,
            reverse_right=True,
        )
        payload = bytes(
            channel
            for index in range(20)
            for channel in (index, index + 20, index + 40)
        )

        left, right, mode = decode_colors(payload, settings)

        self.assertEqual(mode, "20-segment")
        self.assertEqual(left[0], (0, 20, 40))
        self.assertEqual(left[-1], (9, 29, 49))
        self.assertEqual(right[0], (19, 39, 59))
        self.assertEqual(right[-1], (10, 30, 50))

    def test_two_zone_input_expands_to_all_segments(self):
        settings = Settings(govee_ip="192.0.2.10", segments_per_bar=4)
        left, right, mode = decode_colors(bytes([1, 2, 3, 4, 5, 6]), settings)
        self.assertEqual(mode, "2-zone")
        self.assertEqual(left, [(1, 2, 3)] * 4)
        self.assertEqual(right, [(4, 5, 6)] * 4)

    def test_invalid_packet_is_ignored(self):
        settings = Settings(govee_ip="192.0.2.10")
        self.assertIsNone(decode_colors(b"invalid", settings))


class SmoothingTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(govee_ip="192.0.2.10")

    def test_fast_attack_and_slower_release(self):
        state = [[0.0, 0.0, 0.0] for _ in range(20)]
        state, attack = smooth_colors(
            state, [(255, 255, 255)] * 20, 0.15, self.settings
        )
        self.assertTrue(all(235 <= value <= 255 for rgb in attack for value in rgb))

        _state, release = smooth_colors(
            state, [(0, 0, 0)] * 20, 0.35, self.settings
        )
        self.assertTrue(all(0 <= value <= 20 for rgb in release for value in rgb))

    def test_smoothing_can_be_disabled(self):
        settings = Settings(govee_ip="192.0.2.10", adaptive_smoothing=False)
        _state, result = smooth_colors(
            [[0.0, 0.0, 0.0]], [(10, 20, 30)], 0.01, settings
        )
        self.assertEqual(result, [(10, 20, 30)])


if __name__ == "__main__":
    unittest.main()
