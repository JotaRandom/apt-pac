import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import aur

class TestAurInstall(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.aur.console.print')
        self.mock_console_print = self.console_patcher.start()
        
        self.input_patcher = patch('apt_pac.aur.console.input', return_value='n') 
        self.mock_console_input = self.input_patcher.start()
        
        self.print_col_patcher = patch('apt_pac.aur.print_columnar_list')
        self.mock_print_col = self.print_col_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.print_col_patcher.stop()

    def test_aur_install_summary(self):
        installer = aur.AurInstaller()
        
        # Mock resolver to return dummy packages
        pkg_list = [
            {'Name': 'aur-pkg', 'Version': '1.2-3'},
            {'Name': 'dep-pkg', 'Version': '0.9'}
        ]
        
        with patch('apt_pac.aur.AurResolver') as mock_resolver_cls:
            mock_resolver = mock_resolver_cls.return_value
            mock_resolver.resolve.return_value = pkg_list
            
            with self.assertRaises(SystemExit):
                installer.install(['aur-pkg'])
            
            # Check if print_columnar_list called with GREEN BOLD versions
            # Expected list sorted: "aur-pkg [bold]1.2-3[/bold]", "dep-pkg [bold]0.9[/bold]"
            expected = ['aur-pkg [bold]1.2-3[/bold]', 'dep-pkg [bold]0.9[/bold]']
            self.mock_print_col.assert_called_with(expected, 'green')

if __name__ == '__main__':
    unittest.main()
