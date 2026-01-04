import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import aur

class TestCycleDetection(unittest.TestCase):
    def setUp(self):
        self.run_patcher = patch('subprocess.run')
        self.mock_run = self.run_patcher.start()
        self.mock_run.return_value = MagicMock(returncode=127)  # Not installed
        
    def tearDown(self):
        self.run_patcher.stop()

    def test_simple_cycle(self):
        """Test detection of simple cycle: A → B → A"""
        
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'pkg-a':
                    results.append({'Name': 'pkg-a', 'Version': '1.0', 'Depends': ['pkg-b']})
                elif p == 'pkg-b':
                    results.append({'Name': 'pkg-b', 'Version': '1.0', 'Depends': ['pkg-a']})
            return results
        
        with patch('apt_pac.aur.get_aur_info', side_effect=side_effect_rpc):
            with patch('apt_pac.aur.is_in_official_repos', return_value=False):
                resolver = aur.AurResolver()
                
                with self.assertRaises(aur.CyclicDependencyError) as ctx:
                    resolver.resolve(['pkg-a'])
                
                # Check that cycle is in error message
                self.assertIn('pkg-a', str(ctx.exception))
                self.assertIn('pkg-b', str(ctx.exception))
                print(f"✓ Detected cycle: {ctx.exception}")

    def test_complex_cycle(self):
        """Test detection of complex cycle: A → B → C → A"""
        
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'pkg-a':
                    results.append({'Name': 'pkg-a', 'Version': '1.0', 'Depends': ['pkg-b']})
                elif p == 'pkg-b':
                    results.append({'Name': 'pkg-b', 'Version': '1.0', 'Depends': ['pkg-c']})
                elif p == 'pkg-c':
                    results.append({'Name': 'pkg-c', 'Version': '1.0', 'Depends': ['pkg-a']})
            return results
        
        with patch('apt_pac.aur.get_aur_info', side_effect=side_effect_rpc):
            with patch('apt_pac.aur.is_in_official_repos', return_value=False):
                resolver = aur.AurResolver()
                
                with self.assertRaises(aur.CyclicDependencyError) as ctx:
                    resolver.resolve(['pkg-a'])
                
                print(f"✓ Detected complex cycle: {ctx.exception}")

    def test_no_false_positive_diamond(self):
        """Test that diamond dependencies don't trigger false positive: A → B, A → C, B → D, C → D"""
        
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'pkg-a':
                    results.append({'Name': 'pkg-a', 'Version': '1.0', 'Depends': ['pkg-b', 'pkg-c']})
                elif p == 'pkg-b':
                    results.append({'Name': 'pkg-b', 'Version': '1.0', 'Depends': ['pkg-d']})
                elif p == 'pkg-c':
                    results.append({'Name': 'pkg-c', 'Version': '1.0', 'Depends': ['pkg-d']})
                elif p == 'pkg-d':
                    results.append({'Name': 'pkg-d', 'Version': '1.0', 'Depends': []})
            return results
        
        with patch('apt_pac.aur.get_aur_info', side_effect=side_effect_rpc):
            with patch('apt_pac.aur.is_in_official_repos', return_value=False):
                resolver = aur.AurResolver()
                
                # Should NOT raise CyclicDependencyError
                try:
                    queue = resolver.resolve(['pkg-a'])
                    self.assertGreater(len(queue), 0)
                    print("✓ Diamond dependency handled correctly (no false positive)")
                except aur.CyclicDependencyError:
                    self.fail("Diamond dependency incorrectly detected as cycle")


class TestSplitPackages(unittest.TestCase):
    def setUp(self):
        self.run_patcher = patch('subprocess.run')
        self.mock_run = self.run_patcher.start()
        self.mock_run.return_value = MagicMock(returncode=127)
        
    def tearDown(self):
        self.run_patcher.stop()

    def test_split_package_single_base(self):
        """Test that split packages (linux, linux-headers) share same PackageBase"""
        
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'linux':
                    results.append({
                        'Name': 'linux',
                        'Version': '6.0',
                        'PackageBase': 'linux',
                        'Depends': []
                    })
                elif p == 'linux-headers':
                    results.append({
                        'Name': 'linux-headers',
                        'Version': '6.0',
                        'PackageBase': 'linux',  # Same base!
                        'Depends': []
                    })
            return results
        
        with patch('apt_pac.aur.get_aur_info', side_effect=side_effect_rpc):
            with patch('apt_pac.aur.is_in_official_repos', return_value=False):
                resolver = aur.AurResolver()
                
                queue = resolver.resolve(['linux', 'linux-headers'])
                
                # Should only have ONE item in queue (the base)
                self.assertEqual(len(queue), 1, "Split packages should result in single build")
                
                # Check that both packages are tracked
                self.assertIn('linux', resolver.package_bases)
                self.assertEqual(resolver.package_bases['linux'], {'linux', 'linux-headers'})
                
                print(f"✓ Split package tracked: {resolver.package_bases['linux']}")

    def test_split_package_dependency(self):
        """Test package depending on part of a split package"""
        
        def side_effect_rpc(pkgs):
            results = []
            for p in pkgs:
                if p == 'my-app':
                    results.append({
                        'Name': 'my-app',
                        'Version': '1.0',
                        'Depends': ['linux-headers']
                    })
                elif p == 'linux-headers':
                    results.append({
                        'Name': 'linux-headers',
                        'Version': '6.0',
                        'PackageBase': 'linux',
                        'Depends': []
                    })
            return results
        
        with patch('apt_pac.aur.get_aur_info', side_effect=side_effect_rpc):
            with patch('apt_pac.aur.is_in_official_repos', return_value=False):
                resolver = aur.AurResolver()
                
                queue = resolver.resolve(['my-app'])
                
                # Queue should have: linux (base), my-app
                self.assertEqual(len(queue), 2)
                
                # Verify 'linux' base is tracked with linux-headers
                self.assertIn('linux', resolver.package_bases)
                self.assertIn('linux-headers', resolver.package_bases['linux'])
                
                print("✓ Split package dependency resolved correctly")


if __name__ == '__main__':
    unittest.main()
