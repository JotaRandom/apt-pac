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
        
        self.input_patcher = patch('apt_pac.ui.console.input', return_value='y')
        self.mock_console_input = self.input_patcher.start()
        
        self.getuid_patcher = patch('os.getuid', return_value=0, create=True)
        self.mock_getuid = self.getuid_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.getuid_patcher.stop()

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
            elif "-Q" in cmd and "-Qi" not in cmd and "-Qq" not in cmd: 
                # Check installed (pacman -Q args)
                # Output format: name version
                return MagicMock(returncode=0, stdout="pkg 1.0\n")
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect) as mock_run, \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True) as mock_run_apt, \
             patch('subprocess.run', return_value=MagicMock(returncode=0)):
             
             # Run upgrade (interactive)
             commands.execute_command("upgrade", [])
             
             # Calls
             # 1. show_summary -> run_pacman(-Sp -u)
             # 2. prompt input (mocked 'y')
             # 3. run_pacman_with_apt_output(--noconfirm)
             
             self.mock_console_input.assert_called_once()
             
             # Verify run command has --noconfirm
             args, _ = mock_run_apt.call_args
             self.assertIn("--noconfirm", args[0])
             
             # Output Check
             full_output = "\n".join([str(call[0][0]) for call in self.mock_console_print.call_args_list if call[0]])
             self.assertIn("Upgrading: 1", full_output)

    def test_upgrade_auto_confirm(self):
        # Mocks
        sim_mock = MagicMock(returncode=0, stdout="http://mirror/pkg-2.0-1-any.pkg.tar.zst\n") 
        qi_mock = MagicMock(returncode=0, stdout="Name : pkg\nInstalled Size : 100.00 KiB\n")
        
        def side_effect(cmd, **kwargs):
            if "-Sp" in cmd: return sim_mock
            if "-Qi" in cmd: return qi_mock
            if "-Q" in cmd and "-Qi" not in cmd and "-Qq" not in cmd:
                 return MagicMock(returncode=0, stdout="pkg 1.0\n")
            return MagicMock(returncode=0)

        with patch.object(commands, 'run_pacman', side_effect=side_effect) as mock_run, \
             patch.object(commands, 'run_pacman_with_apt_output', return_value=True) as mock_run_apt, \
             patch('subprocess.run', return_value=MagicMock(returncode=0)):
             
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
             self.assertIn("Upgrading: 1", full_output)

if __name__ == '__main__':
    unittest.main()
