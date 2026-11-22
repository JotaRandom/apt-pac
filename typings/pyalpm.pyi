from typing import Any

PKG_REASON_EXPLICIT: int
PKG_REASON_DEPEND: int
PKG_VALIDATION_NONE: int
PKG_VALIDATION_MD5SUM: int
PKG_VALIDATION_SHA256SUM: int
PKG_VALIDATION_SIGNATURE: int
SIG_DATABASE_OPTIONAL: int

class error(Exception): ...

class Package:
    name: str
    version: str
    desc: str
    url: str | None
    licenses: list[str]
    groups: list[str]
    depends: list[str]
    optdepends: list[str]
    conflicts: list[str]
    provides: list[str]
    replaces: list[str]
    size: int
    download_size: int
    isize: int
    validation: int
    packager: str | None
    arch: str | None
    builddate: int
    installdate: int
    reason: int
    files: list[Any]
    db: DB | None
    has_scriptlet: bool
    md5sum: str | None
    sha256sum: str | None
    base: str | None
    def compute_requiredby(self) -> list[str]: ...
    def compute_optionalfor(self) -> list[str]: ...

class DB:
    name: str
    pkgcache: list[Package]
    servers: list[str]
    def get_pkg(self, pkgname: str) -> Package | None: ...
    def search(self, *needles: str) -> list[Package]: ...
    def read_grp(self, grpname: str) -> tuple[str, list[Package]] | None: ...

class Handle:
    cachedirs: list[str]
    arch: str
    checkspace: bool
    dbext: str
    ignorepkgs: list[str]
    ignoregrps: list[str]
    holdpkgs: list[str]
    def __init__(self, root: str, dbpath: str) -> None: ...
    def get_localdb(self) -> DB: ...
    def get_syncdbs(self) -> list[DB]: ...
    def register_syncdb(self, treename: str, level: int) -> DB: ...
    def add_cachedir(self, cachedir: str) -> None: ...

def find_satisfier(pkgs: list[Package], depstring: str) -> Package | None: ...
def vercmp(ver1: str, ver2: str) -> int: ...
def version() -> str: ...
