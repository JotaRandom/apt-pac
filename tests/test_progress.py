import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import commands
from rich.console import Console


class TestProgressBar(unittest.TestCase):
    def setUp(self):
        # Capture console output to verify rendering if needed
        self.console = Console(file=io.StringIO(), force_terminal=True, width=100)
        # Patch the global console in commands to use our captured console
        self.console_patcher = patch("apt_pac.commands.console", self.console)
        self.console_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_run_pacman_progress_bar_candy(self, mock_popen, mock_run):
        # Simulate pacman output with multiple downloads
        simulated_stdout = [
            "( 1/2) downloading package1-1.0-1-x86_64.pkg.tar.zst...",
            "( 2/2) downloading package2-2.0-1-x86_64.pkg.tar.zst...",
            "checking keyring...",
            "checking package integrity...",
            "loading package files...",
            "checking for file conflicts...",
            "( 1/2) checking available disk space...",
            "( 1/2) installing package1...",
            "( 2/2) installing package2...",
        ]

        # Setup mock process for Popen (the main pacman command)
        process = MagicMock()
        process.stdout.readline.side_effect = simulated_stdout + [""]
        process.poll.return_value = 0
        process.returncode = 0
        mock_popen.return_value = process

        # Setup mock run for sync call (just ensure it succeeds)
        mock_run.return_value.returncode = 0

        # Mock Progress to verify tasks are added/updated
        with patch("apt_pac.commands.Progress") as MockProgress:
            mock_progress_instance = MockProgress.return_value
            mock_progress_instance.__enter__.return_value = mock_progress_instance
            mock_progress_instance.add_task.return_value = 1  # Task ID

            # Call the function
            success = commands.run_pacman_with_apt_output(
                ["pacman", "-S", "foo"], total_pkgs=2
            )

            self.assertTrue(success)

            # Verify Progress initialized with correct columns
            # TextColumn(desc), TotalCountColumn, CandyBarColumn, TextColumn(pct)
            args, kwargs = MockProgress.call_args
            self.assertTrue(len(args) >= 4)

            # Verify add_task called with total=2
            mock_progress_instance.add_task.assert_called_with(
                description="Processing", total=2
            )

            # Verify updates happened
            calls = mock_progress_instance.update.call_args_list

            # Should see "Downloading package1"
            desc_updates = [c for c in calls if "description" in c.kwargs]
            has_download = any(
                "Downloading package1" in c.kwargs["description"] for c in desc_updates
            )
            self.assertTrue(
                has_download, "Did not find update for Downloading package1"
            )

            # Should see "Installing package1"
            has_install = any(
                "Installing package1" in c.kwargs["description"] for c in desc_updates
            )
            self.assertTrue(has_install, "Did not find update for Installing package1")

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_run_pacman_progress_bar_ansi(self, mock_popen, mock_run):
        """Test parsing of ANSI-colored output."""
        # Simulate colored output
        # "\x1b[1mcore\x1b[0m downloading..."
        # "\x1b[1mmultilib.db\x1b[0m downloading..."
        simulated_stdout = [
            ":: Syncing databases...",
            "\x1b[1mcore\x1b[0m downloading...",
            "\x1b[1mmultilib.db\x1b[0m downloading...",
            "",
        ]

        process = MagicMock()
        process.stdout.readline.side_effect = simulated_stdout + [""]
        process.poll.return_value = 0
        process.returncode = 0
        mock_popen.return_value = process

        with patch("apt_pac.commands.Progress") as MockProgress:
            mock_progress_instance = MockProgress.return_value
            mock_progress_instance.__enter__.return_value = mock_progress_instance
            mock_progress_instance.add_task.return_value = 1

            commands.run_pacman_with_apt_output(["pacman", "-Fy"], total_pkgs=None)

            calls = mock_progress_instance.update.call_args_list
            desc_updates = [c.kwargs.get("description", "") for c in calls]

            # Should match "Downloading core" (case insensitive match on core/Downloading)
            # The code uppercases "Downloading" but preserves package name case from parts?
            # parts = line_clean.split(). "core"
            # desc = "Downloading core"

            # Check for core
            has_core = any("Downloading core" in d for d in desc_updates)
            self.assertTrue(
                has_core,
                f"Failed to parse 'core downloading...'. Updates: {desc_updates}",
            )

            # Check for multilib.db
            has_multi = any("Downloading multilib.db" in d for d in desc_updates)
            self.assertTrue(
                has_multi,
                f"Failed to parse 'multilib.db downloading...'. Updates: {desc_updates}",
            )


if __name__ == "__main__":
    unittest.main()
