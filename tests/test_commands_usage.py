
import unittest
from unittest.mock import patch
import sys
import os
sys.path.insert(0, os.path.abspath('src'))
from apt_pac.commands import execute_command

class TestCommandsUsage(unittest.TestCase):
    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.print_error")
    def test_rdepends_no_args(self, mock_print_error, mock_console):
        with self.assertRaises(SystemExit) as cm:
            execute_command("rdepends", [])
        
        self.assertEqual(cm.exception.code, 1)
        mock_print_error.assert_called_with("[bold red]E[/bold red]: No package specified")

    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.print_error")
    def test_depends_no_args(self, mock_print_error, mock_console):
        with self.assertRaises(SystemExit) as cm:
            execute_command("depends", [])
        
        self.assertEqual(cm.exception.code, 1)
        mock_print_error.assert_called_with("[bold red]E[/bold red]: No package specified")

    @patch("subprocess.run")
    def test_rdepends_with_args(self, mock_run):
        mock_run.return_value.returncode = 0
        execute_command("rdepends", ["pkgname"])
        # Should NOT exit
        mock_run.assert_called()

    @patch("subprocess.run")
    def test_depends_with_args(self, mock_run):
        mock_run.return_value.returncode = 0
        execute_command("depends", ["pkgname"])
        # Should NOT exit
        mock_run.assert_called()

if __name__ == "__main__":
    unittest.main()
