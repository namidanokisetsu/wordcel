import threading
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from wordcel.utils.capture import CaptureRequest, RegionCapture, _screen_geometry


class RegionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows capture diagnostics")
    def test_exclusion_failure_records_native_error(self):
        import ctypes
        from wordcel.utils.capture import exclude_from_capture
        user32 = Mock()
        def reject(*args):
            ctypes.set_last_error(87)
            return False
        user32.SetWindowDisplayAffinity.side_effect = reject
        with patch("ctypes.WinDLL", return_value=user32), \
                patch("sys.getwindowsversion", return_value=SimpleNamespace(build=19041)), \
                patch("wordcel.utils.timing.mark") as trace:
            self.assertFalse(exclude_from_capture(Mock(winId=lambda: 123), True))
        trace.assert_called_once_with("capture_exclusion", enabled=True, accepted=False, error=87)

    def test_closed_source_cleanup_does_not_abort_worker_invalidation(self):
        capture = RegionCapture()
        capture.window = Mock()
        capture.window.reset.side_effect = OSError("already closed")
        capture._failed = ((1, 123), OSError())
        capture.reset()
        self.assertIsNone(capture._failed)
        capture.close()

    def test_source_window_pixels_retain_screen_coordinates_without_popup(self):
        from PIL import Image
        request = CaptureRequest(1, "screen", (-100, 0, 200, 100), (-100, 0, 200, 100), 1.5, 2,
                                 source_window=123)
        source = Mock()
        source.capture.return_value = ((-70, 30, 120, 60), Image.new("RGB", (120, 60), "red"))
        with patch("wordcel.utils.window_capture.WindowCapture", return_value=source) as create, \
                patch("wordcel.utils.capture.windows_screen_geometry", return_value=(-100, 0, 300, 150)), \
                patch("mss.mss") as desktop:
            capture = RegionCapture()
            try:
                for _ in range(2):
                    frame = capture.capture(request)
                    self.assertEqual(frame.physical_crop, (-100, 0, 300, 150))
                    self.assertEqual(frame.image().getpixel((30, 30)), (255, 0, 0))
                    self.assertEqual(frame.image().getpixel((149, 89)), (255, 0, 0))
                    self.assertEqual(frame.image().getpixel((150, 90)), (0, 0, 0))
                    self.assertEqual(frame.image().getpixel((0, 0)), (0, 0, 0))
                create.assert_called_once()
                desktop.assert_not_called()
            finally:
                capture.close()
            source.close.assert_called_once()

    def test_failed_exclusion_masks_popup_in_physical_pixels_without_wgc(self):
        request = CaptureRequest(1, "screen", (-100, 0, 200, 100), (-100, 0, 200, 100), 1.5, 2,
                                 mask_window=456)
        backend = Mock()
        backend.grab.return_value = SimpleNamespace(bgra=bytes([10, 20, 30, 255]) * (300 * 150))
        with patch("mss.mss", return_value=backend), \
                patch("wordcel.utils.capture.windows_screen_geometry", return_value=(-100, 0, 300, 150)), \
                patch("wordcel.utils.window_capture.window_bounds", return_value=(-70, 30, 120, 60)), \
                patch("wordcel.utils.window_capture.WindowCapture", side_effect=AssertionError("Unexpected WGC")):
            capture = RegionCapture()
            try:
                for _ in range(2):
                    frame = capture.capture(request)
                    image = frame.image()
                    self.assertEqual(frame.physical_crop, (-100, 0, 300, 150))
                    self.assertEqual(image.getpixel((29, 30)), (30, 20, 10))
                    self.assertEqual(image.getpixel((30, 30)), (0, 0, 0))
                    self.assertEqual(image.getpixel((149, 89)), (0, 0, 0))
                    self.assertEqual(image.getpixel((150, 90)), (30, 20, 10))
                    # The full image kept for Anki must have the same redaction.
                    selected = frame.cropped(replace(request, crop=(-100, 0, 100, 100)))
                    self.assertEqual(selected.image().getpixel((30, 30)), (0, 0, 0))
            finally:
                capture.close()

    def test_mask_tracks_popup_movement_and_clips_to_capture(self):
        request = CaptureRequest(1, "screen", (0, 0, 4, 2), (0, 0, 4, 2), 1, 2, mask_window=456)
        backend = Mock()
        backend.grab.return_value = SimpleNamespace(bgra=bytes([255, 255, 255, 255]) * 8)
        with patch("mss.mss", return_value=backend), \
                patch("wordcel.utils.capture.windows_screen_geometry", return_value=request.geometry), \
                patch("wordcel.utils.window_capture.window_bounds",
                      side_effect=[(-1, -1, 2, 2), (3, 1, 3, 3), RuntimeError("hidden"), RuntimeError("hidden")]):
            capture = RegionCapture()
            try:
                image = capture.capture(request).image()
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
                self.assertEqual(image.getpixel((3, 1)), (0, 0, 0))
                self.assertEqual(image.getpixel((1, 0)), (255, 255, 255))
                image = capture.capture(request).image()
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(image.getpixel((3, 1)), (255, 255, 255))
            finally:
                capture.close()

    def test_failed_source_retries_only_after_source_or_session_changes(self):
        request = CaptureRequest(1, "screen", (0, 0, 20, 20), (0, 0, 20, 20), 1, 2, source_window=123)
        source = Mock()
        source.capture.side_effect = OSError("fixture")
        with patch("wordcel.utils.window_capture.WindowCapture", return_value=source) as create, \
                patch("wordcel.utils.capture.windows_screen_geometry", return_value=request.geometry):
            capture = RegionCapture()
            for current in (request, request, replace(request, source_window=456), replace(request, generation=3)):
                with self.assertRaisesRegex(RuntimeError, "cannot be captured"):
                    capture.capture(current)
            self.assertEqual(create.call_count, 3)
            self.assertEqual(source.close.call_count, 3)
            capture.reset()
            with self.assertRaises(RuntimeError):
                capture.capture(request)
            self.assertEqual(create.call_count, 4)
            capture.close()

    def test_frame_identity_distinguishes_identical_content_in_different_windows(self):
        from wordcel.ocr.frames import RecognizedFrame
        request = CaptureRequest(1, "screen", (0, 0, 20, 20), (0, 0, 20, 20), 1, 2, source_window=123)
        frame = RecognizedFrame(request, (), "ja", (), 1, 0)
        self.assertNotEqual(frame.identity, replace(frame, request=replace(request, source_window=456)).identity)

    def test_qt_friendly_monitor_name_maps_at_fractional_scale(self):
        monitors = {r"\\.\DISPLAY1": (0, 0, 3440, 1440)}
        self.assertEqual(_screen_geometry("ZQE-CAA", monitors, (0, 0, 2293, 960), 1.5),
                         (0, 0, 3440, 1440))

    def test_friendly_name_mapping_retains_negative_native_origins(self):
        monitors = {"left": (-1920, -100, 1920, 1080), "right": (0, 0, 2560, 1440)}
        self.assertEqual(_screen_geometry("friendly", monitors, (-1920, -100, 1280, 720), 1.5),
                         (-1920, -100, 1920, 1080))
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (-1920, -100, 1280, 720), 2)
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (-1919, -100, 1280, 720), 1.5)

    def test_ambiguous_or_missing_monitor_is_rejected(self):
        monitors = {"one": (0, 0, 1920, 1080), "two": (0, 0, 1920, 1080)}
        with self.assertRaisesRegex(RuntimeError, "Display changed"):
            _screen_geometry("friendly", monitors, (0, 0, 1920, 1080))
        self.assertEqual(_screen_geometry("one", monitors), monitors["one"])

    def test_negative_origin_and_mixed_scale(self):
        request = CaptureRequest(1, "screen", (-1920, -100, 1280, 720), (-1800, 0, 400, 200), 1.5, 2)
        self.assertEqual(request.physical_crop((-1920, -100, 1920, 1080)), (-1740, 50, 600, 300))

    def test_capture_owns_buffer_and_closes_backend_on_its_thread(self):
        calls = []
        pixels = bytearray([0, 0, 255, 0] * 4)
        backend = Mock()
        backend.grab.side_effect = lambda region: (calls.append(threading.get_ident()) or SimpleNamespace(bgra=pixels))
        backend.close.side_effect = lambda: calls.append(threading.get_ident())
        frames = []
        request = CaptureRequest(1, "screen", (0, 0, 2, 2), (0, 0, 2, 2), 1, 1)
        def run():
            capture = RegionCapture()
            try:
                frames.append(capture.capture(request))
            finally:
                capture.close()
        with patch("mss.mss", return_value=backend), patch("wordcel.utils.capture.windows_screen_geometry", return_value=(0, 0, 2, 2)):
            worker = threading.Thread(target=run)
            worker.start()
            worker.join(2)
        pixels[:] = bytes(len(pixels))
        self.assertEqual(frames[0].image().getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(calls, [worker.ident, worker.ident])
        self.assertNotEqual(worker.ident, threading.get_ident())
