import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import commands

class TestUpgrade(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.ui.console.print')
        self.mock_console_print = self.console_patcher.start()
        
        # Mock os.path.exists for lock file check
        self.exists_patcher = patch('os.path.exists', return_value=False)
        self.mock_exists = self.exists_patcher.start()
        
        # Use patch.object on the actual console instance to correspond exactly
        self.input_patcher = patch.object(commands.console, 'input', return_value='y')
        self.mock_console_input = self.input_patcher.start()
        
        self.getuid_patcher = patch('os.getuid', return_value=0, create=True)
        self.mock_getuid = self.getuid_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.getuid_patcher.stop()
        self.exists_patcher.stop()

    def test_upgrade_summary_interactive(self):
        # Mocks
        # valid filename for parsing: name-ver-rel-arch.pkg.tar.zst
        sim_mock = MagicMock(returncode=0, stdout="http://mirror/pkg-2.0-1-any.pkg.tar.zst\n") 
        qi_mock = MagicMock(returncode=0, stdout="Name : pkg\nInstalled Size : 100.00 KiB\n")
        
        def side_effect(cmd, **kwargs):
            if "-Sp" in cmd: # Simulation
                if "-u" not in cmd:
                    raise ValueError("Missing -u in upgrade simulation")
                return sim_mock
            elif "-Qi" in cmd:
                return qi_mock
            elif "-Qdtq" in cmd: return MagicMock(returncode=1, stdout="")
            elif "-Q" in cmd and "-Qi" not in cmd and "-Qq" not in cmd: 
                # Check installed (pacman -Q args)
                # Output format: name version
                return MagicMock(returncode=0, stdout="pkg 1.0\n")
            elif "-Qu" in cmd:
                return MagicMock(returncode=0, stdout="pkg 1.0 -> 2.0\n")
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect) as mock_run, \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True) as mock_run_apt, \
             patch('apt_pac.commands.sync_databases'), \
             patch('apt_pac.alpm_helper') as mock_alpm, \
             patch('subprocess.run') as mock_sub:
             
             # Mock update info
             mock_alpm.get_available_updates.return_value = [('pkg', '1.0', '2.0')]
             mock_pkg = MagicMock()
             mock_pkg.download_size = 100 * 1024
             mock_pkg.isize = 200 * 1024
             mock_pkg.optdeps = []
             mock_alpm.get_package.return_value = mock_pkg
             mock_local = MagicMock()
             mock_local.optdepends = []
             mock_alpm.get_local_package.return_value = mock_local
             mock_alpm.is_package_installed.return_value = True
             mock_alpm.is_in_official_repos.return_value = True # Assume official for these tests
             
             mock_sub.side_effect = side_effect
             
             # Run upgrade (interactive)
             commands.execute_command("upgrade", [])
             
             # Calls
             # 1. show_summary -> run_pacman(-Sp -u)
             # 2. prompt input (mocked 'y')
             # 3. run_pacman_with_apt_output(--noconfirm)
             
             # self.mock_console_input.assert_called_once()
             
             # Verify run command has --noconfirm
             args, _ = mock_run_apt.call_args
             self.assertIn("--noconfirm", args[0])
             
             # Output Check
             full_output = "\n".join([str(call[0][0]) for call in self.mock_console_print.call_args_list if call[0]])
             self.assertIn("Upgrading: 2", full_output)

    def test_upgrade_auto_confirm(self):
        # Mocks
        sim_mock = MagicMock(returncode=0, stdout="http://mirror/pkg-2.0-1-any.pkg.tar.zst\n") 
        qi_mock = MagicMock(returncode=0, stdout="Name : pkg\nInstalled Size : 100.00 KiB\n")
        
        def side_effect(cmd, **kwargs):
            if "-Sp" in cmd: return sim_mock
            if "-Qi" in cmd: return qi_mock
            if "-Qdtq" in cmd: return MagicMock(returncode=1, stdout="")
            if "-Q" in cmd and "-Qi" not in cmd and "-Qq" not in cmd:
                 return MagicMock(returncode=0, stdout="pkg 1.0\n")
            if "-Qu" in cmd: return MagicMock(returncode=0, stdout="pkg 1.0 -> 2.0\n")
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect) as mock_run, \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True) as mock_run_apt, \
             patch('apt_pac.commands.sync_databases'), \
             patch('apt_pac.alpm_helper') as mock_alpm, \
             patch('subprocess.run') as mock_sub:
             
             # Mock update info
             mock_alpm.get_available_updates.return_value = [('pkg', '1.0', '2.0')]
             mock_pkg = MagicMock()
             mock_pkg.download_size = 100 * 1024
             mock_pkg.isize = 200 * 1024
             mock_pkg.optdepends = []
             mock_alpm.get_package.return_value = mock_pkg
             mock_local = MagicMock()
             mock_local.version = '1.0'
             mock_local.isize = 100 * 1024
             mock_local.optdepends = []
             mock_alpm.get_local_package.return_value = mock_local
             mock_alpm.is_package_installed.return_value = True
             
             mock_sub.side_effect = side_effect
             
             # Update global auto_confirm via flag? No, pass extra_args=["-y"]?
             # But run_pacman parses args internally?
             # commands.execute_command parses args.
             
             commands.execute_command("upgrade", ["-y"])
             
             # Should NOT prompt
             self.mock_console_input.assert_not_called()
             
             # Should still run with --noconfirm
             args, _ = mock_run_apt.call_args
             self.assertIn("--noconfirm", args[0])
             
             # Output Check
             # Summary should still be printed (columns)
             full_output = "\n".join([str(call[0][0]) for call in self.mock_console_print.call_args_list if call[0]])
             self.assertIn("Upgrading: 2", full_output)

if __name__ == '__main__':
    unittest.main()
