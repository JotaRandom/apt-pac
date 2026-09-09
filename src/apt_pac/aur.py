import json
import re
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
import subprocess
import os
import sys
import shutil
from pathlib import Path
from . import ui
from .ui import print_error, print_info, print_transaction_summary
from .i18n import _
from .config import get_config
import tarfile


def is_valid_package(path: str) -> bool:
    """
    Check if a file is a valid pacman package (compressed tar with .PKGINFO).
    Content-based check rather than extension.
    """
    if not os.path.isfile(path):
        return False

    try:
        with tarfile.open(path, "r:*") as tar:
            for member in tar:
                if member.name == ".PKGINFO":
                    return True
            return False
    except (tarfile.TarError, OSError, Exception):
        return False


class CyclicDependencyError(Exception):
    """Raised when a circular dependency is detected in AUR packages."""

    def __init__(self, cycle_path: List[str]):
        self.cycle = cycle_path
        cycle_str = " → ".join(cycle_path)
        super().__init__(f"Dependency cycle detected: {cycle_str}")


AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5/"
CACHE_FILE = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    / "apt-pac"
    / "rpc_cache.json"
)


def _load_cache() -> Dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: Dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _get_cached(key: str) -> Optional[List[Dict]]:
    config = get_config()
    ttl_minutes = config.get("performance", "rpc_cache_ttl", 30)
    ttl_seconds = ttl_minutes * 60

    cache = _load_cache()
    if key in cache:
        entry = cache[key]
        if time.time() - entry.get("timestamp", 0) < ttl_seconds:
            return entry.get("data")
        else:
            del cache[key]
            _save_cache(cache)
    return None


def _set_cached(key: str, data: List[Dict]):
    cache = _load_cache()
    cache[key] = {"timestamp": time.time(), "data": data}
    _save_cache(cache)


def search_aur(query: str) -> List[Dict]:
    try:
        safe_query = urllib.parse.quote(query)
        cache_key = f"search:{safe_query}"

        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{AUR_RPC_URL}search/{safe_query}"

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "apt-pac/2026.01.01")

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []

            data = json.loads(response.read().decode("utf-8"))

            if data.get("type") == "search" and "results" in data:
                results = data["results"]
                _set_cached(cache_key, results)
                return results

    except Exception:
        return []

    return []


def get_aur_info(package_names: List[str]) -> List[Dict]:
    if not package_names:
        return []

    params = [("v", "5"), ("type", "info")]
    for p in package_names:
        params.append(("arg[]", p))

    query_string = urllib.parse.urlencode(params)

    sorted_names = ",".join(sorted(package_names))
    cache_key = f"info:{sorted_names}"

    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{AUR_RPC_URL}info?{query_string}"

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "apt-pac/2026.01.01")

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return []

            data = json.loads(response.read().decode("utf-8"))

            if data.get("type") == "multiinfo" and "results" in data:
                results = data["results"]
                _set_cached(cache_key, results)
                return results

    except Exception:
        return []

    return []


def is_installed(package: str) -> bool:
    from . import alpm_helper
    return alpm_helper.is_package_installed(package)


def is_in_official_repos(package: str) -> bool:
    from . import alpm_helper
    return alpm_helper.is_in_official_repos(package)


def get_installed_packages() -> Dict[str, str]:
    from . import alpm_helper
    try:
        packages = {}
        for pkg in alpm_helper.get_installed_packages():
            packages[pkg.name] = pkg.version
        return packages
    except Exception:
        return {}


def get_installed_aur_packages() -> List[str]:
    from . import alpm_helper
    try:
        packages = [
            pkg.name for pkg in alpm_helper.get_installed_packages(foreign_only=True)
        ]
        return packages
    except Exception:
        return []


def version_compare(ver1: str, ver2: str) -> int:
    import pyalpm
    return pyalpm.vercmp(ver1, ver2)


def check_updates(verbose=False) -> List[Dict]:
    installed_aur = get_installed_aur_packages()
    if not installed_aur:
        return []

    if verbose:
        ui.console.print(
            f"[dim]{_('Checking')} {len(installed_aur)} {_('foreign packages for updates...')}[/dim]"
        )

    installed_map = get_installed_packages()

    updates = []
    chunk_size = 50

    for i in range(0, len(installed_aur), chunk_size):
        chunk = installed_aur[i : i + chunk_size]
        try:
            aur_info_list = get_aur_info(chunk)

            for info in aur_info_list:
                name = info["Name"]
                aur_ver = info["Version"]
                local_ver = installed_map.get(name)

                if local_ver and version_compare(local_ver, aur_ver) < 0:
                    updates.append({"name": name, "current": local_ver, "new": aur_ver})
        except Exception as e:
            if verbose:
                print_error(_(f"Error checking updates for chunk: {e}"))

    return updates


def get_privilege_command(target_user: str, cmd: List[str]) -> List[str]:
    config = get_config()
    tool = config.get("tools", "privilege_tool", "auto")

    if tool == "auto":
        if shutil.which("run0"):
            tool = "run0"
        elif shutil.which("doas"):
            tool = "doas"
        else:
            tool = "sudo"

    if tool == "run0":
        return ["run0", f"--user={target_user}"] + cmd
    elif tool == "doas":
        return ["doas", "-u", target_user] + cmd
    else:
        return ["sudo", "-u", target_user] + cmd


def download_aur_source(
    package_name: str, target_dir: Optional[Path] = None, force=False
) -> Optional[Path]:
    base_url = "https://aur.archlinux.org"
    clone_url = f"{base_url}/{package_name}.git"

    if target_dir is None:
        config = get_config()
        target_dir = config.cache_dir / "sources" / "aur" / package_name

    if target_dir.exists():
        if force:
            shutil.rmtree(target_dir)
        elif (target_dir / ".git").exists():
            try:
                subprocess.run(["git", "pull"], cwd=target_dir, check=True)
                return target_dir
            except subprocess.CalledProcessError:
                ui.console.print(
                    f"[yellow]{_('Pull failed for')} {package_name}, {_('re-cloning...')}[/yellow]"
                )
                shutil.rmtree(target_dir)
        else:
            ui.console.print(
                f"[yellow]{_('Removing incomplete directory for')} {package_name}...[/yellow]"
            )
            shutil.rmtree(target_dir)

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", clone_url, str(target_dir)], check=True)
        return target_dir
    except subprocess.CalledProcessError:
        print_error(_(f"Failed to clone {package_name} from AUR"))
        return None


class AurResolver:
    def __init__(self):
        self.visiting = set()
        self.visited = set()
        self.queue = []
        self.aur_info_cache = {}
        self.official_deps = set()
        self.package_bases = {}
        self.base_to_info = {}

    def resolve(self, packages: List[str]) -> List[Dict]:
        for pkg in packages:
            self._visit(pkg, force_visit=True)
        return self.queue

    def _visit(self, pkg_name: str, force_visit=False, path=None):
        if path is None:
            path = []

        if pkg_name in self.visiting:
            cycle_path = path + [pkg_name]
            raise CyclicDependencyError(cycle_path)

        if pkg_name in self.visited:
            return

        if not force_visit and is_installed(pkg_name):
            self.visited.add(pkg_name)
            return

        if is_in_official_repos(pkg_name):
            self.official_deps.add(pkg_name)
            self.visited.add(pkg_name)
            return

        if pkg_name not in self.aur_info_cache:
            info = get_aur_info([pkg_name])
            if not info:
                print_error(
                    _(f"Package '{pkg_name}' not found in AUR or official repos.")
                )
                sys.exit(1)
            self.aur_info_cache[pkg_name] = info[0]

        pkg_info = self.aur_info_cache[pkg_name]
        base = pkg_info.get("PackageBase", pkg_name)

        if base not in self.package_bases:
            self.package_bases[base] = set()
            self.base_to_info[base] = pkg_info
        self.package_bases[base].add(pkg_name)

        self.visiting.add(pkg_name)

        deps = (
            pkg_info.get("Depends", [])
            + pkg_info.get("MakeDepends", [])
            + pkg_info.get("CheckDepends", [])
        )

        clean_deps = []
        for d in deps:
            clean_name = d.split(">")[0].split("<")[0].split("=")[0].strip()
            clean_deps.append(clean_name)

        for dep in clean_deps:
            self._visit(dep, force_visit=False, path=path + [pkg_name])

        self.visiting.remove(pkg_name)
        self.visited.add(pkg_name)

        if base not in [p.get("PackageBase", p["Name"]) for p in self.queue]:
            self.queue.append(self.base_to_info[base])


class AurInstaller:
    def __init__(self):
        self.config = get_config()
        if os.getuid() == 0:
            real_user = os.environ.get("SUDO_USER")
            if real_user:
                import pwd
                try:
                    user_info = pwd.getpwnam(real_user)
                    user_home = Path(user_info.pw_dir)
                    user_cache = Path(
                        os.environ.get("XDG_CACHE_HOME", user_home / ".cache")
                    )
                    self.build_dir = user_cache / "apt-pac" / "sources" / "aur"
                except KeyError:
                    self.build_dir = self.config.cache_dir / "sources" / "aur"
            else:
                self.build_dir = self.config.cache_dir / "sources" / "aur"
        else:
            self.build_dir = self.config.cache_dir / "sources" / "aur"

        if not self.build_dir.exists():
            self.build_dir.mkdir(parents=True, exist_ok=True)

        self.resolver = None

    def install(
        self,
        packages: List[str],
        verbose=False,
        auto_confirm=False,
        build_queue=None,
        official_deps=None,
        skip_summary=False,
    ):
        if build_queue is None:
            resolver = AurResolver()
            with ui.status("[blue]Resolving AUR dependencies...[/blue]"):
                try:
                    build_queue = resolver.resolve(packages)
                except CyclicDependencyError as e:
                    print_error(str(e))
                    ui.console.print(f"\n[yellow]{_('Possible solutions:')}[/yellow]")
                    ui.console.print(
                        f"  1. {_('One of these packages may list the other as a dependency incorrectly')}"
                    )
                    ui.console.print(
                        f"  2. {_('Try installing packages individually')}"
                    )
                    ui.console.print(
                        f"  3. {_('Report this to')} AUR {_('maintainers:')} {', '.join(set(e.cycle))}"
                    )
                    sys.exit(1)
            official_deps = resolver.official_deps
            self.resolver = resolver
        else:
            official_deps = official_deps or set()
            self.resolver = None

        if not build_queue:
            print_info(_("Nothing to do."))
            return

        if not skip_summary:
            ui.console.print(_("Building dependency tree... Done"))
            ui.console.print(_("Reading state information... Done"))

            install_info = get_resolved_package_info(build_queue, official_deps)
            explicit_set = set(packages)

            print_transaction_summary(
                new_pkgs=install_info, explicit_names=explicit_set
            )

            count = len(install_info)
            count_str = f"[bold]{count}[/bold]" if count > 0 else "0"
            ui.console.print(
                f"0 upgraded, {count_str} newly installed, 0 to remove and 0 not upgraded.",
                highlight=False,
            )

            if auto_confirm:
                ui.console.print(
                    f"{_('Do you want to continue?')} [Y/n] [bold green]{_('Yes')}[/bold green]"
                )
            elif (
                not ui.console.input(f"{_('Do you want to continue?')} [Y/n] ")
                .lower()
                .startswith("y")
            ):
                print_info(_("Aborted."))
                sys.exit(0)

        if official_deps:
            cmd = ["pacman", "-S", "--needed", "--asdeps"] + list(official_deps)
            if auto_confirm:
                cmd.append("--noconfirm")

            from .commands import run_pacman_with_apt_output

            if not run_pacman_with_apt_output(cmd, show_hooks=True):
                print_error(_("Failed to install official dependencies"))
                sys.exit(1)

        final_batch_paths = []
        final_batch_names = []

        queue_deps = {}
        for i, pkg in enumerate(build_queue):
            pname = pkg["Name"]
            deps = set()
            deps.update(pkg.get("Depends", []))
            deps.update(pkg.get("MakeDepends", []))
            deps.update(pkg.get("CheckDepends", []))

            clean_deps = set()
            for d in deps:
                clean = d.split(">")[0].split("<")[0].split("=")[0].strip()
                clean_deps.add(clean)
            queue_deps[pname] = clean_deps

        for i, pkg in enumerate(build_queue):
            pkg_name = pkg["Name"]

            needed_by_future = False
            for j in range(i + 1, len(build_queue)):
                future_pkg = build_queue[j]
                future_name = future_pkg["Name"]
                if pkg_name in queue_deps[future_name]:
                    needed_by_future = True
                    break

            built_files = self._build_pkg(pkg, verbose, auto_confirm)

            if not built_files:
                print_error(_(f"Build failed for {pkg_name}"))
                sys.exit(1)

            if needed_by_future:
                cmd = ["pacman", "-U", "--asdeps", "--needed"] + [str(f) for f in built_files]
                if auto_confirm:
                    cmd.append("--noconfirm")
                from .commands import run_pacman_with_apt_output
                if not run_pacman_with_apt_output(cmd, show_hooks=True):
                    print_error(_(f"Failed to install intermediate dependency {pkg_name}"))
                    sys.exit(1)
            else:
                final_batch_paths.extend(built_files)
                final_batch_names.append(pkg_name)

        if final_batch_paths:
            cmd = ["pacman", "-U", "--needed"] + [str(f) for f in final_batch_paths]
            if auto_confirm:
                cmd.append("--noconfirm")
            from .commands import run_pacman_with_apt_output
            if not run_pacman_with_apt_output(cmd, show_hooks=True):
                print_error(_("Failed to install final packages"))
                sys.exit(1)

    def _build_pkg(
        self, pkg_info: Dict, verbose: bool, auto_confirm: bool
    ) -> List[Path]:
        base = pkg_info.get("PackageBase", pkg_info["Name"])
        name = pkg_info["Name"]
        pkg_dir = self.build_dir / base

        ui.console.print(
            f"[bold cyan]Get:[/bold cyan]1 [blue]https://aur.archlinux.org/{base}.git[/blue] {base}-source",
            highlight=False,
        )

        if not self._download_source_silent(base, pkg_dir, verbose):
            print_error(_(f"Failed to download source for {base}"))
            sys.exit(1)

        config = get_config()
        build_user_config = config.get("tools", "build_user", "auto")
        if build_user_config == "auto":
            real_user = os.environ.get("SUDO_USER")
        else:
            real_user = build_user_config

        if os.getuid() == 0 and real_user:
            subprocess.run(
                ["chown", "-R", f"{real_user}:", str(self.build_dir)], check=False
            )

        # 1.5 Security review of the downloaded PKGBUILD
        from .pkgbuild_review import review_pkgbuild
        if not review_pkgbuild(pkg_dir, name, auto_confirm=auto_confirm):
            print_info(_("Build aborted."))
            sys.exit(1)

        cmd = ["makepkg", "-f", "--needed"]

        if auto_confirm:
            cmd.append("--noconfirm")

        if ui.console.no_color:
            cmd.append("-m")

        if os.getuid() == 0:
            if real_user:
                config = get_config()
                tool = config.get("tools", "privilege_tool", "auto")

                if tool == "auto":
                    if shutil.which("run0"):
                        tool = "run0"
                    elif shutil.which("doas"):
                        tool = "doas"
                    else:
                        tool = "sudo"

                makepkg_cmd_str = " ".join(cmd)
                shell_cmd = f"cd {pkg_dir} && {makepkg_cmd_str}"

                if tool == "run0":
                    cmd = ["run0", f"--user={real_user}", "sh", "-c", shell_cmd]
                elif tool == "doas":
                    cmd = ["doas", "-u", real_user, "sh", "-c", shell_cmd]
                else:
                    cmd = ["sudo", "-u", real_user, "sh", "-c", shell_cmd]

                run_cwd = None
            else:
                print_error(_("Cannot build as root without SUDO_USER"))
                sys.exit(1)
        else:
            run_cwd = pkg_dir

        try:
            for existing_pkg in pkg_dir.glob("*.pkg.tar.*"):
                try:
                    existing_pkg.unlink()
                except OSError:
                    pass

            subprocess.run(cmd, cwd=run_cwd, check=True)

            all_pkg_files = list(pkg_dir.glob("*.pkg.tar.*"))
            valid_pkg_files = []

            for f in all_pkg_files:
                fname = f.name
                if "-debug" in fname and not name.endswith("-debug"):
                    continue
                valid_pkg_files.append(f)

            return valid_pkg_files

        except subprocess.CalledProcessError as e:
            output = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
            if not output and e.stdout:
                output = e.stdout.decode("utf-8", errors="ignore")

            gpg_match = re.search(r"unknown public key ([0-9A-F]+)", output)
            if gpg_match:
                key_id = gpg_match.group(1)
                ui.console.print(
                    f"[yellow]{_('Missing GPG Key detected:')} {key_id}[/yellow]"
                )
                ui.console.print(_("Attempting to import key..."))

                try:
                    subprocess.run(["gpg", "--recv-keys", key_id], check=True)
                    ui.console.print(_("Key imported. Retrying build..."))
                    subprocess.run(cmd, cwd=run_cwd, check=True)

                    all_pkg_files = list(pkg_dir.glob("*.pkg.tar.*"))
                    valid_pkg_files = []
                    for f in all_pkg_files:
                        fname = f.name
                        if "-debug" in fname and not name.endswith("-debug"):
                            continue
                        valid_pkg_files.append(f)
                    return valid_pkg_files

                except subprocess.CalledProcessError:
                    print_error(_(f"Failed to import key {key_id} or rebuild failed."))
                    sys.exit(1)

            print_error(_(f"Failed to build {name}"))
            sys.exit(1)

    def _download_source_silent(self, package_name, target_dir, verbose):
        base_url = "https://aur.archlinux.org"
        clone_url = f"{base_url}/{package_name}.git"

        if target_dir.exists():
            if (target_dir / ".git").exists():
                cmd = ["git", "pull"]
                cwd = target_dir
            else:
                shutil.rmtree(target_dir)
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                cmd = ["git", "clone", clone_url, str(target_dir)]
                cwd = None
        else:
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", clone_url, str(target_dir)]
            cwd = None

        try:
            capture = not verbose
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=capture)
            return True
        except subprocess.CalledProcessError:
            return False


def get_resolved_package_info(
    build_queue: List[Dict], official_deps: set
) -> List[tuple]:
    install_info = []

    for p in build_queue:
        ver = p.get("Version", "")
        install_info.append((p["Name"], ver))

    if official_deps:
        try:
            cmd = ["pacman", "-S", "--print", "--print-format", "%n %v"] + list(
                official_deps
            )
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        install_info.append((parts[0], parts[1]))
                    else:
                        install_info.append((line.strip(), ""))
            else:
                for dep in official_deps:
                    install_info.append((dep, ""))
        except Exception:
            for dep in official_deps:
                install_info.append((dep, ""))

    return install_info
