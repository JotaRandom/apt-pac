import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rich.color import ColorSystem
from rich.console import Console, ConsoleOptions
from rich.text import Text

from apt_pac import commands, ui


def _con(width=80, color=False, encoding="utf-8"):
    buf = io.StringIO()
    con = Console(
        file=buf,
        width=width,
        force_terminal=color,
        no_color=not color,
        color_system="standard" if color else None,
        highlight=False,
    )
    if encoding:
        con._file_encoding = encoding
    return buf, con


class TestUiAlignmentAndCommands(unittest.TestCase):
    def test_is_linux_console_and_terminal_width(self):
        with patch.dict(os.environ, {"TERM": "linux"}, clear=False):
            self.assertTrue(ui.is_linux_console())
            theme = ui._build_theme()
            self.assertNotIn("italic", str(theme.styles["command"]))
            self.assertNotIn("grey70", str(theme.styles["desc"]))

        with patch.dict(os.environ, {"TERM": "vt100"}, clear=False):
            self.assertTrue(ui.is_linux_console())

        utf_con = SimpleNamespace(encoding="utf-8", size=SimpleNamespace(width=48))
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False):
            with patch("os.ttyname", side_effect=OSError("not a tty")):
                self.assertFalse(ui.is_linux_console(utf_con))
                ascii_con = SimpleNamespace(encoding="ascii", size=SimpleNamespace(width=80))
                self.assertTrue(ui.is_linux_console(ascii_con))

        self.assertEqual(ui.get_terminal_width(utf_con), 48)
        tiny_con = SimpleNamespace(size=SimpleNamespace(width=10))
        self.assertEqual(ui.get_terminal_width(tiny_con), 20)

    def test_set_force_colors_uses_standard_on_linux_console(self):
        buf, con = _con(width=80, color=False)
        with (
            patch("apt_pac.ui.console", con),
            patch.dict(os.environ, {"TERM": "linux"}, clear=False),
        ):
            ui.set_force_colors(True)
            self.assertEqual(con._color_system, ColorSystem.STANDARD)

    def test_candybar_width_invariant_and_linux_char(self):
        _, xterm_con = _con(width=80, color=True)
        _, linux_con = _con(width=80, color=True)

        with (
            patch("apt_pac.commands.ui.is_linux_console", return_value=False),
            patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
        ):
            for w in (10, 20, 40, 80):
                opts = xterm_con.options.update(max_width=w)
                for pct in (0, 25, 50, 100):
                    rendered = list(
                        commands.CandyBar(pct, 100, 1.0).__rich_console__(xterm_con, opts)
                    )[0]
                    self.assertEqual(rendered.cell_len, w, f"width={w}, pct={pct}")
                    if pct in (0, 50):
                        self.assertIn("⚬", rendered.plain)

        with patch("apt_pac.commands.ui.is_linux_console", return_value=True):
            for w in (10, 20, 40, 80):
                opts = linux_con.options.update(max_width=w)
                for pct in (0, 25, 50, 100):
                    rendered = list(
                        commands.CandyBar(pct, 100, 1.0).__rich_console__(linux_con, opts)
                    )[0]
                    self.assertEqual(rendered.cell_len, w, f"linux width={w}, pct={pct}")
                    self.assertNotIn("⚬", rendered.plain)
                    if pct < 100:
                        self.assertIn(".", rendered.plain)

    def test_print_columnar_list_adapts_widths_and_literals(self):
        pkgs = [
            "bash",
            "git",
            "nano",
            "vim",
            "curl",
            "htop",
            "super-long-package-name-for-testing-width",
            "jq",
            "sed",
            "grep",
            "literal\\[pkg]",
            "unclosed[tag",
        ]

        buf40, con40 = _con(width=40)
        with patch("apt_pac.ui.console", con40):
            ui.print_columnar_list(pkgs, "green")
        out40 = buf40.getvalue()
        self.assertIn("bash", out40)
        self.assertIn("literal[pkg]", out40)
        self.assertIn("unclosed[tag", out40)
        for line in out40.splitlines():
            self.assertLessEqual(len(line), 40)

        buf160, con160 = _con(width=160)
        with patch("apt_pac.ui.console", con160):
            ui.print_columnar_list(pkgs, "green")
        first_line = buf160.getvalue().splitlines()[0]
        self.assertIn("bash", first_line)
        self.assertIn("git", first_line)
        self.assertIn("nano", first_line)
        for line in buf160.getvalue().splitlines():
            self.assertLessEqual(len(line), 160)

    def test_format_show_aur_and_showsrc_compact_vs_wide(self):
        pacman_out = (
            "Repository      : core\n"
            "Name            : bash\n"
            "Version         : 5.3.20-1\n"
            "Description     : The GNU Bourne Again shell with a very long description that should wrap neatly\n"
            "Depends On      : readline glibc ncurses\n"
            "Optional Deps   : \n"
            "                     bash-completion: programmable completion\n"
            "                     pkgfile: command not found hook\n"
            "Install Reason  : Explicitly installed\n"
        )

        buf_wide, con_wide = _con(width=100)
        with patch("apt_pac.ui.console", con_wide):
            ui.format_show(pacman_out)
        out_wide = buf_wide.getvalue()
        lines_wide = [ln for ln in out_wide.splitlines() if ln.strip()]
        colon_cols = {ln.index(" : ") for ln in lines_wide if " : " in ln}
        self.assertEqual(len(colon_cols), 1)
        self.assertIn("Suggests", out_wide)
        self.assertNotIn("Suggests             :\n\n", out_wide)
        for ln in out_wide.splitlines():
            self.assertLessEqual(len(ln), 100)

        buf_narrow, con_narrow = _con(width=48)
        with patch("apt_pac.ui.console", con_narrow):
            ui.format_show(pacman_out)
        out_narrow = buf_narrow.getvalue()
        self.assertIn("Package: bash", out_narrow)
        self.assertIn("Suggests:", out_narrow)
        self.assertIn("  bash-completion: programmable completion", out_narrow)
        for ln in out_narrow.splitlines():
            self.assertLessEqual(len(ln), 48)

        buf_src, con_src = _con(width=100)
        with patch("apt_pac.ui.console", con_src):
            ui.print_showsrc_info(
                "demo",
                {"pkgname": "demo", "pkgver": "1.0", "pkgrel": "2", "depends": ["bash"]},
                "/tmp/src",
            )
        out_src = buf_src.getvalue()
        src_cols = {ln.index(" : ") for ln in out_src.splitlines() if " : " in ln}
        self.assertEqual(len(src_cols), 1)

    def test_format_search_results_hanging_indent_and_installed_literal(self):
        search_out = (
            "core/bash 5.3.20-1 [installed]\n"
            "    The GNU Bourne Again shell with an intentionally very long description for wrapping check\n"
        )
        buf, con = _con(width=50)
        with patch("apt_pac.ui.console", con):
            ui.format_search_results(search_out)

        lines = buf.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("bash/core 5.3.20-1 [installed]"))
        self.assertTrue(lines[1].startswith("  The GNU"))
        self.assertTrue(lines[2].startswith("  "))
        for ln in lines:
            self.assertLessEqual(len(ln), 50)

        buf_aur, con_aur = _con(width=50)
        with (
            patch("apt_pac.ui.console", con_aur),
            patch("apt_pac.ui.is_linux_console", return_value=True),
        ):
            ui.format_aur_search_results(
                [
                    {
                        "Name": "paru",
                        "Version": "2.0.4-1",
                        "Description": "Feature packed AUR helper with long description for narrow terminal wrapping",
                        "NumVotes": 99,
                    }
                ]
            )
        aur_lines = buf_aur.getvalue().splitlines()
        self.assertTrue(aur_lines[0].startswith("paru/aur 2.0.4-1 (Votes: 99)"))
        self.assertTrue(aur_lines[1].startswith("  Feature packed"))

    def test_list_modes_escaping_glob_and_quiet(self):
        orphan = SimpleNamespace(
            name="orphpkg", version="1.0-1", arch="any", reason=1,
            compute_requiredby=lambda: [],
        )
        dep = SimpleNamespace(
            name="deppkg", version="2.0-1", arch="x86_64", reason=1,
            compute_requiredby=lambda: ["parentpkg"],
        )
        expl = SimpleNamespace(
            name="explpkg", version="3.0-1", arch="x86_64", reason=0,
            compute_requiredby=lambda: [],
        )
        outdated = SimpleNamespace(
            name="aurpkg", version="4.0-1", arch="x86_64", reason=0,
            compute_requiredby=lambda: [],
        )

        sync_extra = SimpleNamespace(db=SimpleNamespace(name="extra"))

        def get_pkg(n):
            return {"orphpkg": sync_extra, "deppkg": sync_extra, "explpkg": sync_extra}.get(n)

        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda s, k, d=None: "apt-pac" if k == "show_output" else (1 if k == "verbosity" else d)

        buf, con = _con(width=120)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con),
            patch("apt_pac.commands.alpm_helper.get_installed_packages", return_value=[orphan, dep, expl, outdated]),
            patch("apt_pac.commands.alpm_helper.get_orphan_packages", return_value=[orphan]),
            patch("apt_pac.commands.alpm_helper.get_package", side_effect=get_pkg),
            patch("apt_pac.commands.aur.check_updates", return_value=[{"name": "aurpkg"}]),
        ):
            commands.execute_command("list", ["--installed"])
        out = buf.getvalue()
        self.assertIn("Listing... Done", out)
        self.assertIn("[installed, orphan]", out)
        self.assertIn("[installed by parentpkg]", out)
        self.assertIn("[installed]", out)
        self.assertIn("[installed, outdated]", out)

        buf_upg, con_upg = _con(width=120)
        sync_bash = SimpleNamespace(db=SimpleNamespace(name="core"), arch="x86_64")
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_upg),
            patch("apt_pac.commands.alpm_helper.get_available_updates", return_value=[("bash", "5.3.1-1", "5.3.2-1")]),
            patch("apt_pac.commands.alpm_helper.get_package", return_value=sync_bash),
        ):
            commands.execute_command("list", ["--upgradable", "b*"])
        self.assertIn("bash/core 5.3.2-1 x86_64 [upgradable from: 5.3.1-1]", buf_upg.getvalue())

        buf_repo, con_repo = _con(width=120)
        core_db = SimpleNamespace(
            name="core",
            pkgcache=[
                SimpleNamespace(name="bash", version="5.3.2-1", arch="x86_64"),
                SimpleNamespace(name="zlib", version="1.3-1", arch="x86_64"),
            ],
        )
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_repo),
            patch("apt_pac.commands.alpm_helper.get_handle", return_value=SimpleNamespace(get_syncdbs=lambda: [core_db])),
            patch("apt_pac.commands.alpm_helper.get_installed_packages", return_value=[SimpleNamespace(name="bash")]),
        ):
            commands.execute_command("list", ["--repo", "core", "b*"])
        out_repo = buf_repo.getvalue()
        self.assertIn("bash/core 5.3.2-1 x86_64 [installed]", out_repo)
        self.assertNotIn("zlib", out_repo)

        buf_q, con_q = _con(width=120)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_q),
            patch("apt_pac.commands.alpm_helper.get_installed_packages", return_value=[expl]),
            patch("apt_pac.commands.alpm_helper.get_package", return_value=sync_extra),
        ):
            commands.execute_command("list", ["-qq"])
        self.assertEqual(buf_q.getvalue().strip(), "explpkg")

    def test_sync_databases_format_dedup_errors_and_aur(self):
        def fake_run(cmd, **kwargs):
            if cmd == ["pacman-conf", "-l"]:
                return MagicMock(returncode=0, stdout="core\nextra\n")
            if cmd == ["pacman-conf", "-r", "core"]:
                return MagicMock(returncode=0, stdout="Server = https://mirror.example.org/core/os/x86_64\n")
            if cmd == ["pacman-conf", "-r", "extra"]:
                return MagicMock(returncode=0, stdout="Server = https://mirror.example.org/extra/os/x86_64\n")
            return MagicMock(returncode=1, stdout="")

        lines = [
            ":: Synchronizing package databases...\n",
            " core is up to date\n",
            " extra                 150.0 KiB  1.2 MiB/s 00:00 [##] 50%\n",
            " extra                 300.0 KiB  2.0 MiB/s 00:00 [##] 100%\n",
            "warning: minor sync warning\n",
            "",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.returncode = 0

        buf, con = _con(width=120)
        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("apt_pac.commands.console", con),
            patch("apt_pac.commands.alpm_helper.reset_handle"),
        ):
            commands.sync_databases(["pacman", "-Sy"], quiet=0, include_aur=True)

        out = buf.getvalue()
        self.assertIn("Hit:1 https://mirror.example.org core", out)
        self.assertEqual(out.count("Get:2 https://mirror.example.org extra"), 1)
        self.assertIn("W: minor sync warning", out)
        self.assertIn("Get:3 https://aur.archlinux.org AUR", out)

        buf_err, con_err = _con(width=120)
        err_proc = MagicMock()
        err_proc.stdout.readline.side_effect = ["error: failed to synchronize all databases\n", ""]
        err_proc.returncode = 1
        with (
            patch("subprocess.run", side_effect=fake_run),
            patch("subprocess.Popen", return_value=err_proc),
            patch("apt_pac.commands.console", con_err),
        ):
            with self.assertRaises(SystemExit) as cm:
                commands.sync_databases(["pacman", "-Sy"], include_aur=True)
            self.assertEqual(cm.exception.code, 1)
        self.assertIn("E: failed to synchronize all databases", buf_err.getvalue())
        self.assertNotIn("AUR", buf_err.getvalue())

    def test_autoclean_simulation_and_real(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda s, k, d=None: 1 if k == "verbosity" else d
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.alpm_helper.clean_cache", return_value=2048000) as mock_clean,
            patch("apt_pac.commands.console"),
        ):
            commands.execute_command("autoclean", ["-s"])
            mock_clean.assert_called_once_with(keep=3, dry_run=True, verbose=True)

            mock_clean.reset_mock()
            commands.execute_command("autoclean", [])
            mock_clean.assert_called_once_with(keep=3, dry_run=False, verbose=True)

    def test_show_output_pacman_bypasses_wrapper(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = (
            lambda s, k, d=None: "pacman"
            if k == "show_output"
            else (1 if k == "verbosity" else d)
        )
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.check_safeguards"),
            patch("apt_pac.commands.os.path.isfile", return_value=False),
            patch("apt_pac.commands.aur.is_in_official_repos", return_value=True),
            patch("apt_pac.commands.run_pacman_with_apt_output") as mock_wrap,
            patch("apt_pac.commands.sync_databases") as mock_sync,
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        ):
            commands.execute_command("install", ["bash"])
            mock_wrap.assert_not_called()
            self.assertTrue(any("pacman" in str(c) and "-S" in str(c) for c in mock_run.call_args_list))

            mock_run.reset_mock()
            commands.execute_command("update", [])
            mock_sync.assert_not_called()
            mock_wrap.assert_not_called()
            self.assertTrue(any("-Sy" in str(c) for c in mock_run.call_args_list))

    def test_depends_rdepends_policy_madison_stats_news_and_tty(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = lambda s, k, d=None: 1 if k == "verbosity" else d

        fake_pkg = SimpleNamespace(
            name="bash",
            depends=["readline>=8.0", "glibc"],
            optdepends=["bash-completion: completion"],
            compute_requiredby=lambda: ["pacman"],
            compute_optionalfor=lambda: ["git"],
        )

        buf, con = _con(width=100)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con),
            patch("apt_pac.commands.alpm_helper.get_local_package", return_value=fake_pkg),
        ):
            commands.execute_command("depends", ["bash"])
            commands.execute_command("rdepends", ["bash"])
        out = buf.getvalue()
        self.assertIn("Depends: readline>=8.0", out)
        self.assertIn("Suggests: bash-completion: completion", out)
        self.assertIn("Reverse Depends:", out)
        self.assertIn("Optional For:", out)

        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.shutil.which", return_value="/usr/bin/pactree"),
            patch("apt_pac.commands.ui.is_linux_console", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        ):
            commands.execute_command("depends", ["--tree", "bash"])
            mock_run.assert_called_with(["pactree", "-a", "bash"], check=False)
            commands.execute_command("rdepends", ["--tree", "bash"])
            mock_run.assert_called_with(["pactree", "-r", "-a", "bash"], check=False)

        # policy merge when local == repo version
        buf_pol, con_pol = _con(width=100)
        core_db = SimpleNamespace(name="core", get_pkg=lambda n: SimpleNamespace(version="5.3.20-1") if n == "bash" else None)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_pol),
            patch("apt_pac.commands.alpm_helper.get_handle", return_value=SimpleNamespace(get_syncdbs=lambda: [core_db])),
            patch("apt_pac.commands.alpm_helper.get_local_package", return_value=SimpleNamespace(version="5.3.20-1")),
        ):
            commands.execute_command("policy", ["bash"])
        out_pol = buf_pol.getvalue()
        self.assertEqual(out_pol.count(" *** 5.3.20-1 500"), 1)
        self.assertIn("500 core", out_pol)
        self.assertIn("100 /var/lib/pacman/local", out_pol)

        # madison aligned columns
        buf_mad, con_mad = _con(width=100)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_mad),
            patch("apt_pac.commands.alpm_helper.get_local_package", return_value=SimpleNamespace(version="5.3.20-1")),
            patch("apt_pac.commands.alpm_helper.get_package", return_value=SimpleNamespace(version="5.3.20-1", db=SimpleNamespace(name="core"))),
        ):
            commands.execute_command("madison", ["bash"])
        mad_lines = [ln for ln in buf_mad.getvalue().splitlines() if "|" in ln]
        self.assertEqual(len(mad_lines), 2)
        self.assertEqual(mad_lines[0].index("|"), mad_lines[1].index("|"))

        # news brackets escaped & dynamic width
        rss = (
            b'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
            b"<item><title>[testing] Update notice</title>"
            b"<pubDate>Mon, 16 Nov 2026 12:00:00 +0000</pubDate>"
            b"<link>https://archlinux.org/news/test/</link>"
            b"<description>Check [installed] status carefully.</description>"
            b"</item></channel></rss>"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = rss
        mock_resp.__enter__.return_value = mock_resp
        buf_news, con_news = _con(width=50)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_news),
            patch("apt_pac.ui.console", con_news),
            patch("apt_pac.commands.urllib.request.urlopen", return_value=mock_resp),
            patch("apt_pac.commands.shutil.which", return_value=None),
        ):
            commands.execute_command("news", [])
        out_news = buf_news.getvalue()
        self.assertIn("[testing] Update notice", out_news)
        self.assertIn("-" * 48, out_news)

        # linux console easter egg & add-repository ASCII panel
        buf_pac, con_pac = _con(width=80)
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.console", con_pac),
            patch("apt_pac.commands.ui.console", con_pac),
            patch("apt_pac.commands.ui.is_linux_console", return_value=True),
            patch("apt_pac.commands._confirm_yes", return_value=False),
            patch("apt_pac.commands.alpm_helper.get_all_repo_packages", return_value=[SimpleNamespace()]),
            patch("apt_pac.commands.alpm_helper.get_installed_packages", return_value=[SimpleNamespace()]),
            patch("apt_pac.commands.alpm_helper.get_orphan_packages", return_value=[]),
            patch("apt_pac.commands.alpm_helper.get_available_updates", return_value=[]),
            patch("apt_pac.commands.alpm_helper.get_cache_dirs", return_value=[]),
        ):
            commands.execute_command("pacman", [])
            commands.execute_command("add-repository", [])
            commands.execute_command("stats", [])
        out_tty = buf_pac.getvalue()
        self.assertIn("C.... o  o  o", out_tty)
        self.assertIn("Waka waka", out_tty)
        self.assertIn("+--", out_tty)
        self.assertNotIn("╭", out_tty)
        self.assertIn("Total packages", out_tty)

    def test_quiet_disables_progress(self):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = ["(1/1) installing foo (1.0-1)\n", ""]
        mock_proc.returncode = 0
        mock_prog = MagicMock()
        mock_prog.__enter__.return_value = mock_prog
        mock_prog.__exit__.return_value = False
        mock_prog.add_task.return_value = 1

        buf, con = _con(width=80)
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("subprocess.run"),
            patch("apt_pac.commands.Progress", return_value=mock_prog) as mock_prog_cls,
            patch("apt_pac.commands.console", con),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "foo"], quiet=1)
        self.assertTrue(ok)
        self.assertTrue(mock_prog_cls.call_args.kwargs.get("disable"))


if __name__ == "__main__":
    unittest.main()
