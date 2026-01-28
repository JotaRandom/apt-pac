import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import aur


class TestRecursiveAur(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch("apt_pac.ui.console.print")
        self.mock_console = self.console_patcher.start()

        # Mock input to say 'y'
        self.input_patcher = patch("apt_pac.ui.console.input", return_value="y")
        self.mock_input = self.input_patcher.start()

        self.run_patcher = patch("subprocess.run")
        self.mock_run = self.run_patcher.start()

        self.rpc_patcher = patch("apt_pac.aur.get_aur_info")
        self.mock_rpc = self.rpc_patcher.start()

        # Mock config
        self.config_patcher = patch("apt_pac.aur.get_config")
        self.mock_get_config = self.config_patcher.start()
        self.mock_config_instance = MagicMock()
        self.mock_config_instance.cache_dir = Path("/tmp/mock_cache")
        self.mock_config_instance.get.return_value = "auto"  # for build_user
        self.mock_get_config.return_value = self.mock_config_instance

        # Mock install summary to avoid UI complexity
        self.summary_patcher = patch("apt_pac.aur.print_transaction_summary")
        self.mock_summary = self.summary_patcher.start()

        # Mock os.getuid to simulate non-root (simplifies flow)
        self.getuid_patcher = patch("os.getuid", return_value=1000)
        self.mock_getuid = self.getuid_patcher.start()

        # Mock _download_source_silent (internal method used by installer)
        self.download_patcher = patch(
            "apt_pac.aur.AurInstaller._download_source_silent", return_value=True
        )
        self.mock_download = self.download_patcher.start()

        # Mock is_installed (none installed)
        self.installed_patcher = patch("apt_pac.aur.is_installed", return_value=False)
        self.mock_is_installed = self.installed_patcher.start()

        # Mock is_in_official_repos (False for AUR pkgs)
        self.official_patcher = patch(
            "apt_pac.aur.is_in_official_repos", return_value=False
        )
        self.mock_is_official = self.official_patcher.start()

        # Mock glob for package file finding
        self.glob_patcher = patch("pathlib.Path.glob")
        self.mock_glob = self.glob_patcher.start()
        # Return a mock package file
        mock_pkg = MagicMock()
        mock_pkg.stem = "test-pkg-1.0-1-any"
        mock_pkg.__str__.return_value = (
            "/tmp/mock_build/pkg/test-pkg-1.0-1-any.pkg.tar.zst"
        )
        self.mock_glob.return_value = [mock_pkg]

        # Mock Path.exists to force git clone (return False)
        self.exists_patcher = patch("pathlib.Path.exists", return_value=False)
        self.mock_exists = self.exists_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.run_patcher.stop()
        self.rpc_patcher.stop()
        self.config_patcher.stop()
        self.summary_patcher.stop()
        self.getuid_patcher.stop()
        self.download_patcher.stop()
        self.installed_patcher.stop()
        self.official_patcher.stop()
        self.glob_patcher.stop()
        self.exists_patcher.stop()

    def test_recursive_aur_build_and_cleanup(self):
        # Scenario:
        # 'leaf-pkg' (AUR) depends on 'mid-pkg' (AUR)
        # 'mid-pkg' (AUR) has no deps
        # 'leaf-pkg' also has 'make-dep-pkg' (MakeDepends) - effectively checked via -r flag

        # Set up RPC return values
        def side_effect_rpc(pkgs):
            # print(f"DEBUG: get_aur_info called with: {pkgs}")
            results = []
            for p in pkgs:
                if p == "leaf-pkg":
                    results.append(
                        {
                            "Name": "leaf-pkg",
                            "PackageBase": "leaf-pkg",
                            "Version": "2.0-1",
                            "Depends": ["mid-pkg"],
                            "MakeDepends": ["make-dep-pkg"],
                        }
                    )
                elif p == "mid-pkg":
                    results.append(
                        {
                            "Name": "mid-pkg",
                            "PackageBase": "mid-pkg",
                            "Version": "1.0-1",
                            "Depends": [],
                        }
                    )
                elif p == "make-dep-pkg":
                    results.append(
                        {
                            "Name": "make-dep-pkg",
                            "PackageBase": "make-dep-pkg",
                            "Version": "0.9-1",
                            "Depends": [],
                        }
                    )
            return results

        self.mock_rpc.side_effect = side_effect_rpc

        # run_pacman_with_apt_output mock needed for install step
        with patch("apt_pac.commands.run_pacman_with_apt_output", return_value=True):
            installer = aur.AurInstaller()
            installer.install(["leaf-pkg"], verbose=True, auto_confirm=True)

            # VERIFICATION

            # 1. Verify resolving and build order
            # mid-pkg should be downloaded/built FIRST
            # leaf-pkg should be downloaded/built SECOND
            self.mock_download.assert_has_calls(
                [
                    call(
                        "mid-pkg",
                        self.mock_config_instance.cache_dir
                        / "sources"
                        / "aur"
                        / "mid-pkg",
                        True,
                    ),
                    call(
                        "make-dep-pkg",
                        self.mock_config_instance.cache_dir
                        / "sources"
                        / "aur"
                        / "make-dep-pkg",
                        True,
                    ),
                    call(
                        "leaf-pkg",
                        self.mock_config_instance.cache_dir
                        / "sources"
                        / "aur"
                        / "leaf-pkg",
                        True,
                    ),
                ],
                any_order=False,
            )  # Order matters!

            # 2. Verify makepkg command includes -r
            # We look for subprocess.run calls
            # Expected cmd: ['makepkg', '-sfr', '--needed', '--noconfirm'] (since auto_confirm=True)

            makepkg_calls = []
            for c in self.mock_run.call_args_list:
                args = c[0]
                if args and isinstance(args[0], list) and args[0][0] == "makepkg":
                    makepkg_calls.append(args[0])

            self.assertTrue(
                len(makepkg_calls) >= 2, "Should have called makepkg at least twice"
            )

            # Verify command flags
            for cmd in makepkg_calls:
                self.assertIn("-f", cmd, "makepkg command should include -f")
                self.assertIn("--needed", cmd)
                self.assertIn("--noconfirm", cmd)


if __name__ == "__main__":
    unittest.main()
