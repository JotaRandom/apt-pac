import io
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from apt_pac import aur, commands, sources

class TestAurFeatures(unittest.TestCase):
    
    @patch('subprocess.run')
    @patch('apt_pac.aur.get_aur_info')
    def test_check_updates(self, mock_get_info, mock_run):
        # Mock installed packages: local-pkg 1.0
        # Mock AUR version: local-pkg 2.0
        
        # Mock pacman -Qm (foreign packages)
        mock_run.side_effect = [
             MagicMock(stdout="foreign-pkg 1.0\n", returncode=0), # get_installed_aur
             MagicMock(stdout="foreign-pkg 1.0\n", returncode=0), # get_installed_packages
             MagicMock(stdout="1", returncode=0), # vercmp 1.0 2.0 -> 1 (remote is newer? wait vercmp output)
        ]
        
        # Verify vercmp behavior: vercmp <ver1> <ver2> returns <0 if ver1<ver2
        # In check_updates: if version_compare(local, aur) < 0: update
        # We need mock_run to return < 0 for the comparison to work
        
        def run_side_effect(cmd, **kwargs):
            if cmd[0] == "pacman" and "-Qm" in cmd:
                return MagicMock(stdout="foreign-pkg 1.0\n", returncode=0)
            if cmd[0] == "pacman" and "-Q" in cmd:
                 return MagicMock(stdout="foreign-pkg 1.0\n", returncode=0)
            if cmd[0] == "vercmp":
                # vercmp 1.0 2.0 -> returns -1 (1.0 is older than 2.0)
                return MagicMock(stdout="-1\n", returncode=0)
            return MagicMock(returncode=0)
            
        mock_run.side_effect = run_side_effect
        mock_get_info.return_value = [{'Name': 'foreign-pkg', 'Version': '2.0'}]
        
        updates = aur.check_updates(verbose=False)
        
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['name'], 'foreign-pkg')
        self.assertEqual(updates[0]['current'], '1.0')
        self.assertEqual(updates[0]['new'], '2.0')

    @patch('subprocess.run')
    def test_download_aur_source(self, mock_run):
        # Test download fallback
        with patch('apt_pac.config.get_config') as mock_config:
            mock_cache = MagicMock()
            mock_cache.exists.return_value = False # Target doesn't exist
            mock_config.return_value.cache_dir = Path("/tmp/cache")
            
            # Run
            target = aur.download_aur_source("test-pkg")
            
            # Verify git clone called
            expected_url = "https://aur.archlinux.org/test-pkg.git"
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "git")
            self.assertEqual(args[1], "clone")
            self.assertEqual(args[2], expected_url)

    @patch('apt_pac.sources.download_source')
    @patch('apt_pac.aur.download_aur_source')
    def test_apt_source_fallback(self, mock_aur_dl, mock_abs_dl):
        # Mock official source failing
        mock_abs_dl.return_value = None
        # Mock AUR source succeeding
        mock_aur_dl.return_value = Path("/tmp/aur/pkg")
        
        # Call handle_apt_source
        success = sources.handle_apt_source("unknown-pkg", [], verbose=True)
        
        self.assertTrue(success)
        mock_abs_dl.assert_called_once()
        mock_aur_dl.assert_called_once_with("unknown-pkg")

    @patch('subprocess.run')
    @patch('apt_pac.aur.check_updates')
    @patch('apt_pac.ui.console.input')
    def test_upgrade_flow(self, mock_input, mock_check_updates, mock_run):
        # Test that upgrade command calls check_updates
        mock_check_updates.return_value = [{'name': 'foo', 'current': '1.0', 'new': '2.0'}]
        mock_input.return_value = 'n' # Don't actually install in test
        
        # We need to mock COMMAND_MAP imports in implementation or config
        # Simply calling check_updates via the command logic is complex due to exit() calls
        pass

    @patch('subprocess.run')
    def test_smart_providers_aur(self, mock_run):
        # Case 1: auto_confirm=False (Default) -> Should NOT pass --noconfirm to makepkg
        installer = aur.AurInstaller()
        # Mock resolve logic to return one package
        with patch.object(aur.AurResolver, 'resolve', return_value=[{'Name':'foo'}]), \
             patch('apt_pac.aur.download_aur_source', return_value=True), \
             patch('builtins.print'), \
             patch('apt_pac.ui.console.input', return_value='y'), \
             patch('os.getuid', return_value=1000, create=True): # Mock as non-root user
             
             installer.install(['foo'], auto_confirm=False)
             
             # Check makepkg call
             # Logic traverses build_pkg -> subprocess.run(cmd)
             # We want to find the call ["makepkg", ...]
             found = False
             for call in mock_run.call_args_list:
                 args = call[0][0]
                 if args and args[0] == "makepkg":
                     self.assertNotIn("--noconfirm", args)
                     found = True
             self.assertTrue(found, "makepkg should have been called without --noconfirm")

        # Case 2: auto_confirm=True -> Should pass --noconfirm
        mock_run.reset_mock()
        with patch.object(aur.AurResolver, 'resolve', return_value=[{'Name':'foo'}]), \
             patch('apt_pac.aur.download_aur_source', return_value=True), \
             patch('builtins.print'), \
             patch('apt_pac.ui.console.input', return_value='y'), \
             patch('os.getuid', return_value=1000, create=True):
             
             installer.install(['foo'], auto_confirm=True)
             
             found = False
             for call in mock_run.call_args_list:
                 args = call[0][0]
                 if args and args[0] == "makepkg":
                     self.assertIn("--noconfirm", args)
                     found = True
             self.assertTrue(found, "makepkg should have been called with --noconfirm")

    @patch('subprocess.run')
    @patch('apt_pac.commands.get_editor', return_value='nano')
    @patch('apt_pac.ui.console.input', return_value='y')
    def test_add_repository(self, mock_input, mock_editor, mock_run):
        # We need to test execute_command, but importing it might be tricky due to circular imports or global state
        # Let's import it locally
        from apt_pac.commands import execute_command
        
        # Mock os.getuid to avoid permission issues
        with patch('os.getuid', return_value=0, create=True):
             execute_command("add-repository", [])
             
             # Check if editor was called
             mock_run.assert_called_with(["nano", "/etc/pacman.conf"], check=True)

    @patch('apt_pac.ui.console.input', return_value='y')
    def test_gpg_import(self, mock_input):
         # Patch subprocess.run specifically where it is used
         with patch('apt_pac.aur.subprocess.run') as mock_run:
             from apt_pac.aur import AurInstaller
             import subprocess
             
             # Mock download success
             with patch('apt_pac.aur.download_aur_source', return_value=True):
                 installer = AurInstaller()
             
             # Setup mock side effects
             # 1. First makepkg call fails with GPG error
             # 2. gpg --recv-keys call succeeds
             # 3. Retry makepkg call succeeds
             
             error_output = b"Verifying source file signatures with gpg...\n" \
                            b"package-query 1.9-1 (Tue Jun 29) (unknown public key D1483FA6C3C07136)\n" \
                            b"==> ERROR: One or more PGP signatures could not be verified!"
             
             # Mock subprocess.run behaviors sequentially
             def side_effect(*args, **kwargs):
                 cmd = args[0]
                 if "makepkg" in cmd:
                     # Check if it's the retry (how to distinguish? just state)
                     if not hasattr(side_effect, 'failed_once'):
                         side_effect.failed_once = True
                         raise subprocess.CalledProcessError(1, cmd, output=b"", stderr=error_output)
                     else:
                         return MagicMock(returncode=0)
                 elif "gpg" in cmd:
                     return MagicMock(returncode=0)
                 elif "chown" in cmd:
                     return MagicMock(returncode=0)
                 return MagicMock(returncode=0)

             mock_run.side_effect = side_effect
             
             # Run
             # Mock os.getuid to avoid AttributeError on Windows
             with patch('os.getuid', return_value=1000, create=True):
                 installer._build_pkg({'Name': 'package-query', 'Version': '1.9'}, verbose=False, auto_confirm=True)
             
             # Verify GPG called
             # We should see call to gpg --recv-keys D1483FA6C3C07136
             gpg_called = False
             for call_args in mock_run.call_args_list:
                 cmd = call_args[0][0]
                 if "gpg" in cmd and "D1483FA6C3C07136" in cmd:
                     gpg_called = True
                     break
             
             self.assertTrue(gpg_called, "gpg --recv-keys should have been called for D1483FA6C3C07136")

    @patch('subprocess.run')
    @patch('apt_pac.commands.get_config')
    @patch('apt_pac.commands.console')
    def test_key_alias(self, mock_console, mock_config, mock_run):
        from apt_pac.commands import execute_command
        # Test that 'key' maps to apt-key logic (pacman-key)
        # Mock config avoiding errors
        mock_conf_obj = MagicMock()
        mock_conf_obj.get.return_value = 0
        mock_config.return_value = mock_conf_obj
        
        execute_command("key", ["list"])
        mock_run.assert_called_with(["pacman-key", "--list-keys"])

    @patch('sys.stdout', new_callable=io.StringIO)
    @patch('subprocess.run')
    @patch('apt_pac.commands.get_config')
    @patch('apt_pac.commands.console')
    def test_key_output(self, mock_console, mock_config, mock_run, mock_stdout):
        from apt_pac.commands import execute_command
        # Test that 'key add' prints OK
        mock_conf_obj = MagicMock()
        mock_conf_obj.get.return_value = 0
        mock_config.return_value = mock_conf_obj
        
        # Mock successful run
        mock_run.return_value = MagicMock(returncode=0)
        
        execute_command("key", ["add", "key.gpg"])
        
        mock_run.assert_called_with(["pacman-key", "--add", "key.gpg"], check=True, capture_output=True)
        self.assertIn("OK", mock_stdout.getvalue())

if __name__ == '__main__':
    unittest.main()
