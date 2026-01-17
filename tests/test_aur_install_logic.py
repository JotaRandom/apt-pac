
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import apt_pac.aur as aur
import apt_pac.commands as commands

class TestAurInstallLogic(unittest.TestCase):
    
    @patch('apt_pac.aur.AurInstaller')
    @patch('apt_pac.aur.is_in_official_repos')
    @patch('apt_pac.aur.search_aur')
    @patch('subprocess.run')
    @patch('os.getuid', return_value=0, create=True)
    def test_mixed_install(self, mock_getuid, mock_run, mock_search, mock_is_official, mock_installer_cls):
        """Test mixed Official + AUR install"""
        print("\nTesting Mixed Install Logic...")
        
        # Scenario: apt install git google-chrome
        # git -> Official
        # google-chrome -> AUR
        
        def is_official_side_effect(pkg):
            return pkg == "git"
        
        mock_is_official.side_effect = is_official_side_effect
        mock_search.return_value = True # Assume found in AUR if checked
        
        mock_installer_instance = MagicMock()
        mock_installer_cls.return_value = mock_installer_instance
        
        # Robust config mock
        mock_config = MagicMock()
        def get_conf(section, option, default=None):
            if option == 'verbosity': return 1
            if option == 'show_pacman_command': return False
            return default
        mock_config.get.side_effect = get_conf
        
        with patch('apt_pac.commands.get_config', return_value=mock_config):
            commands.execute_command("install", ["git", "google-chrome"])
            
        # Verify pacman called for git
        found_install = False
        for call in mock_run.call_args_list:
            args = call[0][0]
            if "pacman" in args and "-S" in args and "git" in args:
                found_install = True
                break
        
        self.assertTrue(found_install, "pacman -S git not called")
        print("  Official package 'git' passed to pacman.")
        
        # Verify AUR installer called for google-chrome
        mock_installer_instance.install.assert_called_with(["google-chrome"], verbose=False, auto_confirm=False)
        print("  AUR package 'google-chrome' passed to AurInstaller.")

    @patch('apt_pac.aur.AurInstaller')
    @patch('apt_pac.aur.is_in_official_repos')
    @patch('apt_pac.aur.search_aur')
    @patch('subprocess.run')
    @patch('os.getuid', return_value=0, create=True)
    def test_pure_official(self, mock_getuid, mock_run, mock_search, mock_is_official, mock_installer):
        """Test pure official install (fallback to standard flow)"""
        print("\nTesting Pure Official Install...")
        
        mock_is_official.return_value = True
        
        with patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True):
             commands.execute_command("install", ["git"])
        
        # Should set pacman_cmd standard flow, not trigger installer directly
        # Wait, my logic calls installer directly ONLY if aur_pkgs list is not empty.
        # So it should fall through to `pacman_cmd = ["pacman", "-S"] + extra_args`
        # But execute_command continues execution...
        
        # Mock run should be called ONCE at the END of execute_command
        # We need to ensure AurInstaller was NOT initialized
        mock_installer.assert_not_called()
        print("  AurInstaller properly skipped.")

if __name__ == '__main__':
    unittest.main()
