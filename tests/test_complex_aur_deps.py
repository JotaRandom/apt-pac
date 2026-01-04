import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import commands, aur, ui

class TestComplexAurDeps(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch('apt_pac.ui.console.print')
        self.mock_console = self.console_patcher.start()
        
        self.input_patcher = patch('apt_pac.ui.console.input', return_value='y') 
        self.mock_input = self.input_patcher.start()
        
        self.run_patcher = patch('subprocess.run')
        self.mock_run = self.run_patcher.start()
        
        self.rpc_patcher = patch('apt_pac.aur.get_aur_info')
        self.mock_rpc = self.rpc_patcher.start()
        
        self.config_patcher = patch('apt_pac.aur.get_config')
        self.mock_get_config = self.config_patcher.start()
        self.mock_config_instance = MagicMock()
        from pathlib import Path
        self.mock_config_instance.cache_dir = Path("/tmp/mock_cache")
        self.mock_get_config.return_value = self.mock_config_instance
        
        self.mock_config_instance.cache_dir = Path("/tmp/mock_cache")
        self.mock_get_config.return_value = self.mock_config_instance
        
        self.summary_patcher = patch('apt_pac.aur.print_transaction_summary')
        self.mock_summary = self.summary_patcher.start()
        
        # Mock os.getuid
        self.getuid_patcher = patch('os.getuid', return_value=1000, create=True)
        self.mock_getuid = self.getuid_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.run_patcher.stop()
        self.rpc_patcher.stop()
        self.config_patcher.stop()
        self.summary_patcher.stop()
        self.getuid_patcher.stop()

    def test_install_mixed_deps(self):
        # Simulate:
        # User installs 'target-pkg' (AUR)
        # target-pkg depends on: 'aur-lib' (AUR) and 'official-lib' (Official)
        # aur-lib depends on: 'base-devel' (Official)
        
        # Mocks for RPC info
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'target-pkg':
                    results.append({
                        'Name': 'target-pkg', 
                        'Version': '1.0-1',
                        'Depends': ['aur-lib', 'official-lib']
                    })
                elif p == 'aur-lib':
                    results.append({
                        'Name': 'aur-lib', 
                        'Version': '0.5-1',
                        'Depends': ['base-devel']
                    })
            return results
            
        self.mock_rpc.side_effect = side_effect_rpc
        
        # Mock pacman to resolve official versions
        def side_effect_run(cmd, **kwargs):
            # Check if official (pacman -Sp)
            if '-Sp' in cmd:
                # Last arg is usually package name
                # cmd = ["pacman", "-Sp", "--noconfirm", package]
                pkg = cmd[-1]
                if pkg in ['target-pkg', 'aur-lib']:
                    return MagicMock(returncode=1) # Not official
                return MagicMock(returncode=0) # Official (official-lib, base-devel)

            # args: pacman -S --print --print-format %n %v official-lib base-devel
            # Note: order depends on sets, might vary.
            if 'pacman' in cmd and '--print' in cmd:
                # Return versions
                mock_out = "official-lib 2.0-1\nbase-devel 9.0-1\n"
                return MagicMock(returncode=0, stdout=mock_out)
            
            # Pacman check for installed (Simulate none installed)
            # cmd is ["pacman", "-Qq", package]
            if any(x in cmd for x in ['-Q', '-Qq']):
                return MagicMock(returncode=127) # Not found
                
            return MagicMock(returncode=0)
            
        self.mock_run.side_effect = side_effect_run

        # Execute
        installer = aur.AurInstaller()
        try:
             installer.install(['target-pkg'])
        except Exception as e:
             print(f"DEBUG: Exception during install: {e}")
             import traceback
             traceback.print_exc()
             pass # Installer exits or fails on build, but we verify summary first.
             
        # VERIFICATION
        self.mock_summary.assert_called_once()
        kwargs = self.mock_summary.call_args.kwargs
        
        new_pkgs = kwargs.get('new_pkgs', [])
        explicit_names = kwargs.get('explicit_names', set())
        
        # 1. Verify Explicit
        self.assertEqual(explicit_names, {'target-pkg'})
        
        # 2. Verify Contents
        # Should contain: target-pkg, aur-lib, official-lib, base-devel
        # Check by name
        # Check by name
        names = [p[0] for p in new_pkgs]
        self.assertIn('target-pkg', names)
        self.assertIn('aur-lib', names)
        self.assertIn('official-lib', names)
        self.assertIn('base-devel', names)
        
        # 3. Verify Verions
        new_pkg_dict = dict(new_pkgs)
        self.assertEqual(new_pkg_dict['official-lib'], '2.0-1')
        self.assertEqual(new_pkg_dict['base-devel'], '9.0-1')
        self.assertEqual(new_pkg_dict['target-pkg'], '1.0-1')
        self.assertEqual(new_pkg_dict['aur-lib'], '0.5-1')

if __name__ == '__main__':
    unittest.main()
