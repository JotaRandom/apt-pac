import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import commands


class TestUpgradeVersions(unittest.TestCase):
    # setUp/tearDown removed to rely on decorators
    pass

    @patch.object(commands, "sync_databases")
    @patch("apt_pac.commands.alpm_helper")
    @patch("apt_pac.commands.ui.print_columnar_list")
    @patch("apt_pac.commands.console")
    @patch.object(commands, "get_config")
    @patch.object(commands, "run_pacman")
    @patch("apt_pac.commands.run_pacman_with_apt_output", return_value=True)
    @patch("apt_pac.commands.subprocess.run")
    @patch("apt_pac.aur.download_aur_source", return_value=True)
    @patch("apt_pac.aur.subprocess.run")
    @patch.dict(os.environ, {"SUDO_USER": "testuser"})
    @patch("os.getuid", return_value=0)
    @patch("apt_pac.aur.check_updates", return_value=[])
    @patch("apt_pac.aur.get_installed_aur_packages", return_value=[])
    @patch("pathlib.Path.glob")
    @patch("builtins.input", return_value="y")
    def test_upgrade_official_version(
        self,
        mock_input,
        mock_glob,
        mock_aur_inst,
        mock_aur_chk,
        mock_getuid,
        mock_aur_sub,
        mock_aur_dl,
        mock_sub,
        mock_run_apt,
        mock_run,
        mock_config,
        mock_console,
        mock_print_col,
        mock_alpm_helper,
        mock_sync,
    ):
        # Configure glob to return a fake package
        mock_pkg = MagicMock()
        mock_pkg.name = "core-pkg-2.0-1-any.pkg.tar.zst"
        mock_glob.return_value = [mock_pkg]
        # Mocks
        sim_mock = MagicMock(
            returncode=0, stdout="http://mirror/core-pkg-2.0-1-any.pkg.tar.zst\n"
        )
        qi_mock = MagicMock(
            returncode=0, stdout="Name : core-pkg\nInstalled Size : 100.00 KiB\n"
        )

        mock_sub.side_effect = (
            lambda cmd, **kwargs: sim_mock if "-Sp" in cmd else qi_mock
        )
        mock_run.side_effect = lambda *args, **kwargs: 0
        mock_aur_sub.return_value.returncode = 0

        mock_config.return_value = MagicMock()

        def config_side_effect(section, key, default=None):
            if key == "warn_partial_upgrades":
                return True
            if key == "verbosity":
                return 1
            return default

        mock_config.return_value.get.side_effect = config_side_effect

        # New ALPM Helper Mocks via Module Mock
        # Mock updates
        mock_alpm_helper.get_available_updates.return_value = [
            ("core-pkg", "1.0", "2.0-1")
        ]
        # Mock package info (Must return objects with attributes)
        pkg_mock = MagicMock()
        pkg_mock.name = "core-pkg"
        pkg_mock.size = 102400
        pkg_mock.download_size = 102400  # Required for show_summary size calc
        pkg_mock.isize = 204800
        pkg_mock.optdepends = []
        pkg_mock.version = "2.0-1"  # Important for map check
        mock_alpm_helper.get_package.return_value = pkg_mock

        local_mock = MagicMock()
        local_mock.name = "core-pkg"
        local_mock.version = "1.0"
        local_mock.isize = 102400
        local_mock.optdepends = []
        mock_alpm_helper.get_local_package.return_value = local_mock

        mock_alpm_helper.is_package_installed.return_value = True
        mock_alpm_helper.is_in_official_repos.return_value = True

        with patch("apt_pac.commands.sys.argv", ["/usr/bin/apt-pac"]):
            try:
                commands.execute_command("upgrade", [])
            except SystemExit as e:
                if e.code != 0:
                    raise

        # Verify output
        mock_print_col.assert_called_with(
            ["core-pkg ([dim]1.0[/dim] -> [bold]2.0-1[/bold])"], "green"
        )

    @patch.object(commands, "sync_databases")
    @patch("apt_pac.commands.alpm_helper")
    @patch("apt_pac.commands.ui.print_columnar_list")
    @patch("apt_pac.commands.console")
    @patch.object(commands, "get_config")
    @patch.object(commands, "run_pacman")
    @patch("apt_pac.commands.run_pacman_with_apt_output", return_value=True)
    @patch("apt_pac.commands.subprocess.run")
    @patch("apt_pac.aur.download_aur_source", return_value=True)
    @patch("apt_pac.aur.subprocess.run")
    @patch.dict(os.environ, {"SUDO_USER": "testuser"})
    @patch("os.getuid", return_value=0)
    @patch("apt_pac.aur.check_updates", return_value=[])
    @patch("apt_pac.aur.get_installed_aur_packages", return_value=[])
    @patch("pathlib.Path.glob")
    @patch("builtins.input", return_value="y")
    def test_upgrade_aur_version(
        self,
        mock_input,
        mock_glob,
        mock_aur_inst,
        mock_aur_chk,
        mock_getuid,
        mock_aur_sub,
        mock_aur_dl,
        mock_sub,
        mock_run_apt,
        mock_run,
        mock_config,
        mock_console,
        mock_print_col,
        mock_alpm_helper,
        mock_sync,
    ):
        # Configure glob to return a fake package
        mock_pkg = MagicMock()
        mock_pkg.name = "aur-pkg-1.1-any.pkg.tar.zst"
        mock_glob.return_value = [mock_pkg]
        # Mocks
        sim_mock = MagicMock(
            returncode=0, stdout="http://mirror/aur-pkg-1.1-any.pkg.tar.zst\n"
        )
        qi_mock = MagicMock(
            returncode=0, stdout="Name : aur-pkg\nInstalled Size : 100.00 KiB\n"
        )

        mock_sub.side_effect = (
            lambda cmd, **kwargs: sim_mock if "-Sp" in cmd else qi_mock
        )
        mock_run.side_effect = lambda *args, **kwargs: 0
        mock_aur_sub.return_value.returncode = 0

        mock_config.return_value = MagicMock()

        def config_side_effect(section, key, default=None):
            if key == "warn_partial_upgrades":
                return True
            if key == "verbosity":
                return 1
            return default

        mock_config.return_value.get.side_effect = config_side_effect

        # New ALPM Helper Mocks via Module Mock
        # Mock updates
        mock_alpm_helper.get_available_updates.return_value = [
            ("aur-pkg", "1.0", "1.1")
        ]
        # Mock package info
        pkg_mock = MagicMock()
        pkg_mock.name = "aur-pkg"
        pkg_mock.size = 102400
        pkg_mock.download_size = 102400  # Required for show_summary size calc
        pkg_mock.isize = 204800
        pkg_mock.optdepends = []
        pkg_mock.version = "1.1"
        mock_alpm_helper.get_package.return_value = pkg_mock

        local_mock = MagicMock()
        local_mock.name = "aur-pkg"
        local_mock.version = "1.0"
        local_mock.isize = 102400
        local_mock.optdepends = []
        mock_alpm_helper.get_local_package.return_value = local_mock

        mock_alpm_helper.is_package_installed.return_value = True
        mock_alpm_helper.is_in_official_repos.return_value = False

        with patch("apt_pac.commands.sys.argv", ["/usr/bin/apt-pac"]):
            try:
                commands.execute_command("upgrade", [])
            except SystemExit as e:
                if e.code != 0:
                    raise

        # Verify AUR formatting
        mock_print_col.assert_called_with(
            ["aur-pkg ([dim]1.0[/dim] -> [bold]1.1[/bold])"], "green"
        )


if __name__ == "__main__":
    unittest.main()
