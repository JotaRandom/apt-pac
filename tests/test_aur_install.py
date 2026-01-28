import unittest
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import aur


class TestAurInstall(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch("apt_pac.ui.console.print")
        self.mock_console_print = self.console_patcher.start()

        self.input_patcher = patch("apt_pac.ui.console.input", return_value="n")
        self.mock_console_input = self.input_patcher.start()

        self.print_summary_patcher = patch("apt_pac.aur.print_transaction_summary")
        self.mock_print_summary = self.print_summary_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.input_patcher.stop()
        self.print_summary_patcher.stop()

    def test_aur_install_summary(self):
        installer = aur.AurInstaller()

        # Mock resolver to return dummy packages
        pkg_list = [
            {"Name": "aur-pkg", "Version": "1.2-3"},
            {"Name": "dep-pkg", "Version": "0.9"},
        ]

        with patch("apt_pac.aur.AurResolver") as mock_resolver_cls:
            mock_resolver = mock_resolver_cls.return_value
            mock_resolver.resolve.return_value = pkg_list
            # Mock official deps
            mock_resolver.official_deps = set()

            with self.assertRaises(SystemExit):
                installer.install(["aur-pkg"])

            # Check if print_transaction_summary called with correct packages
            # Expected new_pkgs: [('aur-pkg', '1.2-3'), ('dep-pkg', '0.9')]
            # Note: get_resolved_package_info logic might sort/format them.
            # Assuming basic (name, ver) tuples.
            expected_pkgs = [("aur-pkg", "1.2-3"), ("dep-pkg", "0.9")]
            self.mock_print_summary.assert_called()
            args, kwargs = self.mock_print_summary.call_args
            # Verify the list of packages passed to new_pkgs matches our expected data
            # The order might vary depending on implementation, but likely stable.
            self.assertEqual(sorted(kwargs["new_pkgs"]), sorted(expected_pkgs))


if __name__ == "__main__":
    unittest.main()
