import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import aur

class TestAurDeps(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.aur.console.print')
        self.mock_console_print = self.console_patcher.start()
        
        self.input_patcher = patch('apt_pac.aur.console.input', return_value='n') 
        self.mock_console_input = self.input_patcher.start()
        
        # Mock print_transaction_summary instead of print_columnar_list
        self.print_summary_patcher = patch('apt_pac.aur.print_transaction_summary')
        self.mock_print_summary = self.print_summary_patcher.start()
        
        self.sub_patcher = patch('subprocess.run')
        self.mock_sub = self.sub_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.print_summary_patcher.stop()
        self.sub_patcher.stop()

    def test_aur_install_deps_passed_to_ui(self):
        installer = aur.AurInstaller()
        packages = ['target']
        build_queue = [
            {'Name': 'dep-aur', 'Version': '0.9'},
            {'Name': 'target', 'Version': '1.0'}
        ]
        
        with patch('apt_pac.aur.AurResolver') as mock_resolver_cls:
            mock_resolver = mock_resolver_cls.return_value
            mock_resolver.resolve.return_value = build_queue
            mock_resolver.official_deps = {'dep-official'}
            self.mock_sub.return_value = MagicMock(returncode=0, stdout="dep-official 2.0\n")

            with self.assertRaises(SystemExit):
                installer.install(packages)
            
            # Verify call to print_transaction_summary
            self.assertEqual(self.mock_print_summary.call_count, 1)
            
            # Check args
            # call_args.kwargs should contain 'new_pkgs' and 'explicit_names'
            call_kwargs = self.mock_print_summary.call_args.kwargs
            
            # explicit_names should be {'target'}
            self.assertEqual(call_kwargs['explicit_names'], {'target'})
            
            # new_pkgs should contain tuples, including deps
            # [('dep-aur', '0.9'), ('target', '1.0'), ('dep-official', '2.0')]
            # Order might vary slightly depending on how code appends, but let's check membership.
            new_pkgs = call_kwargs['new_pkgs']
            self.assertIn(('target', '1.0'), new_pkgs)
            self.assertIn(('dep-aur', '0.9'), new_pkgs)
            self.assertIn(('dep-official', '2.0'), new_pkgs)

if __name__ == '__main__':
    unittest.main()
