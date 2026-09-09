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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

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
        re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/", re.I),
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
        re.compile(r"chmod\s+[0-7]*[675][0-7]{2}", re.I),
        "warning",
        "sets setuid/setgid bit (chmod with 4xxx/2xxx)",
    ),
    (
        re.compile(r"install\s+.*-m\s*[0-7]*[675][0-7]{2}", re.I),
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
        re.compile(r"source\s*=\s*\([^)]*https?://(?!github\.com|gitlab\.com|bitbucket\.org|codeberg\.org|git\.sr\.ht|aur\.archlinux\.org)[^)]+\)", re.I),
        "warning",
        "source=() contains unusual remote URL (not common git hosts)",
    ),
]


def analyze_pkgbuild(content: str) -> List[Tuple[str, str]]:
    """
    Run static analysis on PKGBUILD content.
    Returns list of (severity, description).
    """
    findings: List[Tuple[str, str]] = []
    seen = set()

    for pattern, severity, desc in _PATTERNS:
        if pattern.search(content):
            key = (severity, desc)
            if key not in seen:
                findings.append(key)
                seen.add(key)

    return findings


def _get_editor() -> str:
    config = get_config()
    editor = config.get("tools", "editor", "") or os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        return editor
    for candidate in ("nano", "vim", "vi", "micro", "emacs"):
        if shutil.which(candidate):
            return candidate
    return "nano"


def _show_pkgbuild_preview(pkgbuild_path: Path, max_lines: int = 50) -> None:
    """Pretty-print the beginning of the PKGBUILD."""
    try:
        lines = pkgbuild_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        print_error(_(f"Cannot read PKGBUILD: {e}"))
        return

    ui.console.print()
    ui.console.rule(f"[bold]PKGBUILD[/bold] — {pkgbuild_path.parent.name}")
    shown = lines[:max_lines]
    for i, line in enumerate(shown, 1):
        # Very light syntax hinting
        if line.strip().startswith("#"):
            ui.console.print(f"[dim]{i:3}│ {line}[/dim]", highlight=False)
        elif re.match(r"^[a-zA-Z_]+=", line):
            ui.console.print(f"[cyan]{i:3}│[/cyan] {line}", highlight=False)
        else:
            ui.console.print(f"{i:3}│ {line}", highlight=False)

    if len(lines) > max_lines:
        ui.console.print(
            f"[dim]… ({len(lines) - max_lines} more lines — press 'v' to view full)[/dim]"
        )
    ui.console.rule()


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
        print_error(_(f"PKGBUILD not found in {pkg_dir}"))
        return False

    try:
        content = pkgbuild_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print_error(_(f"Cannot read PKGBUILD: {e}"))
        return False

    findings = analyze_pkgbuild(content)
    critical = [d for s, d in findings if s == "critical"]
    warnings = [d for s, d in findings if s == "warning"]

    # In "auto" mode we only interrupt when something suspicious is found
    if mode == "auto" and not findings:
        return True

    # ---------- Present findings ----------
    ui.console.print()
    ui.console.print(
        f"[bold yellow]{_('PKGBUILD Review')}[/bold yellow] — "
        f"[bold]{package_name}[/bold]"
    )

    if critical:
        ui.console.print(f"[bold red]{_('CRITICAL findings:')}[/bold red]")
        for desc in critical:
            ui.console.print(f"  [red]✗[/red] {desc}")
    if warnings:
        ui.console.print(f"[bold yellow]{_('Warnings:')}[/bold yellow]")
        for desc in warnings:
            ui.console.print(f"  [yellow]![/yellow] {desc}")
    if not findings:
        ui.console.print(f"[green]{_('No obvious dangerous patterns detected.')}[/green]")

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
                    f"{_('Continue building')} [bold]{package_name}[/bold]? "
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
            editor = _get_editor()
            ui.console.print(f"[dim]{_('Opening')} {pkgbuild_path} {_('in')} {editor}…[/dim]")
            try:
                subprocess.run([editor, str(pkgbuild_path)], check=False)
            except Exception as e:
                print_error(_(f"Failed to launch editor: {e}"))
            # Re-analyse after edit
            try:
                content = pkgbuild_path.read_text(encoding="utf-8", errors="replace")
                findings = analyze_pkgbuild(content)
                critical = [d for s, d in findings if s == "critical"]
                warnings = [d for s, d in findings if s == "warning"]
                if critical:
                    ui.console.print(f"[bold red]{_('Still has CRITICAL findings:')}[/bold red]")
                    for desc in critical:
                        ui.console.print(f"  [red]✗[/red] {desc}")
                elif warnings:
                    ui.console.print(f"[yellow]{_('Still has warnings.')}[/yellow]")
                else:
                    ui.console.print(f"[green]{_('No obvious dangerous patterns detected.')}[/green]")
            except OSError:
                pass
            continue
        if answer in ("v", "view"):
            pager = shutil.which("less") or shutil.which("more") or "cat"
            subprocess.run([pager, str(pkgbuild_path)], check=False)
            continue

        ui.console.print(
            f"[dim]{_('Please answer Y (yes), n (no), e (edit) or v (view full).')}[/dim]"
        )
