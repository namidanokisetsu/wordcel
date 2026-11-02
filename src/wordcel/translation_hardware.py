"""Worker-only local driver probes. Inference reads installed backend identity."""
from dataclasses import dataclass
import ctypes
import sys
import subprocess


@dataclass(frozen=True)
class Capabilities:
    cuda: bool = False
    vulkan: bool = False
    memory: int | None = None
    gpu_memory: int | None = None
    cuda_reason: str = "A compatible CUDA 13.4 driver/device was not found"
    vulkan_reason: str = "A compatible Vulkan 1.2 device was not found"

    def select(self, backend="automatic"):
        if backend == "automatic":
            return "cuda" if self.cuda else "vulkan" if self.vulkan else "cpu"
        if backend not in {"cpu", "cuda", "vulkan"}:
            raise ValueError("Choose Automatic, CPU, Vulkan or CUDA")
        if backend == "cuda" and not self.cuda:
            raise RuntimeError(self.cuda_reason + ". Choose CPU or Automatic.")
        if backend == "vulkan" and not self.vulkan:
            raise RuntimeError(self.vulkan_reason + ". Choose CPU or Automatic.")
        return backend


def _cuda():
    # Query the driver directly; nvidia-smi need not be installed or on PATH.
    driver = ctypes.WinDLL("nvcuda.dll")
    version, count = ctypes.c_int(), ctypes.c_int()
    if driver.cuInit(0) or driver.cuDriverGetVersion(ctypes.byref(version)) or version.value < 13040:
        return None
    if driver.cuDeviceGetCount(ctypes.byref(count)):
        return None
    for device in range(count.value):
        major, minor, memory = ctypes.c_int(), ctypes.c_int(), ctypes.c_size_t()
        if not driver.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), device) \
                and (major.value, minor.value) >= (7, 5) \
                and not driver.cuDeviceTotalMem_v2(ctypes.byref(memory), device):
            return memory.value
    return None


def _vulkan():
    vk = ctypes.WinDLL("vulkan-1.dll")
    class Application(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("name", ctypes.c_char_p),
                    ("version", ctypes.c_uint32), ("engine", ctypes.c_char_p),
                    ("engine_version", ctypes.c_uint32), ("api", ctypes.c_uint32)]
    class Instance(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                    ("app", ctypes.POINTER(Application)), ("layer_count", ctypes.c_uint32),
                    ("layers", ctypes.c_void_p), ("extension_count", ctypes.c_uint32), ("extensions", ctypes.c_void_p)]
    class Storage16(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("storage", ctypes.c_uint32),
                    ("uniform", ctypes.c_uint32), ("push", ctypes.c_uint32), ("io", ctypes.c_uint32)]
    class Features(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("features", ctypes.c_uint32 * 55)]
    app = Application(type=0, name=b"Wordcel", api=(1 << 22) | (2 << 12))
    info = Instance(type=1, app=ctypes.pointer(app))
    instance = ctypes.c_void_p()
    if vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)):
        return False
    try:
        count = ctypes.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None) or not count.value:
            return False
        devices = (ctypes.c_void_p * count.value)()
        if vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices):
            return False
        for device in devices:
            # VkPhysicalDeviceProperties is larger than the inspected prefix.
            properties = (ctypes.c_uint32 * 1024)()
            vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(device), ctypes.byref(properties))
            storage = Storage16(type=1000083000)
            features = Features(type=1000059000, next=ctypes.cast(ctypes.pointer(storage), ctypes.c_void_p))
            vk.vkGetPhysicalDeviceFeatures2(ctypes.c_void_p(device), ctypes.byref(features))
            # Exclude software devices, require shaderInt16 and 16-bit storage.
            if properties[0] < app.api or properties[4] not in (1, 2) or not features.features[41] or not storage.storage:
                continue
            class Extension(ctypes.Structure):
                _fields_ = [("name", ctypes.c_char * 256), ("version", ctypes.c_uint32)]
            extension_count = ctypes.c_uint32()
            physical = ctypes.c_void_p(device)
            if vk.vkEnumerateDeviceExtensionProperties(physical, None, ctypes.byref(extension_count), None):
                continue
            extensions = (Extension * extension_count.value)()
            if vk.vkEnumerateDeviceExtensionProperties(physical, None, ctypes.byref(extension_count), extensions) \
                    or b"VK_KHR_16bit_storage" not in [extension.name for extension in extensions]:
                continue
            class QueueFamily(ctypes.Structure):
                _fields_ = [("flags", ctypes.c_uint32), ("count", ctypes.c_uint32),
                            ("timestamp", ctypes.c_uint32), ("granularity", ctypes.c_uint32 * 3)]
            queue_count = ctypes.c_uint32()
            vk.vkGetPhysicalDeviceQueueFamilyProperties(physical, ctypes.byref(queue_count), None)
            queues = (QueueFamily * queue_count.value)()
            vk.vkGetPhysicalDeviceQueueFamilyProperties(physical, ctypes.byref(queue_count), queues)
            index = next((i for i, queue in enumerate(queues) if queue.flags & 2 and queue.count), None)
            if index is None:
                continue
            class QueueInfo(ctypes.Structure):
                _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                            ("family", ctypes.c_uint32), ("count", ctypes.c_uint32), ("priority", ctypes.POINTER(ctypes.c_float))]
            class DeviceInfo(ctypes.Structure):
                _fields_ = [("type", ctypes.c_uint32), ("next", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                            ("queue_count", ctypes.c_uint32), ("queues", ctypes.POINTER(QueueInfo)),
                            ("layer_count", ctypes.c_uint32), ("layers", ctypes.c_void_p),
                            ("extension_count", ctypes.c_uint32), ("extensions", ctypes.POINTER(ctypes.c_char_p)),
                            ("features", ctypes.c_void_p)]
            priority = ctypes.c_float(1)
            queue = QueueInfo(type=2, family=index, count=1, priority=ctypes.pointer(priority))
            enabled = (ctypes.c_char_p * 1)(b"VK_KHR_16bit_storage")
            required = Storage16(type=1000083000, storage=1)
            info = DeviceInfo(type=3, next=ctypes.cast(ctypes.pointer(required), ctypes.c_void_p),
                              queue_count=1, queues=ctypes.pointer(queue), extension_count=1, extensions=enabled)
            logical = ctypes.c_void_p()
            if not vk.vkCreateDevice(physical, ctypes.byref(info), None, ctypes.byref(logical)):
                vk.vkDestroyDevice(logical, None)
                return True
        return False
    finally:
        vk.vkDestroyInstance(instance, None)


def system_memory():
    try:
        if sys.platform == "win32":
            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in ("total", "available", "page", "page_available", "virtual", "virtual_available", "extended")]
            status = Status()
            status.length = ctypes.sizeof(status)
            return status.available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
        if sys.platform == "darwin":
            import subprocess
            # Free + inactive pages are reclaimable without counting swap.
            output = subprocess.check_output(["/usr/bin/vm_stat"], text=True, timeout=3)
            import re
            page = int(re.search(r"page size of (\d+)", output)[1])
            return page * sum(int(re.search(rf"Pages {name}:\s+(\d+)", output)[1]) for name in ("free", "inactive"))
        import os
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return None


def detect_capabilities():
    memory, gpu_memory, vulkan = system_memory(), None, False
    if sys.platform == "win32":
        try:
            gpu_memory = _cuda()
        except (OSError, AttributeError):
            pass
        try:
            vulkan = _vulkan()
        except (OSError, AttributeError):
            pass
    return Capabilities(cuda=gpu_memory is not None, vulkan=vulkan, memory=memory, gpu_memory=gpu_memory)
