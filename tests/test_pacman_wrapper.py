import io
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rich.console import Console
from apt_pac import commands, ui


def _capture_console():
    buf = io.StringIO()
    con = Console(file=buf, force_terminal=False, no_color=True, width=120)
    return buf, con


def _mock_progress():
    prog = MagicMock()
    prog.__enter__.return_value = prog
    prog.__exit__.return_value = False
    prog.add_task.return_value = 1
    return prog


class TestPacmanWrapper(unittest.TestCase):
    def test_interactive_prompt_without_newline_flushed_and_stops_progress(self):
        r_fd, w_fd = os.pipe()
        reader_stream = os.fdopen(r_fd, "rb", 0)

        mock_proc = MagicMock()
        mock_proc.stdout = reader_stream
        mock_proc.poll.side_effect = lambda: None if not mock_proc._done else 0
        mock_proc._done = False
        mock_proc.returncode = 0

        def writer():
            try:
                os.write(w_fd, b":: Replace foo with extra/bar? [Y/n] ")
                time.sleep(0.30)
                os.write(w_fd, b"\n(1/1) upgrading bar (1.0-1 -> 2.0-1)\n")
                mock_proc._done = True
            finally:
                os.close(w_fd)

        buf, con = _capture_console()
        mock_prog = _mock_progress()
        mock_proc.wait.side_effect = lambda: None

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=mock_prog),
            patch("apt_pac.commands.console", con),
        ):
            t = threading.Thread(target=writer, daemon=True)
            t.start()
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "bar"])
            t.join(timeout=3)

        reader_stream.close()
        out = buf.getvalue()
        self.assertTrue(ok)
        mock_prog.stop.assert_called()
        mock_prog.start.assert_called()
        self.assertIn(":: Replace foo with extra/bar? [Y/n]", out)
        self.assertIn("Preparing to unpack .../bar_2.0-1.pkg ...", out)
        self.assertIn("Unpacking bar (2.0-1) over (1.0-1) ...", out)

    @unittest.skipIf(sys.platform == "win32", "PTY test requires POSIX/Linux")
    def test_real_pty_child_process_output(self):
        script = (
            "import sys\n"
            "sys.stdout.write('(1/1) installing demo (1.0-1)\\n')\n"
            "sys.stdout.flush()\n"
        )
        buf, con = _capture_console()
        mock_prog = _mock_progress()

        with (
            patch("apt_pac.commands.Progress", return_value=mock_prog),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output([sys.executable, "-c", script])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertIn("Selecting previously unselected package demo.", out)
        self.assertIn("Unpacking demo (1.0-1) ...", out)

    def test_pacman_error_block_preserves_multiline_details(self):
        lines = [
            "resolving dependencies...\n",
            "error: failed to commit transaction (conflicting files)\n",
            "foo: /usr/bin/foo exists in filesystem (owned by bar)\n",
            "Errors occurred, no packages were upgraded.\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 1

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "foo"])

        out = buf.getvalue()
        self.assertFalse(ok)
        self.assertNotIn("resolving dependencies", out)
        self.assertIn("E: failed to commit transaction (conflicting files)", out)
        self.assertIn("foo: /usr/bin/foo exists in filesystem (owned by bar)", out)
        self.assertIn("Errors occurred, no packages were upgraded.", out)

    def test_optional_dependencies_and_scriptlets_preserved(self):
        lines = [
            "(1/1) installing git (2.48.0-1)\n",
            "Optional dependencies for git\n",
            "    tk: gitk and git gui [installed]\n",
            "    python: git p4 support [pending]\n",
            "    perl: extra helpers\n",
            "==> Generating initramfs...\n",
            ":: Note: enable foo.service to start automatically\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "git"])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertIn("Optional dependencies for git", out)
        self.assertIn("tk: gitk and git gui [installed]", out)
        self.assertIn("python: git p4 support [pending]", out)
        self.assertIn("perl: extra helpers", out)
        self.assertIn("==> Generating initramfs...", out)
        self.assertIn(":: Note: enable foo.service to start automatically", out)

    def test_warnings_and_pacnew_summary_notice(self):
        lines = [
            "(1/1) upgrading pacman (7.0-1 -> 7.1-1)\n",
            "warning: /etc/pacman.conf installed as /etc/pacman.conf.pacnew\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-Su"])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertIn("W: /etc/pacman.conf installed as /etc/pacman.conf.pacnew", out)
        self.assertIn(
            "Configuration file updates detected (.pacnew/.pacsave/.pacorig):", out
        )
        self.assertIn("pacdiff", out)

    def test_pre_transaction_checks_do_not_trigger_setting_up_system(self):
        lines = [
            "(1/2) checking keys in keyring\n",
            "(2/2) checking package integrity\n",
            "(1/1) loading package files\n",
            "(1/1) checking for file conflicts\n",
            "(2/2) checking available disk space\n",
            ":: Processing package changes...\n",
            "(1/1) installing ripgrep (14.1.1-1)\n",
            ":: Running post-transaction hooks...\n",
            "(1/2) Arming ConditionNeedsUpdate...\n",
            "(2/2) Updating the info directory file...\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "ripgrep"])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertNotIn("Setting up system (checking", out)
        self.assertNotIn("Setting up system (loading", out)
        self.assertIn("Processing triggers for Running post-transaction hooks ...", out)
        self.assertIn("Setting up system (Arming ConditionNeedsUpdate) ...", out)
        self.assertIn(
            "Setting up system (Updating the info directory file) ...", out
        )

    def test_reinstall_downgrade_and_single_reading_database(self):
        lines = [
            "(1/3) installing pkg-a (1.0-1)\n",
            "(2/3) reinstalling pkg-b (2.0-1)\n",
            "(3/3) downgrading pkg-c (3.0-2 -> 3.0-1)\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "pkg-a"])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertEqual(out.count("Reading database"), 1)
        self.assertIn("Preparing to unpack .../pkg-b_2.0-1.pkg ...", out)
        self.assertIn("Unpacking pkg-b (2.0-1) over (2.0-1) ...", out)
        self.assertIn("Preparing to unpack .../pkg-c_3.0-1.pkg ...", out)
        self.assertIn("downgrading pkg-c from 3.0-2 to 3.0-1", out)
        self.assertIn("Unpacking pkg-c (3.0-1) over (3.0-2) ...", out)

    def test_simulate_apt_download_output_formats_repo_version_size_and_cache(self):
        sp_out = (
            "file:///var/cache/pacman/pkg/bash-5.2.37-2-x86_64.pkg.tar.zst\n"
            "https://mirror.example.org/arch/core/os/x86_64/coreutils-9.5-1-x86_64.pkg.tar.zst\n"
        )
        bash_pkg = MagicMock(version="5.2.37-2", download_size=1900000)
        bash_pkg.db = MagicMock()
        bash_pkg.db.name = "core"
        coreutils_pkg = MagicMock(version="9.5-1", download_size=2800000)
        coreutils_pkg.db = MagicMock()
        coreutils_pkg.db.name = "core"

        def get_pkg(name):
            return {"bash": bash_pkg, "coreutils": coreutils_pkg}.get(name)

        buf, con = _capture_console()
        with (
            patch(
                "subprocess.run",
                return_value=MagicMock(returncode=0, stdout=sp_out),
            ),
            patch("apt_pac.commands.alpm_helper.get_package", side_effect=get_pkg),
            patch("apt_pac.ui.console", con),
        ):
            count = commands.simulate_apt_download_output(
                ["pacman", "-S", "bash", "coreutils"], MagicMock()
            )

        out = buf.getvalue()
        self.assertEqual(count, 2)
        self.assertIn("Hit:1 [in cache] core/bash 5.2.37-2 [1.9 MB]", out)
        self.assertIn(
            "Get:2 https://mirror.example.org/ core/coreutils 9.5-1 [2.8 MB]", out
        )

    def test_execute_command_install_passes_total_pkgs_and_skips_sim_on_remove(self):
        mock_conf = MagicMock()
        mock_conf.get.return_value = 0

        with (
            patch("apt_pac.commands.get_config", return_value=mock_conf),
            patch("apt_pac.commands.check_safeguards"),
            patch("apt_pac.commands.os.path.isfile", return_value=False),
            patch("apt_pac.commands.aur.is_in_official_repos", return_value=True),
            patch("apt_pac.commands.show_summary", return_value=True),
            patch(
                "apt_pac.commands.simulate_apt_download_output", return_value=4
            ) as mock_sim,
            patch(
                "apt_pac.commands.run_pacman_with_apt_output", return_value=True
            ) as mock_run_apt,
            patch("os.getuid", return_value=0, create=True),
        ):
            commands.execute_command("install", ["foo"])
            self.assertEqual(mock_run_apt.call_args.kwargs.get("total_pkgs"), 4)
            mock_sim.assert_called_once()

        with (
            patch("apt_pac.commands.get_config", return_value=mock_conf),
            patch("apt_pac.commands.check_safeguards"),
            patch("apt_pac.commands.simulate_apt_download_output") as mock_sim_rm,
            patch(
                "apt_pac.commands.run_pacman_with_apt_output", return_value=True
            ) as mock_run_rm,
            patch("os.getuid", return_value=0, create=True),
        ):
            commands.execute_command("remove", ["foo"])
            mock_sim_rm.assert_not_called()
            mock_run_rm.assert_called_once()

    def test_show_summary_failure_returns_none_and_preserves_interactivity(self):
        with patch(
            "apt_pac.commands.run_pacman",
            return_value=MagicMock(returncode=1, stdout="", stderr="target not found"),
        ):
            res = commands.show_summary("install", ["virtual-pkg"])
        self.assertIsNone(res)

        mock_conf = MagicMock()
        mock_conf.get.return_value = 0
        with (
            patch("apt_pac.commands.get_config", return_value=mock_conf),
            patch("apt_pac.commands.check_safeguards"),
            patch("apt_pac.commands.os.path.isfile", return_value=False),
            patch("apt_pac.commands.aur.is_in_official_repos", return_value=True),
            patch("apt_pac.commands.show_summary", return_value=None),
            patch("apt_pac.commands.simulate_apt_download_output", return_value=0),
            patch(
                "apt_pac.commands.run_pacman_with_apt_output", return_value=True
            ) as mock_run_apt,
            patch("os.getuid", return_value=0, create=True),
        ):
            commands.execute_command("install", ["virtual-pkg"])
            called_cmd = mock_run_apt.call_args[0][0]
            self.assertNotIn("--noconfirm", called_cmd)

    def test_pkg_name_containing_error_or_warning_not_misclassified(self):
        lines = [
            "(1/1) installing libgpg-error (1.50-1)\n",
            "Optional dependencies for gnupg\n",
            "    libgpg-error: error helper\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _capture_console()
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=_mock_progress()),
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "gnupg"])

        out = buf.getvalue()
        self.assertTrue(ok)
        self.assertNotIn("E:", out)
        self.assertNotIn("W:", out)
        self.assertIn("Unpacking libgpg-error (1.50-1) ...", out)


if __name__ == "__main__":
    unittest.main()
