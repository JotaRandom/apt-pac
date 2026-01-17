
import unittest
from unittest.mock import patch, MagicMock
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

    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.alpm_helper.get_local_package")
    def test_rdepends_with_args(self, mock_get_local, mock_console):
        # Mock a package with rdepends
        mock_pkg = MagicMock()
        mock_pkg.name = 'pkgname'
        mock_pkg.compute_requiredby.return_value = ['dep1', 'dep2']
        mock_get_local.return_value = mock_pkg
        
        execute_command("rdepends", ["pkgname"])
        # Should print package name and deps
        self.assertTrue(mock_console.print.called)

    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.alpm_helper.get_local_package")
    @patch("apt_pac.commands.alpm_helper.get_package")
    def test_depends_with_args(self, mock_get_pkg, mock_get_local, mock_console):
        # Mock a package with depends
        mock_pkg = type('obj', (object,), {
            'name': 'pkgname',
            'depends': ['bash', 'coreutils']
        })()
        mock_get_local.return_value = mock_pkg
        
        execute_command("depends", ["pkgname"])
        # Should print package name and deps
        self.assertTrue(mock_console.print.called)

if __name__ == "__main__":
    unittest.main()
