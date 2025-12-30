
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import apt_pac.aur as aur
import apt_pac.commands as commands
import apt_pac.ui as ui

class TestSearchLogic(unittest.TestCase):
    
    def test_aur_rpc_live(self):
        """Test the actual AUR RPC connection (requires internet)"""
        print("\nTesting AUR RPC (Live)...")
        results = aur.search_aur("google-chrome")
        found = any(p['Name'] == 'google-chrome' for p in results)
        print(f"  Search 'google-chrome': Found {len(results)} results. Match found: {found}")
        self.assertTrue(len(results) > 0)
        self.assertTrue(found)

    @patch('subprocess.run')
    @patch('apt_pac.ui.console.print')
    def test_command_dispatch_official(self, mock_print, mock_run):
        """Test normal search (Official only)"""
        print("\nTesting Dispatch: --official...")
        
        # Mock pacman response
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "extra/firefox 133.0-1\n    Fast browser"
        mock_run.return_value = mock_proc
        
        # Mock config object
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda section, option, default=None: 'apt-pac' if option == 'show_output' else default
        
        with patch('apt_pac.commands.get_config', return_value=mock_config):
            commands.execute_command("search", ["firefox", "--official"])
            
        # Verify pacman was called
        args, _ = mock_run.call_args
        self.assertIn("pacman", args[0])
        self.assertIn("-Ss", args[0])
        self.assertIn("firefox", args[0])
        print("  Pacman called correctly.")

    @patch('apt_pac.aur.search_aur')
    @patch('subprocess.run')
    @patch('apt_pac.ui.console.print')
    def test_command_dispatch_aur(self, mock_print, mock_run, mock_aur_search):
        """Test AUR search flag"""
        print("\nTesting Dispatch: --aur...")
        
        mock_aur_search.return_value = [{"Name": "google-chrome", "Version": "1.0", "NumVotes": 100}]
        
        # Mock pacman to do nothing (it shouldn't be called for search if scope is aur)
        # Wait, my logic calls pacman regardless of scope? 
        # Checking implementation: 
        # if scope in ["both", "official"]: call pacman
        # So if scope == "aur", pacman is NOT called for search.
        
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda section, option, default=None: 'apt-pac' if option == 'show_output' else default

        with patch('apt_pac.commands.get_config', return_value=mock_config):
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

if __name__ == '__main__':
    unittest.main()
