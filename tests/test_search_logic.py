import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import apt_pac.aur as aur
import apt_pac.commands as commands


class TestSearchLogic(unittest.TestCase):
    @patch("apt_pac.aur._set_cached")
    @patch("apt_pac.aur._get_cached", return_value=None)
    @patch("urllib.request.urlopen")
    def test_aur_rpc_live(self, mock_urlopen, mock_get_cached, mock_set_cached):
        """Test AUR RPC search parsing offline with mocked response."""
        import json

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            {
                "version": 5,
                "type": "search",
                "resultcount": 1,
                "results": [{"Name": "google-chrome", "Version": "133.0-1"}],
            }
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        results = aur.search_aur("google-chrome")
        found = any(p["Name"] == "google-chrome" for p in results)
        self.assertTrue(len(results) > 0)
        self.assertTrue(found)

    @patch("apt_pac.ui.console.print")
    @patch("apt_pac.commands.alpm_helper")
    def test_command_dispatch_official(self, mock_alpm, mock_print):
        """Test normal search (Official only)"""
        print("\nTesting Dispatch: --official...")

        # Mock alpm search
        mock_pkg = MagicMock()
        mock_pkg.name = "firefox"
        mock_pkg.version = "133.0-1"
        mock_pkg.desc = "Fast browser"
        mock_pkg.db.name = "extra"

        mock_alpm.search_packages.return_value = [mock_pkg]

        # Mock config object
        mock_config = MagicMock()
        mock_config.get.side_effect = (
            lambda section, option, default=None: "apt-pac"
            if option == "show_output"
            else default
        )

        with patch("apt_pac.commands.get_config", return_value=mock_config):
            commands.execute_command("search", ["firefox", "--official"])

        # Verify alpm_helper was called
        mock_alpm.search_packages.assert_called_with("firefox")
        print("  ALPM search called correctly.")

    @patch("apt_pac.aur.search_aur")
    @patch("subprocess.run")
    @patch("apt_pac.ui.console.print")
    def test_command_dispatch_aur(self, mock_print, mock_run, mock_aur_search):
        """Test AUR search flag"""
        print("\nTesting Dispatch: --aur...")

        mock_aur_search.return_value = [
            {"Name": "google-chrome", "Version": "1.0", "NumVotes": 100}
        ]

        # Mock pacman to do nothing (it shouldn't be called for search if scope is aur)
        # Wait, my logic calls pacman regardless of scope?
        # Checking implementation:
        # if scope in ["both", "official"]: call pacman
        # So if scope == "aur", pacman is NOT called for search.

        mock_config = MagicMock()
        mock_config.get.side_effect = (
            lambda section, option, default=None: "apt-pac"
            if option == "show_output"
            else default
        )

        with patch("apt_pac.commands.get_config", return_value=mock_config):
            commands.execute_command("search", ["google-chrome", "--aur"])

        # Verify AUR was called
        mock_aur_search.assert_called_with("google-chrome")
        print("  AUR search called correctly.")

        # Verify pacman was NOT called for search results
        # Note: subprocess might be called for other things? No.
        # Check call args of mock_run.
        # Actually execute_command builds 'pacman_cmd' at start.
        # But invocation of subprocess.run(pacman_cmd...) is inside `if scope in...`

        # Ensure 'pacman -Ss' was NOT run
        for call in mock_run.call_args_list:
            args = call[0][0]
            if "pacman" in args and "-Ss" in args:
                self.fail("Pacman -Ss should not be called in --aur mode")


if __name__ == "__main__":
    unittest.main()
