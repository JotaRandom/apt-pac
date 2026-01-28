import unittest
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import ui


class TestUiSummary(unittest.TestCase):
    def setUp(self):
        self.console_patcher = patch("apt_pac.ui.console.print")
        self.mock_console_print = self.console_patcher.start()

        self.print_col_patcher = patch("apt_pac.ui.print_columnar_list")
        self.mock_print_col = self.print_col_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.print_col_patcher.stop()

    def test_summary_removals(self):
        # Test removal formatting
        removes = [("pkg1", "1.0"), ("pkg2", "")]
        ui.print_transaction_summary(remove_pkgs=removes)

        # Expect print_columnar_list called with RED strings
        # Sorted: pkg1 [bold]1.0[/bold], pkg2
        expected = ["pkg1 [bold]1.0[/bold]", "pkg2"]
        self.mock_print_col.assert_called_with(expected, "red")

    def test_summary_installs_explicit_and_extra(self):
        # Test exact vs extra separation
        installs = [("target", "1.0"), ("dep", "0.9")]
        explicit = {"target"}

        ui.print_transaction_summary(new_pkgs=installs, explicit_names=explicit)

        self.assertEqual(self.mock_print_col.call_count, 2)

        # 1. Explicit (The following NEW...)
        args1 = self.mock_print_col.call_args_list[0][0][0]
        self.assertEqual(args1, ["target [bold]1.0[/bold]"])

        # 2. Extra (The following extra...)
        args2 = self.mock_print_col.call_args_list[1][0][0]
        self.assertEqual(args2, ["dep [bold]0.9[/bold]"])

    def test_summary_upgrades(self):
        upgrades = [("pkg", "1.0")]
        ui.print_transaction_summary(upgraded_pkgs=upgrades)

        expected = ["pkg [bold]1.0[/bold]"]
        self.mock_print_col.assert_called_with(expected, "green")


if __name__ == "__main__":
    unittest.main()
