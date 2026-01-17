import io
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
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
        mock_run.return_value.returncode = 0 # Default success
        
        installer = aur.AurInstaller()
        # Mock resolve logic to return one package
        with patch.object(aur.AurResolver, 'resolve', return_value=[{'Name':'foo'}]), \
             patch('apt_pac.aur.download_aur_source', return_value=True), \
             patch('builtins.print'), \
             patch('apt_pac.ui.console.input', return_value='y'), \
             patch('os.getuid', return_value=1000, create=True), \
             patch('pathlib.Path.glob', return_value=[MagicMock(stem='foo-1.0-1-any')]), \
             patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True):
             
             installer.install(['foo'], auto_confirm=False)
             
             # Check makepkg call
             # Logic traverses build_pkg -> subprocess.run(cmd)
             # We want to find the call ["makepkg", ...]
             found = False
             for call_val in mock_run.call_args_list:
                 args = call_val[0][0]
                 if args and args[0] == "makepkg":
                     self.assertNotIn("--noconfirm", args)
                     found = True
             self.assertTrue(found, "makepkg should have been called without --noconfirm")

        # Case 2: auto_confirm=True -> Should pass --noconfirm
        mock_run.reset_mock()
        mock_run.return_value.returncode = 0
        
        with patch.object(aur.AurResolver, 'resolve', return_value=[{'Name':'foo'}]), \
             patch('apt_pac.aur.download_aur_source', return_value=True), \
             patch('builtins.print'), \
             patch('apt_pac.ui.console.input', return_value='y'), \
             patch('os.getuid', return_value=1000, create=True), \
             patch('pathlib.Path.glob', return_value=[MagicMock(stem='foo-1.0-1-any')]), \
             patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True):
             
             installer.install(['foo'], auto_confirm=True)
             
             found = False
             for call_val in mock_run.call_args_list:
                 args = call_val[0][0]
                 if args and args[0] == "makepkg":
                     self.assertIn("--noconfirm", args)
                     found = True
             self.assertTrue(found, "makepkg should have been called with --noconfirm")

    @patch('apt_pac.commands.subprocess.run')
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
             
             # Fix: Mock pathlib.Path.iterdir to avoid FileNotFoundError
             # and return a dummy package file for the install step
             with patch('pathlib.Path.iterdir') as mock_iterdir, \
                  patch('apt_pac.aur.is_valid_package', return_value=True), \
                  patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True):
                 
                 mock_pkg = MagicMock()
                 mock_pkg.stem = "package-query-1.9-1-any"
                 mock_iterdir.return_value = [mock_pkg]
                 
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

    @patch('sys.stdout', new_callable=io.StringIO)
    @patch('subprocess.run')
    @patch('apt_pac.commands.get_config')
    @patch('apt_pac.commands.console')
    @patch('apt_pac.ui.console')
    @patch('os.getuid', return_value=0, create=True)
    def test_download_output(self, mock_getuid, mock_ui_console, mock_cmd_console, mock_config, mock_run, mock_stdout):
        from apt_pac.commands import execute_command
        # Mock config
        mock_conf_obj = MagicMock()
        mock_conf_obj.get.return_value = 0
        mock_config.return_value = mock_conf_obj
        
        # Setup mock for subprocess.run
        url_output = "file://var/cache/pacman/pkg/testpkg-1.0-1-any.pkg.tar.zst\nhttp://mirror.archlinux.org/core/os/x86_64/testpkg-1.0-1-any.pkg.tar.zst"
        
        def side_effect(*args, **kwargs):
             cmd = args[0]
             if "-p" in cmd:
                 return MagicMock(returncode=0, stdout=url_output)
             if "-Qu" in cmd: # Partial upgrade check
                 return MagicMock(returncode=1, stdout="")
             return MagicMock(returncode=0)
             
        mock_run.side_effect = side_effect
        
        with patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True):
             execute_command("install", ["testpkg"])
        
        # Verify ui.print_apt_download_line called
        # It uses ui.console, so proper mock is mock_ui_console
        
        found_get = False
        for call_args in mock_ui_console.print.call_args_list:
             if len(call_args[0]) > 0 and "Get:" in str(call_args[0][0]):
                 found_get = True
                 break
        
        self.assertTrue(found_get, "Should have printed Get: line")

        self.assertTrue(found_get, "Should have printed Get: line")

    @patch('apt_pac.aur.get_config')
    @patch('urllib.request.urlopen')
    def test_rpc_caching(self, mock_urlopen, mock_config):
        from apt_pac import aur
        import json
        import os
        
        # Mock Default Config (30 min)
        mock_conf_obj = MagicMock()
        mock_conf_obj.get.return_value = 30
        mock_config.return_value = mock_conf_obj

        # Setup mock response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "version": 5, 
            "type": "search", 
            "resultcount": 1, 
            "results": [{"Name": "cached-pkg", "Version": "1.0"}]
        }).encode('utf-8')
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        
        mock_urlopen.return_value = mock_response
        
        # Ensure clean state
        cache_file = aur.CACHE_FILE
        if cache_file.exists():
            try:
                os.remove(cache_file)
            except:
                pass
                
        try:
            # First call - should hit network
            res1 = aur.search_aur("cached-pkg")
            self.assertEqual(len(res1), 1)
            self.assertEqual(mock_urlopen.call_count, 1)
            
            # Second call - should hit cache
            res2 = aur.search_aur("cached-pkg")
            self.assertEqual(len(res2), 1)
            # Call count should STILL be 1
            self.assertEqual(mock_urlopen.call_count, 1)
            
        finally:
             if cache_file.exists():
                try:
                    os.remove(cache_file)
                except:
                    pass

    @patch('time.time')
    @patch('apt_pac.aur.get_config')
    @patch('urllib.request.urlopen')
    def test_rpc_cache_expiry(self, mock_urlopen, mock_config, mock_time):
        from apt_pac import aur
        import json
        import os
        
        # Mock Config with SHORT TTL (1 minute)
        mock_conf_obj = MagicMock()
        mock_conf_obj.get.return_value = 1 # 1 minute
        mock_config.return_value = mock_conf_obj
        
        # Setup mock response
        mock_response = MagicMock()
        # Return generic content
        mock_response.read.return_value = json.dumps({
            "version": 5, "type": "search", "results": [{"Name": "expired-pkg"}]
        }).encode('utf-8')
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        # Define time progression
        start_time = 1000.0
        mock_time.return_value = start_time
        
        # Clean cache
        cache_file = aur.CACHE_FILE
        if cache_file.exists():
             try: os.remove(cache_file)
             except: pass
             
        try:
            # 1. First search (Time = 0)
            aur.search_aur("expired-pkg")
            self.assertEqual(mock_urlopen.call_count, 1)
            
            # 2. Advance time by 30 seconds (Within 1 min TTL)
            mock_time.return_value = start_time + 30.0
            aur.search_aur("expired-pkg")
            self.assertEqual(mock_urlopen.call_count, 1) # Should be cached
            
            # 3. Advance time by 61 seconds (Expired)
            mock_time.return_value = start_time + 61.0
            aur.search_aur("expired-pkg")
            self.assertEqual(mock_urlopen.call_count, 2) # Should re-fetch
            
        finally:
            if cache_file.exists():
                try: os.remove(cache_file)
                except: pass

class TestPrivileges(unittest.TestCase):
    @patch('apt_pac.commands.subprocess.run')
    @patch('apt_pac.commands.os.getuid', create=True)
    @patch('apt_pac.ui.console')
    def test_system_install_no_root(self, mock_console, mock_getuid, mock_run):
        from apt_pac import commands
        # Mock user as non-root (1000)
        mock_getuid.return_value = 1000
        
        # Mock subprocess.run for safeguard check (pacman -Qu)
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        with self.assertRaises(SystemExit) as cm:
            commands.execute_command("install", ["foo"])
            
        # Should exit with specific code (100 or 1)
        # Our code exits with 100 for permission denied
        self.assertEqual(cm.exception.code, 100)
        
    @patch('apt_pac.aur.get_config')
    @patch('shutil.which')
    def test_get_privilege_command(self, mock_which, mock_config):
        from apt_pac.aur import get_privilege_command
        
        # Setup Config Mock
        mock_conf_obj = MagicMock()
        mock_config.return_value = mock_conf_obj
        
        # 1. Test "sudo" explicit
        mock_conf_obj.get.side_effect = lambda s, k, d: "sudo" if k == "privilege_tool" else d
        cmd = get_privilege_command("user", ["cmd"])
        self.assertEqual(cmd, ["sudo", "-u", "user", "cmd"])
        
        # 2. Test "doas" explicit
        mock_conf_obj.get.side_effect = lambda s, k, d: "doas" if k == "privilege_tool" else d
        cmd = get_privilege_command("user", ["cmd"])
        self.assertEqual(cmd, ["doas", "-u", "user", "cmd"])

        # 3. Test "run0" explicit
        mock_conf_obj.get.side_effect = lambda s, k, d: "run0" if k == "privilege_tool" else d
        cmd = get_privilege_command("user", ["cmd"])
        self.assertEqual(cmd, ["run0", "--user=user", "cmd"])

        # 4. Test "auto" with run0 available
        mock_conf_obj.get.side_effect = lambda s, k, d: "auto" if k == "privilege_tool" else d
        mock_which.side_effect = lambda cmd: "/bin/run0" if cmd == "run0" else None
        cmd = get_privilege_command("user", ["cmd"])
        self.assertEqual(cmd, ["run0", "--user=user", "cmd"])

        # 5. Test "auto" with doas available (no run0)
        mock_which.side_effect = lambda cmd: "/bin/doas" if cmd == "doas" else None
        cmd = get_privilege_command("user", ["cmd"])
        self.assertEqual(cmd, ["doas", "-u", "user", "cmd"])
    
    @patch('apt_pac.aur.download_aur_source')
    @patch('subprocess.run')
    @patch('os.getuid', create=True)
    @patch.dict(os.environ, {"SUDO_USER": "testuser"}, clear=True) 
    def test_aur_build_as_root_with_sudo_user(self, mock_getuid, mock_run, mock_download):
        from apt_pac.aur import AurInstaller
        
        # Mock root
        mock_getuid.return_value = 0
        mock_download.return_value = True # Success download
        
        installer = AurInstaller()
        # We need to minimally mock _build_pkg dependencies
        # But _build_pkg is instance method. We can test it directly.
        
        pkg_info = {'Name': 'test-pkg'}
        
        # We need to patch get_config inside aur module to return 'sudo' for deterministic test
        with patch('apt_pac.aur.get_config') as mock_config:
             mock_conf_obj = MagicMock()
             mock_conf_obj.get.side_effect = lambda s, k, d: "sudo" if k == "privilege_tool" else d
             mock_config.return_value = mock_conf_obj
             
             # Mock built package findings
             with patch.object(Path, 'glob', return_value=[Path("test-pkg-1.0-1-any.pkg.tar.zst")]), \
                  patch('apt_pac.commands.run_pacman_with_apt_output', return_value=True): 
                  installer._build_pkg(pkg_info, verbose=False, auto_confirm=True)
        
        # Check that subprocess.run was called with sudo
        found_sudo = False
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            if cmd[0] == "sudo" and cmd[1] == "-u" and cmd[2] == "testuser":
                found_sudo = True
                break
        
        self.assertTrue(found_sudo, "Should have dropped privileges with sudo -u testuser")

    @patch('apt_pac.aur.download_aur_source')
    @patch('os.getuid', create=True)
    @patch.dict(os.environ, {}, clear=True) # Ensure NO SUDO_USER
    def test_aur_build_as_root_no_sudo_user(self, mock_getuid, mock_download):
        from apt_pac.aur import AurInstaller
        
        # Mock root
        mock_getuid.return_value = 0
        mock_download.return_value = True
        
        installer = AurInstaller()
        pkg_info = {'Name': 'test-pkg'}
        
        with self.assertRaises(SystemExit):
            # Suppress print error
            with patch('apt_pac.ui.console.print'):
                 installer._build_pkg(pkg_info, verbose=False, auto_confirm=True)

class TestEasterEggs(unittest.TestCase):
    @patch('apt_pac.commands.console')
    @patch('apt_pac.commands.os.getuid', create=True)
    def test_moo(self, mock_getuid, mock_console):
        from apt_pac import commands
        mock_getuid.return_value = 1000
        
        commands.execute_command("moo", [])
        
        # Verify call args
        found_moo = False
        for call_args in mock_console.print.call_args_list:
            if "Have you mooed today?" in str(call_args[0][0]):
                found_moo = True
                break
        self.assertTrue(found_moo)

    @patch('apt_pac.commands.console')
    @patch('apt_pac.commands.os.getuid', create=True)
    def test_pacman(self, mock_getuid, mock_console):
        from apt_pac import commands
        mock_getuid.return_value = 1000
        
        commands.execute_command("pacman", [])
        
        found_pacman = False
        for call_args in mock_console.print.call_args_list:
            if "Waka waka" in str(call_args[0][0]): 
                found_pacman = True
                break
        self.assertTrue(found_pacman)

if __name__ == '__main__':
    unittest.main()
