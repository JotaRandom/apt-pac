import unittest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from apt_pac import alpm_helper

class TestCacheCleaner(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.test_dir) / "cache"
        self.cache_dir.mkdir()
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    def create_pkg(self, name, version, arch="x86_64"):
        filename = f"{name}-{version}-{arch}.pkg.tar.zst"
        path = self.cache_dir / filename
        # Write dummy content with size = 1000 bytes
        with open(path, "wb") as f:
            f.write(b"0" * 1000)
        return path

    @patch('apt_pac.alpm_helper.get_handle')
    def test_clean_cache_keeps_recent(self, mock_get_handle):
        # Mock handle.cachedirs
        mock_handle = MagicMock()
        mock_handle.cachedirs = [str(self.cache_dir)]
        mock_get_handle.return_value = mock_handle
        
        # Create 5 versions of 'foo'
        # Versions: 1.0-1, 1.1-1, 1.2-1, 2.0-1, 2.1-1
        # Expected kept (keep=3): 2.1-1, 2.0-1, 1.2-1
        # Expected deleted: 1.1-1, 1.0-1
        
        pkgs = [
            ("foo", "1.0-1"),
            ("foo", "1.1-1"),
            ("foo", "1.2-1"),
            ("foo", "2.0-1"),
            ("foo", "2.1-1")
        ]
        
        for name, ver in pkgs:
            self.create_pkg(name, ver)
            
        # Create another package 'bar' with 2 versions (should keep all)
        self.create_pkg("bar", "1.0-1")
        self.create_pkg("bar", "2.0-1")
        
        # Run clean_cache
        freed = alpm_helper.clean_cache(keep=3, dry_run=False, verbose=False)
        
        # Verify foo files
        self.assertTrue((self.cache_dir / "foo-2.1-1-x86_64.pkg.tar.zst").exists())
        self.assertTrue((self.cache_dir / "foo-2.0-1-x86_64.pkg.tar.zst").exists())
        self.assertTrue((self.cache_dir / "foo-1.2-1-x86_64.pkg.tar.zst").exists())
        self.assertFalse((self.cache_dir / "foo-1.1-1-x86_64.pkg.tar.zst").exists())
        self.assertFalse((self.cache_dir / "foo-1.0-1-x86_64.pkg.tar.zst").exists())
        
        # Verify bar files
        self.assertTrue((self.cache_dir / "bar-2.0-1-x86_64.pkg.tar.zst").exists())
        self.assertTrue((self.cache_dir / "bar-1.0-1-x86_64.pkg.tar.zst").exists())
        
        # Verify freed bytes (2 files * 1000 bytes)
        self.assertEqual(freed, 2000)

    @patch('apt_pac.alpm_helper.get_handle')
    def test_dry_run(self, mock_get_handle):
        mock_handle = MagicMock()
        mock_handle.cachedirs = [str(self.cache_dir)]
        mock_get_handle.return_value = mock_handle
        
        self.create_pkg("test", "1.0-1")
        self.create_pkg("test", "2.0-1")
        self.create_pkg("test", "3.0-1")
        self.create_pkg("test", "4.0-1")
        
        freed = alpm_helper.clean_cache(keep=3, dry_run=True, verbose=False)
        
        # Should report freed bytes but not delete
        self.assertEqual(freed, 1000)
        self.assertTrue((self.cache_dir / "test-1.0-1-x86_64.pkg.tar.zst").exists())

if __name__ == '__main__':
    unittest.main()
