import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import commands

class TestUpgradeVersions(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.ui.console.print')
        self.mock_console_print = self.console_patcher.start()
        
        self.input_patcher = patch('apt_pac.ui.console.input', return_value='n') 
        self.mock_console_input = self.input_patcher.start()
        
        self.getuid_patcher = patch('os.getuid', return_value=0, create=True)
        self.mock_getuid = self.getuid_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
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
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect), \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True), \
             patch('apt_pac.commands.print_columnar_list') as mock_print_col, \
             patch('subprocess.run'):
             
             try:
                 commands.execute_command("upgrade", [])
             except SystemExit:
                 pass
             
             # Check call args
             # print_columnar_list(['core-pkg [bold]2.0-1[/bold]'], 'green')
             mock_print_col.assert_called_with(['core-pkg [bold]2.0-1[/bold]'], 'green')
             
    def test_upgrade_aur_version(self):
        # Mocks for AUR
        updates = [{'name': 'aur-pkg', 'current': '1.0', 'new': '1.1'}]
        
        with patch('apt_pac.commands.aur.check_updates', return_value=updates), \
             patch('apt_pac.commands.print_columnar_list') as mock_print_col, \
             patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True), \
             patch('apt_pac.commands.show_summary'), \
             patch('subprocess.run'):
             
             try:
                 commands.execute_command("upgrade", [])
             except SystemExit:
                 pass
             
             # Check AUR output - should be called with list ["aur-pkg [bold]1.1[/bold]"]
             mock_print_col.assert_called_with(['aur-pkg [bold]1.1[/bold]'], 'green')

if __name__ == '__main__':
    unittest.main()
