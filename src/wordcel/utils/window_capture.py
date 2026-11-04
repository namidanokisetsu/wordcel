"""Worker-owned Windows Graphics Capture sessions, independent of popup visibility."""
import ctypes
from ctypes import wintypes
from contextlib import ExitStack
import threading
from time import monotonic
from uuid import UUID


def window_at_point(point, excluded=0):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.WindowFromPhysicalPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPhysicalPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    handle = user32.WindowFromPhysicalPoint(wintypes.POINT(*point))
    handle = user32.GetAncestor(handle, 2) if handle else 0
    owner, own = wintypes.DWORD(), wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
    user32.GetWindowThreadProcessId(excluded, ctypes.byref(own))
    return handle if handle and handle != excluded and owner.value != own.value else 0


def window_bounds(handle):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = user32.IsIconic.argtypes = [wintypes.HWND]
    if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
        raise RuntimeError("Source window is no longer available.")
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    rect = wintypes.RECT()
    result = dwm.DwmGetWindowAttribute(handle, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    if result < 0:
        raise ctypes.WinError(result)
    bounds = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    if min(bounds[2:]) <= 0:
        raise RuntimeError("Source window is no longer available.")
    return bounds


def _com_method(pointer, index, result, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])


def _create_device():
    from winrt.windows.graphics.directx.direct3d11.interop import create_direct3d11_device_from_dxgi_device

    create = ctypes.WinDLL("d3d11").D3D11CreateDevice
    create.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.HMODULE, wintypes.UINT,
                       ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p]
    create.restype = ctypes.c_long
    device, dxgi = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        # BGRA support is required by the frame pool. WARP covers systems
        # where hardware device creation is unavailable.
        result = create(None, 1, None, 0x20, None, 0, 7, ctypes.byref(device), None, None)
        if result < 0:
            result = create(None, 5, None, 0x20, None, 0, 7, ctypes.byref(device), None, None)
        if result < 0:
            raise ctypes.WinError(result)
        iid = ctypes.create_string_buffer(UUID("54ec77fa-1377-44e6-8c32-88fd5f44c84c").bytes_le)
        query = _com_method(device, 0, ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        result = query(device, iid, ctypes.byref(dxgi))
        if result < 0:
            raise ctypes.WinError(result)
        return create_direct3d11_device_from_dxgi_device(dxgi.value)
    finally:
        for pointer in (dxgi, device):
            if pointer:
                _com_method(pointer, 2, wintypes.ULONG)(pointer)


def _frame_image(frame):
    from PIL import Image
    from winrt.windows.graphics.imaging import BitmapBufferAccessMode, SoftwareBitmap

    bitmap = SoftwareBitmap.create_copy_from_surface_async(frame.surface).get()
    try:
        buffer = bitmap.lock_buffer(BitmapBufferAccessMode.READ)
        try:
            plane = buffer.get_plane_description(0)
            reference = buffer.create_reference()
            try:
                pixels = bytes(memoryview(reference)[plane.start_index:])
                return Image.frombytes("RGB", (plane.width, plane.height), pixels, "raw", "BGRX", plane.stride)
            finally:
                reference.close()
        finally:
            buffer.close()
    finally:
        bitmap.close()


class WindowCapture:
    def __init__(self):
        from winrt.runtime import ApartmentType, init_apartment
        init_apartment(ApartmentType.MULTI_THREADED)
        self._apartment = True
        self.device = self.pool = self.session = self.item = None
        self.handle = 0
        self._arrived = self._closed = None
        self._ready = threading.Event()
        self._ended = threading.Event()
        self._latest = None
        self._size = None

    def _start(self, handle):
        from winrt.windows.graphics.capture import Direct3D11CaptureFramePool, GraphicsCaptureSession
        from winrt.windows.graphics.capture.interop import create_for_window
        from winrt.windows.graphics.directx import DirectXPixelFormat

        self.reset()
        if not GraphicsCaptureSession.is_supported():
            raise RuntimeError("Window capture is unavailable on this system.")
        if self.device is None:
            self.device = _create_device()
        self.handle = handle
        self.item = create_for_window(handle)
        self._size = self.item.size
        self.pool = Direct3D11CaptureFramePool.create_free_threaded(
            self.device, DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED, 2, self._size)
        self._ready, self._ended = threading.Event(), threading.Event()
        ready, ended = self._ready, self._ended
        self._arrived = self.pool.add_frame_arrived(lambda *_: ready.set())
        def closed(*_):
            ended.set()
            ready.set()
        self._closed = self.item.add_closed(closed)
        self.session = self.pool.create_capture_session(self.item)
        for option in ("is_cursor_capture_enabled", "is_border_required"):
            try:
                setattr(self.session, option, False)
            except (AttributeError, OSError):
                pass  # Older Windows versions retain their capture defaults.
        self.session.start_capture()

    def capture(self, handle):
        bounds = window_bounds(handle)
        if self.handle != handle or (self._size.width, self._size.height) != bounds[2:]:
            self._start(handle)
        deadline = monotonic() + 1
        while True:
            if monotonic() >= deadline:
                raise RuntimeError("Source window capture timed out.")
            if self._ended.is_set():
                raise RuntimeError("Source window is no longer available.")
            self._ready.clear()
            frame = self.pool.try_get_next_frame()
            if frame is not None:
                try:
                    # Consume the newest of the two buffered frames after OCR
                    # has been busy, rather than returning an older screen.
                    newer = self.pool.try_get_next_frame()
                    if newer is not None:
                        frame.close()
                        frame = newer
                    size = frame.content_size
                    if size == self._size:
                        self._latest = _frame_image(frame)
                finally:
                    frame.close()
                if size != self._size:
                    # Recreate alone may not produce another frame for a static
                    # window. A new session supplies its complete resized image.
                    self._start(handle)
                    continue
            current = window_bounds(handle)
            if current != bounds:
                bounds = current
                if (self._size.width, self._size.height) != bounds[2:]:
                    self._start(handle)
                continue
            if self._latest is not None and self._latest.size == bounds[2:]:
                return bounds, self._latest
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RuntimeError("Source window capture timed out.")
            self._ready.wait(remaining)

    def reset(self):
        pool, session, item = self.pool, self.session, self.item
        arrived, closed = self._arrived, self._closed
        self.pool = self.session = self.item = self._latest = None
        self._arrived = self._closed = None
        self.handle = 0
        self._ready.clear()
        self._ended.clear()
        with ExitStack() as cleanup:
            if pool is not None:
                cleanup.callback(pool.close)
            if session is not None:
                cleanup.callback(session.close)
            if item is not None and closed is not None:
                cleanup.callback(item.remove_closed, closed)
            if pool is not None and arrived is not None:
                cleanup.callback(pool.remove_frame_arrived, arrived)

    def close(self):
        from winrt.runtime import uninit_apartment
        try:
            try:
                self.reset()
            finally:
                if self.device is not None:
                    self.device.close()
                    self.device = None
        finally:
            if self._apartment:
                self._apartment = False
                uninit_apartment()
