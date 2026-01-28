import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import apt_pac.commands as commands


class TestShowLogic(unittest.TestCase):
    @patch("apt_pac.aur.get_aur_info")
    @patch("apt_pac.ui.format_aur_info")
    @patch("subprocess.run")
    @patch("apt_pac.ui.console.print")
    def test_show_fallback_to_aur(
        self, mock_print, mock_run, mock_format_aur, mock_get_aur
    ):
        """Test show command falls back to AUR if official and local fail"""
        print("\nTesting Show Fallback logic...")

        # Mock pacman -Si failing
        mock_si = MagicMock()
        mock_si.returncode = 1
        mock_si.stderr = "error: package 'google-chrome' was not found"

        # Mock pacman -Qi failing
        mock_qi = MagicMock()
        mock_qi.returncode = 1

        # Configure side effects for subprocess.run to return different mocks for different calls
        def side_effect(cmd, **kwargs):
            if "-Si" in cmd:
                return mock_si
            if "-Qi" in cmd:
                return mock_qi
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        # Mock AUR returning data
        mock_get_aur.return_value = [{"Name": "google-chrome", "Version": "1.0"}]

        # Mock config
        mock_config = MagicMock()

        def get_conf(section, option, default=None):
            if option == "show_output":
                return "apt-pac"
            if option == "verbosity":
                return 1
            return default

        mock_config.get.side_effect = get_conf

        with patch("apt_pac.commands.get_config", return_value=mock_config):
            commands.execute_command("show", ["google-chrome"])

        # Assertions
        mock_get_aur.assert_called_with(["google-chrome"])
        mock_format_aur.assert_called_once()
        print("  Fallback to AUR success.")


if __name__ == "__main__":
    unittest.main()
