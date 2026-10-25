"""wordcel - Desktop OCR dictionary with multilingual Yomitan lookup."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wordcel")
except PackageNotFoundError:
    __version__ = "0+unknown"
USER_AGENT = f"wordcel/{__version__} (https://github.com/namidanokisetsu/wordcel)"

__author__ = "rtr46"
__license__ = "GPL-3.0"
