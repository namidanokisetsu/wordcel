"""Lightweight readiness checks for shared lookup."""

import platform


TORCH_DEFAULT_VERSION = "2.8.0"
TORCH_INTEL_MAC_VERSION = "2.2.2"


def torch_version(system=None, machine=None):
    """Return the pinned source morphology wheel for a supported platform."""
    system = system or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    if system == "darwin" and machine in {"x86_64", "amd64"}:
        return TORCH_INTEL_MAC_VERSION
    return TORCH_DEFAULT_VERSION


def numpy_requirement(system=None, machine=None):
    """Return the NumPy ABI constraint paired with the selected Torch wheel."""
    system = system or platform.system().lower()
    machine = (machine or platform.machine()).lower()
    return "numpy<2" if system == "darwin" and machine in {"x86_64", "amd64"} else None


def model_available(language):
    if language == "tr":
        from .turkish_analyzer import available
        return available()
    from .stanza_analyzer import model_available as stanza_available
    return stanza_available(language)
