import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import alpm_helper, aur, cli, commands, config, sources


class TestArchFixes(unittest.TestCase):
    def test_reinstall_uses_pacman_s_without_force(self):
        with (
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.alpm_helper.get_available_updates", return_value=[]),
            patch("apt_pac.commands.simulate_apt_download_output"),
            patch(
                "apt_pac.commands.run_pacman_with_apt_output", return_value=True
            ) as mock_exec,
            patch("apt_pac.commands.console"),
        ):
            commands.execute_command("reinstall", ["bash", "-y"])
            called_cmd = mock_exec.call_args[0][0]
            self.assertNotIn("--force", called_cmd)
            self.assertIn("--noconfirm", called_cmd)
            self.assertIn("bash", called_cmd)

    def test_config_sections_mass_removal_and_always_sync_files(self):
        """Ensure mass_removal_threshold reads [safeguards] and always_sync_files reads [defaults]."""
        mock_cfg = MagicMock()
        seen_lookups = []

        def fake_get(section, key, default=None):
            seen_lookups.append((section, key))
            if (section, key) == ("safeguards", "mass_removal_threshold"):
                return 2
            if (section, key) == ("defaults", "always_sync_files"):
                return False
            return default

        mock_cfg.get.side_effect = fake_get

        with (
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.get_protected_packages", return_value=set()),
            patch(
                "apt_pac.commands.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="pkg1 1.0-1\npkg2 2.0-1\n"),
            ),
            patch("apt_pac.commands.print_transaction_summary"),
            patch("apt_pac.commands.console") as mock_console,
            patch("apt_pac.commands.sync_databases"),
            patch("apt_pac.commands.run_pacman_with_apt_output") as mock_run_apt,
        ):
            mock_console.input.return_value = "n"
            with self.assertRaises(SystemExit):
                commands.check_safeguards("remove", ["pkg1"])
            self.assertIn(("safeguards", "mass_removal_threshold"), seen_lookups)

            commands.execute_command("update", [])
            self.assertIn(("defaults", "always_sync_files"), seen_lookups)
            mock_run_apt.assert_not_called()

    def test_config_hierarchical_merge(self):
        """User config should merge on top of global config rather than skipping it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            global_cfg = tmp / "global.toml"
            user_cfg = tmp / "user.toml"
            global_cfg.write_text(
                '[safeguards]\nmass_removal_threshold = 42\nreview_pkgbuild = "auto"\n',
                encoding="utf-8",
            )
            user_cfg.write_text(
                '[ui]\nverbosity = 2\n',
                encoding="utf-8",
            )

            cfg = config.Config.__new__(config.Config)
            cfg.global_config_path = global_cfg
            cfg.user_config_path = user_cfg
            cfg.config_dir = tmp
            cfg.data = cfg._deep_copy(config.DEFAULT_CONFIG)
            cfg._load()

            self.assertEqual(cfg.get("safeguards", "mass_removal_threshold"), 42)
            self.assertEqual(cfg.get("safeguards", "review_pkgbuild"), "auto")
            self.assertEqual(cfg.get("ui", "verbosity"), 2)

    def test_warn_partial_upgrades_false_skips_prompt(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = (
            lambda s, k, d=None: False if (s, k) == ("safeguards", "warn_partial_upgrades") else d
        )
        with (
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch(
                "apt_pac.commands.alpm_helper.get_available_updates",
                return_value=[("linux", "6.0-1", "6.1-1")],
            ),
            patch("apt_pac.aur.is_in_official_repos", return_value=True),
            patch("apt_pac.commands.show_summary"),
            patch("apt_pac.commands.simulate_apt_download_output"),
            patch("apt_pac.commands.run_pacman_with_apt_output", return_value=True),
            patch("apt_pac.commands.console") as mock_console,
        ):
            commands.execute_command("install", ["bash"])
            mock_console.input.assert_not_called()

    def test_force_colors_does_not_pollute_extra_args(self):
        mock_cfg = MagicMock()
        mock_cfg.get.side_effect = (
            lambda s, k, d=None: True if (s, k) == ("ui", "force_colors") else d
        )
        mock_handle = MagicMock()
        mock_handle.get_syncdbs.return_value = []
        with (
            patch("apt_pac.commands.get_config", return_value=mock_cfg),
            patch("apt_pac.commands.ui.set_force_colors") as mock_set_colors,
            patch("apt_pac.commands.alpm_helper.get_handle", return_value=mock_handle),
            patch("apt_pac.commands.alpm_helper.get_local_package", return_value=None),
            patch("apt_pac.commands.console") as mock_console,
        ):
            commands.execute_command("policy", ["bash"])
            mock_set_colors.assert_called_with(True)
            printed = " ".join(str(c) for c in mock_console.print.call_args_list)
            self.assertNotIn("--color=always", printed)
            self.assertIn("bash:", printed)

    def test_news_parses_dates_under_non_english_locale(self):
        rss = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel><title>Arch News</title>
        <item>
          <title>Manual intervention needed</title>
          <pubDate>Mon, 16 Nov 2026 12:00:00 +0000</pubDate>
          <link>https://archlinux.org/news/test/</link>
          <description>Update glibc carefully.</description>
        </item>
        </channel></rss>"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = rss
        mock_resp.__enter__.return_value = mock_resp

        with (
            patch("apt_pac.commands.urllib.request.urlopen", return_value=mock_resp),
            patch("apt_pac.commands.shutil.which", return_value=None),
            patch.dict(os.environ, {"LANG": "es_ES.UTF-8"}, clear=True),
            patch("apt_pac.commands.console") as mock_console,
        ):
            commands.execute_command("news", [])
            printed = " ".join(str(c) for c in mock_console.print.call_args_list)
            self.assertIn("Manual intervention needed", printed)

    def test_run_pacman_with_apt_output_compact_progress(self):
        simulated_stdout = [
            "(1/3) installing foo (1.0-1)...\n",
            "(2/3) upgrading bar (1.0-1 -> 2.0-1)...\n",
            "(10/10) removing baz...\n",
            ":: Running post-transaction hooks...\n",
            "(1/1) Reloading system manager configuration...\n",
        ]
        process = MagicMock()
        process.stdout.readline.side_effect = simulated_stdout + [""]
        process.returncode = 0

        buf = io.StringIO()
        cap_console = Console(file=buf, force_terminal=False, width=100)
        with (
            patch("apt_pac.commands.console", cap_console),
            patch("subprocess.Popen", return_value=process),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            ok = commands.run_pacman_with_apt_output(["pacman", "-S", "foo"], total_pkgs=3)

        self.assertTrue(ok)
        out = buf.getvalue()
        self.assertIn("Unpacking foo (1.0-1)", out)
        self.assertIn("Preparing to unpack .../bar_2.0-1.pkg ...", out)
        self.assertIn("Removing baz ...", out)
        self.assertIn("Processing triggers for", out)

    def test_sources_parse_srcinfo_without_bash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)
            (pkg_dir / ".SRCINFO").write_text(
                "pkgbase = yay\n"
                "\tpkgdesc = Yet another yogurt\n"
                "\tpkgver = 12.4.2\n"
                "\tpkgrel = 1\n"
                "\turl = https://github.com/Jguer/yay\n"
                "\tarch = x86_64\n"
                "\tlicense = GPL-3.0-or-later\n"
                "\tmakedepends = go\n"
                "\tmakedepends = git\n"
                "\tdepends = pacman\n"
                "pkgname = yay\n",
                encoding="utf-8",
            )
            pkgbuild = pkg_dir / "PKGBUILD"
            pkgbuild.write_text("$(touch /tmp/should_never_run)\n", encoding="utf-8")

            with patch("apt_pac.sources.subprocess.run") as mock_run:
                makedeps = sources.parse_pkgbuild_makedepends(pkgbuild)
                info = sources.parse_pkgbuild_info(pkgbuild)
                mock_run.assert_not_called()

            self.assertEqual(makedeps, ["go", "git"])
            self.assertEqual(info["pkgname"], "yay")
            self.assertEqual(info["pkgver"], "12.4.2")
            self.assertEqual(info["depends"], "pacman")

    def test_cli_leading_flags_and_version(self):
        parsed = cli.parse_args(["-y", "--verbose", "install", "vim"])
        self.assertEqual(parsed.command, "install")
        self.assertEqual(parsed.args, ["-y", "--verbose", "vim"])

        with (
            patch("apt_pac.cli._print_version", side_effect=SystemExit(0)) as mock_ver,
            self.assertRaises(SystemExit),
        ):
            cli.parse_args(["--version", "full"])
        mock_ver.assert_called_with("full")

    def test_alpm_helper_orphans_excludes_optionalfor(self):
        opt_dep_pkg = MagicMock()
        opt_dep_pkg.name = "libwebp"
        opt_dep_pkg.reason = 1  # PKG_REASON_DEPEND
        opt_dep_pkg.compute_requiredby.return_value = []
        opt_dep_pkg.compute_optionalfor.return_value = ["ffmpeg"]

        true_orphan = MagicMock()
        true_orphan.name = "unused-lib"
        true_orphan.reason = 1
        true_orphan.compute_requiredby.return_value = []
        true_orphan.compute_optionalfor.return_value = []

        mock_handle = MagicMock()
        mock_handle.get_localdb.return_value.pkgcache = [opt_dep_pkg, true_orphan]
        with (
            patch("apt_pac.alpm_helper.get_handle", return_value=mock_handle),
            patch("apt_pac.alpm_helper.pyalpm.PKG_REASON_DEPEND", 1),
        ):
            orphans = alpm_helper.get_orphan_packages()
        self.assertEqual([p.name for p in orphans], ["unused-lib"])

    def test_alpm_helper_updates_respects_ignorepkg(self):
        p1 = MagicMock(name="linux", groups=["base"])
        p1.name = "linux"
        p1.version = "6.1.0-1"
        p2 = MagicMock(name="bash", groups=[])
        p2.name = "bash"
        p2.version = "5.2.0-1"

        s1 = MagicMock(version="6.2.0-1")
        s2 = MagicMock(version="5.3.0-1")
        mock_syncdb = MagicMock()
        mock_syncdb.get_pkg.side_effect = lambda n: {"linux": s1, "bash": s2}.get(n)

        mock_handle = MagicMock()
        mock_handle.get_localdb.return_value.pkgcache = [p1, p2]
        mock_handle.get_syncdbs.return_value = [mock_syncdb]

        with (
            patch("apt_pac.alpm_helper.get_handle", return_value=mock_handle),
            patch(
                "apt_pac.alpm_helper._pacman_conf",
                side_effect=lambda k: ["linux"] if k == "IgnorePkg" else [],
            ),
            patch("apt_pac.alpm_helper.pyalpm.vercmp", return_value=1),
        ):
            updates = alpm_helper.get_available_updates()
        self.assertEqual(updates, [("bash", "5.2.0-1", "5.3.0-1")])

    def test_aur_collect_built_packages_excludes_sig_and_debug(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)
            for fname in [
                "foo-1.0-1-x86_64.pkg.tar.zst",
                "foo-1.0-1-x86_64.pkg.tar.zst.sig",
                "foo-debug-1.0-1-x86_64.pkg.tar.zst",
                "foo-debugger-1.0-1-x86_64.pkg.tar.zst",
            ]:
                (pkg_dir / fname).write_bytes(b"x")

            installer = aur.AurInstaller.__new__(aur.AurInstaller)
            files = sorted(p.name for p in installer._collect_built_packages(pkg_dir, "foo"))
            self.assertEqual(
                files,
                [
                    "foo-1.0-1-x86_64.pkg.tar.zst",
                    "foo-debugger-1.0-1-x86_64.pkg.tar.zst",
                ],
            )

    def test_upgrade_aur_only_skips_official_and_preserves_review_flag(self):
        mock_installer = MagicMock()
        with (
            patch("os.getuid", return_value=0, create=True),
            patch("apt_pac.commands.sync_databases") as mock_sync,
            patch("apt_pac.commands.simulate_apt_download_output") as mock_sim,
            patch("apt_pac.commands.run_pacman_with_apt_output") as mock_run_apt,
            patch("apt_pac.commands.show_summary", return_value=True) as mock_summary,
            patch("apt_pac.commands.alpm_helper"),
            patch(
                "apt_pac.aur.check_updates",
                return_value=[{"name": "paru", "current": "2.0", "new": "2.1"}],
            ),
            patch("apt_pac.aur.AurResolver") as mock_res_cls,
            patch("apt_pac.aur.get_resolved_package_info", return_value=[("paru", "2.1")]),
            patch("apt_pac.aur.AurInstaller", return_value=mock_installer),
        ):
            mock_res_cls.return_value.resolve.return_value = [{"Name": "paru", "Version": "2.1"}]
            mock_res_cls.return_value.official_deps = set()

            commands.execute_command("upgrade", ["--aur"])

            mock_sync.assert_not_called()
            mock_sim.assert_not_called()
            mock_run_apt.assert_not_called()
            self.assertTrue(mock_summary.call_args.kwargs["skip_official"])
            install_kwargs = mock_installer.install.call_args.kwargs
            self.assertFalse(install_kwargs["auto_confirm"])
            self.assertTrue(install_kwargs["confirm_pacman"])

    def test_apt_key_adv_strips_literal_adv(self):
        with patch("subprocess.run") as mock_run:
            commands.execute_command("apt-key", ["adv", "--recv-keys", "ABCD"])
            mock_run.assert_called_with(["pacman-key", "--recv-keys", "ABCD"])

    def test_confirm_yes_empty_enter(self):
        with patch("apt_pac.commands.console.input", return_value=""):
            self.assertTrue(commands._confirm_yes("Continue? [Y/n] "))
        with patch("apt_pac.commands.console.input", return_value="n"):
            self.assertFalse(commands._confirm_yes("Continue? [Y/n] "))

    def test_simulate_never_executes_pacman(self):
        with (
            patch("os.getuid", return_value=1000, create=True),
            patch("apt_pac.aur.is_in_official_repos", return_value=True),
            patch("apt_pac.commands.show_summary") as mock_summary,
            patch("apt_pac.commands.run_pacman_with_apt_output") as mock_run_apt,
            patch("apt_pac.commands.sync_databases") as mock_sync,
        ):
            commands.execute_command("install", ["-s", "bash"])
            mock_summary.assert_called_once()
            mock_run_apt.assert_not_called()

            commands.execute_command("upgrade", ["--simulate"])
            mock_sync.assert_not_called()
            mock_run_apt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
