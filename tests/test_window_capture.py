import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wordcel.utils.window_capture import WindowCapture


class Pixels(bytearray):
    def close(self):
        self.closed = True


class WindowCaptureTests(unittest.TestCase):
    def setUp(self):
        runtime = SimpleNamespace(ApartmentType=SimpleNamespace(MULTI_THREADED=1),
                                  init_apartment=Mock(), uninit_apartment=Mock())
        self.bitmap = Mock()
        self.modules = patch.dict(sys.modules, {
            "winrt.runtime": runtime,
            "winrt.windows.graphics.directx": SimpleNamespace(
                DirectXPixelFormat=SimpleNamespace(B8_G8_R8_A8_UINT_NORMALIZED=87)),
            "winrt.windows.graphics.imaging": SimpleNamespace(
                BitmapBufferAccessMode=SimpleNamespace(READ=1),
                SoftwareBitmap=SimpleNamespace(create_copy_from_surface_async=self.bitmap)),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.capture = WindowCapture()
        self.capture.handle = 123
        self.capture.device = Mock()
        self.capture.pool = Mock()
        self.capture._size = SimpleNamespace(width=4, height=2)
        self.addCleanup(self.capture.close)
        bounds = patch("wordcel.utils.window_capture.window_bounds", return_value=(10, 20, 4, 2))
        self.bounds = bounds.start()
        self.addCleanup(bounds.stop)

    def image(self, color, size=(4, 2)):
        width, height = size
        stride = width * 4 + 4
        data = Pixels(b"head" + (bytes((*color[::-1], 255)) * width + b"pad!") * height)
        buffer = Mock()
        buffer.get_plane_description.return_value = SimpleNamespace(
            start_index=4, width=width, height=height, stride=stride)
        buffer.create_reference.return_value = data
        bitmap = Mock()
        bitmap.lock_buffer.return_value = buffer
        self.bitmap.return_value.get.return_value = bitmap
        return bitmap, buffer, data

    def test_newest_frame_is_copied_with_stride_and_static_pixels_are_reused(self):
        old, new = Mock(content_size=self.capture._size), Mock(content_size=self.capture._size)
        bitmap, buffer, data = self.image((10, 20, 30))
        self.capture.pool.try_get_next_frame.side_effect = [old, new, None]
        bounds, image = self.capture.capture(123)
        self.assertEqual(bounds, (10, 20, 4, 2))
        self.assertEqual(image.getpixel((3, 1)), (10, 20, 30))
        self.bitmap.assert_called_once_with(new.surface)
        old.close.assert_called_once()
        new.close.assert_called_once()
        bitmap.close.assert_called_once()
        buffer.close.assert_called_once()
        self.assertTrue(data.closed)
        data[:] = bytes(len(data))
        self.assertEqual(self.capture.capture(123)[1].getpixel((3, 1)), (10, 20, 30))
        self.assertEqual(self.bitmap.call_count, 1)

    def test_resize_closes_old_frame_before_restarting_session(self):
        size = SimpleNamespace(width=6, height=3)
        first, second = Mock(content_size=size), Mock(content_size=size)
        self.image((40, 50, 60), (6, 3))
        self.bounds.side_effect = [(10, 20, 4, 2), (10, 20, 6, 3), (10, 20, 6, 3)]
        self.capture.pool.try_get_next_frame.side_effect = [first, None, second, None, None]
        def restart(handle):
            first.close.assert_called_once()
            self.capture._size = size
        with patch.object(self.capture, "_start", side_effect=restart) as start:
            bounds, image = self.capture.capture(123)
            start.assert_called_once_with(123)
        self.assertEqual(image.size, (6, 3))

    def test_closed_window_does_not_return_cached_pixels(self):
        self.capture._ended.set()
        with self.assertRaisesRegex(RuntimeError, "no longer available"):
            self.capture.capture(123)
        self.capture.pool.try_get_next_frame.assert_not_called()

    def test_first_frame_wait_is_bounded(self):
        self.capture.pool.try_get_next_frame.return_value = None
        self.capture._ready = Mock()
        with patch("wordcel.utils.window_capture.monotonic", side_effect=[0, 0, .2, 1.1]):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                self.capture.capture(123)
        self.capture._ready.wait.assert_called_once_with(.8)

    def test_reset_releases_session_but_retains_prepared_device(self):
        session, pool, item = Mock(), self.capture.pool, Mock()
        self.capture.session, self.capture.item = session, item
        self.capture._arrived, self.capture._closed = 11, 12
        self.capture.reset()
        pool.remove_frame_arrived.assert_called_once_with(11)
        item.remove_closed.assert_called_once_with(12)
        session.close.assert_called_once()
        pool.close.assert_called_once()
        self.capture.device.close.assert_not_called()
        self.assertEqual(self.capture.handle, 0)

    def test_cleanup_error_still_closes_session_and_pool(self):
        pool, session = self.capture.pool, Mock()
        self.capture.session = session
        self.capture._arrived = 11
        pool.remove_frame_arrived.side_effect = OSError("closed")
        with self.assertRaises(OSError):
            self.capture.reset()
        pool.close.assert_called_once()
        session.close.assert_called_once()
        self.assertIsNone(self.capture.pool)
