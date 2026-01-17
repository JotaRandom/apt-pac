import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import commands

class TestUpgradeVersions(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.commands.console')
        self.mock_console = self.console_patcher.start()
        self.mock_console.input.return_value = 'n'
        
        self.getuid_patcher = patch('os.getuid', return_value=0, create=True)
        self.mock_getuid = self.getuid_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.getuid_patcher.stop()

    def test_upgrade_official_version(self):
        # Mocks
        sim_mock = MagicMock(returncode=0, stdout="http://mirror/core-pkg-2.0-1-any.pkg.tar.zst\n") 
        qi_mock = MagicMock(returncode=0, stdout="Name : core-pkg\nInstalled Size : 100.00 KiB\n")
        
        def side_effect(cmd, **kwargs):
            if "-Sp" in cmd: 
                # Upgrades need -u
                if "-u" not in cmd: return MagicMock(returncode=0, stdout="")
                return sim_mock
            elif "-Qi" in cmd: return qi_mock
            elif "-Q" in cmd: return MagicMock(returncode=0, stdout="core-pkg 1.0\n") # Installed
            elif "-Qu" in cmd: return MagicMock(returncode=0, stdout="core-pkg 1.0 -> 2.0-1\n")
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect), \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True), \
             patch('apt_pac.ui.print_columnar_list') as mock_print_col, \
             patch('subprocess.run', return_value=MagicMock(returncode=0, stdout="")):
             
             try:
                 commands.execute_command("upgrade", [])
             except SystemExit:
                 pass
             
             # Check call args
             # Expect: core-pkg ([dim]1.0[/dim] -> [bold]2.0-1[/bold])
             mock_print_col.assert_called_with(['core-pkg ([dim]1.0[/dim] -> [bold]2.0-1[/bold])'], 'green')
             
    def test_upgrade_aur_version(self):
        # Mocks for AUR
        updates = [{'name': 'aur-pkg', 'current': '1.0', 'new': '1.1'}]
        
        def side_effect_subprocess(cmd, **kwargs):
             if "-Qdtq" in cmd: return MagicMock(returncode=1, stdout="")
             return MagicMock(returncode=0, stdout="")

        with patch('apt_pac.commands.aur.check_updates', return_value=updates), \
             patch('apt_pac.ui.print_columnar_list') as mock_print_col, \
             patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True), \
             patch('subprocess.run', side_effect=side_effect_subprocess), \
             patch('apt_pac.commands.aur.AurResolver') as MockResolver:
             
             # Setup implementation of resolve
             instance = MockResolver.return_value
             # Return just the package itself as if resolved
             instance.resolve.return_value = [{'Name': 'aur-pkg', 'Version': '1.1'}]
             instance.official_deps = []
             
             try:
                 commands.execute_command("upgrade", [])
             except SystemExit:
                 pass
             
             # Check AUR output - should be called with list ["aur-pkg [bold]1.1[/bold]"]
             # Expect: aur-pkg ([dim]1.0[/dim] -> [bold]1.1[/bold])
             mock_print_col.assert_called_with(['aur-pkg ([dim]1.0[/dim] -> [bold]1.1[/bold])'], 'green')

if __name__ == '__main__':
    unittest.main()
