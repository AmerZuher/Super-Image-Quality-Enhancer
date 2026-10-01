"""SIQE Studio backend."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("siqe")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
