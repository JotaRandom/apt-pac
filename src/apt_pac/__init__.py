from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("apt-pac")
except PackageNotFoundError:
    __version__ = "2026.01.28"
