"""
PKGBUILD security review for apt-pac.

Performs static analysis looking for common malicious or dangerous patterns
and optionally prompts the user for manual confirmation before building.

This exists because AUR packages are untrusted user-submitted code and
there have been multiple supply-chain / malware incidents.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

from rich.markup import escape

from . import ui
from .config import get_config
from .i18n import _
from .ui import print_error, print_info


# ---------------------------------------------------------------------------
# Dangerous / suspicious patterns (regex, case-insensitive where noted)
# Each entry: (compiled_regex, severity, human description)
# severity: "critical" | "warning"
# ---------------------------------------------------------------------------

_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Critical – almost certainly malicious or extremely dangerous
    (
        re.compile(r"curl\s+[^|\n]*\|\s*(?:ba)?sh", re.I),
        "critical",
        "curl … | sh/bash (remote code execution)",
    ),
    (
        re.compile(r"wget\s+[^|\n]*\|\s*(?:ba)?sh", re.I),
        "critical",
        "wget … | sh/bash (remote code execution)",
    ),
    (
        re.compile(r"curl\s+[^|\n]*\|\s*python", re.I),
        "critical",
        "curl … | python (remote code execution)",
    ),
    (
        re.compile(r"wget\s+[^|\n]*\|\s*python", re.I),
        "critical",
        "wget … | python (remote code execution)",
    ),
    (
        re.compile(r"(?:ba)?sh\s+<\(\s*(?:curl|wget)\b", re.I),
        "critical",
        "shell process substitution from curl/wget (remote code execution)",
    ),
    (
        re.compile(r"(?:ba)?sh\s+-c\s+[\"'].*\$\(\s*(?:curl|wget)\b", re.I),
        "critical",
        "shell -c executing downloaded curl/wget payload (remote code execution)",
    ),
    (
        re.compile(
            r"\brm\s+(?:(?:-[a-zA-Z]+\s+)*--no-preserve-root|(?:-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*)\s+/(?:\s|$|\*|(?:etc|usr|bin|sbin|lib|boot|home|var|opt|root)\b))",
            re.I,
        ),
        "critical",
        "rm -rf / or similar destructive command on root",
    ),
    (
        re.compile(r"\bdd\s+.*of=/dev/[sh]d", re.I),
        "critical",
        "dd writing directly to disk device",
    ),
    (
        re.compile(r"base64\s+(-d|--decode).*(?:\|\s*(?:ba)?sh|eval)", re.I),
        "critical",
        "base64-decoded payload piped to shell/eval (obfuscation)",
    ),
    (
        re.compile(r"eval\s+[\"'].*base64", re.I),
        "critical",
        "eval of base64 content (classic obfuscation)",
    ),
    (
        re.compile(r"\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}", re.I),
        "critical",
        "long hex-encoded payload (possible obfuscation)",
    ),
    # Warnings – suspicious but sometimes legitimate
    (
        re.compile(r"\bsudo\b", re.I),
        "warning",
        "uses 'sudo' inside PKGBUILD (unusual and dangerous)",
    ),
    (
        re.compile(r"\b(doas|run0|pkexec)\b", re.I),
        "warning",
        "privilege-escalation helper used inside PKGBUILD",
    ),
    (
        re.compile(r"curl\s+.*(-k|--insecure)", re.I),
        "warning",
        "curl with --insecure / -k (disables TLS verification)",
    ),
    (
        re.compile(r"wget\s+.*--no-check-certificate", re.I),
        "warning",
        "wget ignoring certificate validation",
    ),
    (
        re.compile(
            r"\bchmod\s+(?:-[a-zA-Z]+\s+)*(?:0*[2-7][0-7]{3}\b|[ugoa]*\+[rwxXst]*s\b)",
            re.I,
        ),
        "warning",
        "sets setuid/setgid bit (chmod with 4xxx/2xxx or +s)",
    ),
    (
        re.compile(
            r"\binstall\b[^\n]*(?:\s-[a-zA-Z]*m\s*|\s--mode[=\s]+)(?:0*[2-7][0-7]{3}\b|[ugoa]*\+[rwxXst]*s\b)",
            re.I,
        ),
        "warning",
        "install with setuid/setgid mode",
    ),
    (
        re.compile(r"(/tmp|/dev/shm)/[a-z0-9._-]+\s*\|\s*(?:ba)?sh", re.I),
        "warning",
        "executing script from /tmp or /dev/shm",
    ),
    (
        re.compile(r"nc\s+(-[el]|--listen|--exec)", re.I),
        "warning",
        "netcat listener / execute mode",
    ),
    (
        re.compile(r"python[23]?\s+-c\s+[\"'].*import\s+urllib", re.I),
        "warning",
        "inline python downloading content via urllib",
    ),
    (
        re.compile(r"source(?:_[a-z0-9_]+)?\s*=\s*\([^)]*\bhttp://[^)]+\)", re.I),
        "warning",
        "source=() uses unencrypted http:// URL",
    ),
    (
        re.compile(
            r"source(?:_[a-z0-9_]+)?\s*=\s*\([^)]*https?://\d{1,3}(?:\.\d{1,3}){3}[:/][^)]*\)",
            re.I,
        ),
        "warning",
        "source=() downloads from a raw IP address",
    ),
    (
        re.compile(
            r"source(?:_[a-z0-9_]+)?\s*=\s*\([^)]*https?://(?:[^/\s)]*\.)?(?:pastebin\.com|0x0\.st|transfer\.sh|ix\.io|paste\.rs|dpaste\.org|hastebin\.com)/[^)]+\)",
            re.I,
        ),
        "warning",
        "source=() downloads from an anonymous paste/file-drop host",
    ),
]


def analyze_pkgbuild(content: str) -> List[Tuple[str, str]]:
    """
    Run static analysis on PKGBUILD content.
    Returns list of (severity, description).
    """
    findings: List[Tuple[str, str]] = []
    seen = set()

    # Ignore full-line comments so commented instructions/notes do not false-positive
    code_content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    )

    for pattern, severity, desc in _PATTERNS:
        if pattern.search(code_content):
            key = (severity, desc)
            if key not in seen:
                findings.append(key)
                seen.add(key)

    return findings


def _get_editor() -> List[str]:
    config = get_config()
    editor = (
        config.get("tools", "editor", "")
        or os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
    )
    if editor:
        try:
            parts = shlex.split(editor)
            if parts:
                return parts
        except ValueError:
            pass
    for candidate in ("nano", "vim", "vi", "micro", "emacs"):
        if shutil.which(candidate):
            return [candidate]
    return ["nano"]


def _show_pkgbuild_preview(pkgbuild_path: Path, max_lines: int = 50) -> None:
    """Pretty-print the beginning of the PKGBUILD with markup escaping."""
    try:
        lines = pkgbuild_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        print_error(_("Cannot read PKGBUILD: {error}").format(error=e))
        return

    linux_vt = ui.is_linux_console(ui.console)
    sep = "-" if linux_vt else "—"
    pipe = "|" if linux_vt else "│"
    ellip = "..." if linux_vt else "…"
    rule_char = "-" if linux_vt else "─"

    ui.console.print()
    ui.console.rule(
        f"[bold]PKGBUILD[/bold] {sep} {escape(pkgbuild_path.parent.name)}",
        characters=rule_char,
    )
    shown = lines[:max_lines]
    for i, line in enumerate(shown, 1):
        safe_line = escape(line)
        if line.strip().startswith("#"):
            ui.console.print(f"[dim]{i:3}{pipe} {safe_line}[/dim]", highlight=False)
        elif re.match(r"^[a-zA-Z_]+=", line):
            ui.console.print(f"[cyan]{i:3}{pipe}[/cyan] {safe_line}", highlight=False)
        else:
            ui.console.print(f"{i:3}{pipe} {safe_line}", highlight=False)

    if len(lines) > max_lines:
        ui.console.print(
            f"[dim]{ellip} ({len(lines) - max_lines} more lines {sep} press 'v' to view full)[/dim]"
        )
    ui.console.rule(characters=rule_char)


def review_pkgbuild(
    pkg_dir: Path,
    package_name: str,
    auto_confirm: bool = False,
) -> bool:
    """
    Review the PKGBUILD located in pkg_dir.

    Returns True if the user (or policy) allows the build to continue.
    Returns False (and the caller should abort) otherwise.
    """
    config = get_config()
    mode = config.get("safeguards", "review_pkgbuild", "ask")

    # Normalise legacy boolean values if someone set true/false
    if mode is True or str(mode).lower() in ("true", "1", "yes"):
        mode = "ask"
    elif mode is False or str(mode).lower() in ("false", "0", "no", "never"):
        mode = "never"

    if mode == "never":
        return True

    pkgbuild_path = pkg_dir / "PKGBUILD"
    if not pkgbuild_path.is_file():
        print_error(_("PKGBUILD not found in {pkg_dir}").format(pkg_dir=pkg_dir))
        return False

    try:
        content = pkgbuild_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print_error(_("Cannot read PKGBUILD: {error}").format(error=e))
        return False

    findings = analyze_pkgbuild(content)
    critical = [d for s, d in findings if s == "critical"]
    warnings = [d for s, d in findings if s == "warning"]

    # In "auto" mode we only interrupt when something suspicious is found
    if mode == "auto" and not findings:
        return True

    linux_vt = ui.is_linux_console(ui.console)
    sep = "-" if linux_vt else "—"
    cross = "x" if linux_vt else "✗"
    ellip = "..." if linux_vt else "…"

    # ---------- Present findings ----------
    ui.console.print()
    ui.console.print(
        f"[bold yellow]{_('PKGBUILD Review')}[/bold yellow] {sep} "
        f"[bold]{escape(package_name)}[/bold]"
    )

    if critical:
        ui.console.print(f"[bold red]{_('CRITICAL findings:')}[/bold red]")
        for desc in critical:
            safe_desc = escape(desc.replace("…", "...") if linux_vt else desc)
            ui.console.print(f"  [red]{cross}[/red] {safe_desc}")
    if warnings:
        ui.console.print(f"[bold yellow]{_('Warnings:')}[/bold yellow]")
        for desc in warnings:
            safe_desc = escape(desc.replace("…", "...") if linux_vt else desc)
            ui.console.print(f"  [yellow]![/yellow] {safe_desc}")
    if not findings:
        ui.console.print(
            f"[green]{_('No obvious dangerous patterns detected.')}[/green]"
        )

    _show_pkgbuild_preview(pkgbuild_path)

    # ---------- Decision ----------
    if auto_confirm:
        if critical:
            print_error(
                _(
                    "Critical findings in PKGBUILD and --noconfirm / -y was given. "
                    "Aborting for safety. Re-run without -y to review manually."
                )
            )
            return False
        # Warnings only + auto_confirm → proceed but warn loudly
        if warnings:
            ui.console.print(
                f"[yellow]{_('W:')} {_('Proceeding despite warnings because of --noconfirm.')}[/yellow]"
            )
        return True

    # Interactive prompt
    while True:
        try:
            answer = (
                ui.console.input(
                    f"{_('Continue building')} [bold]{escape(package_name)}[/bold]? "
                    f"[Y/n/e/v] "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            ui.console.print()
            print_info(_("Aborted."))
            return False

        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            print_info(_("Build aborted by user."))
            return False
        if answer in ("e", "edit"):
            editor_cmd = _get_editor() + [str(pkgbuild_path)]
            from . import aur

            real_user = aur._get_real_build_user(config)
            if os.getuid() == 0 and real_user:
                editor_cmd = aur.get_privilege_command(real_user, editor_cmd)
            ui.console.print(
                f"[dim]{_('Opening')} {escape(str(pkgbuild_path))} {_('in')} {escape(str(editor_cmd[0]))}{ellip}[/dim]"
            )
            try:
                subprocess.run(editor_cmd, check=False)
            except Exception as e:
                print_error(_("Failed to launch editor: {error}").format(error=e))
            # Re-analyse after edit
            try:
                content = pkgbuild_path.read_text(encoding="utf-8", errors="replace")
                findings = analyze_pkgbuild(content)
                critical = [d for s, d in findings if s == "critical"]
                warnings = [d for s, d in findings if s == "warning"]
                if critical:
                    ui.console.print(
                        f"[bold red]{_('Still has CRITICAL findings:')}[/bold red]"
                    )
                    for desc in critical:
                        safe_desc = escape(
                            desc.replace("…", "...") if linux_vt else desc
                        )
                        ui.console.print(f"  [red]{cross}[/red] {safe_desc}")
                elif warnings:
                    ui.console.print(f"[yellow]{_('Still has warnings.')}[/yellow]")
                else:
                    ui.console.print(
                        f"[green]{_('No obvious dangerous patterns detected.')}[/green]"
                    )
            except OSError:
                pass
            continue
        if answer in ("v", "view"):
            pager = shutil.which("less") or shutil.which("more") or "cat"
            pager_cmd = [pager, str(pkgbuild_path)]
            from . import aur

            real_user = aur._get_real_build_user(config)
            if os.getuid() == 0 and real_user:
                pager_cmd = aur.get_privilege_command(real_user, pager_cmd)
            try:
                subprocess.run(pager_cmd, check=False)
            except OSError as e:
                print_error(_("Failed to launch pager: {error}").format(error=e))
            continue

        ui.console.print(
            f"[dim]{_('Please answer Y (yes), n (no), e (edit) or v (view full).')}[/dim]"
        )
