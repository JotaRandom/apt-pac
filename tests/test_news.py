import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath("src"))
from apt_pac.commands import execute_command


class TestNewsCommand(unittest.TestCase):
    def setUp(self):
        # Sample RSS XML construction helper
        self.rss_template = """
        <rss version="2.0">
        <channel>
            <title>Arch Linux News</title>
            {}
        </channel>
        </rss>
        """
        self.item_template = """
            <item>
                <title>{title}</title>
                <pubDate>{date}</pubDate>
                <link>{link}</link>
                <description>{desc}</description>
            </item>
        """

    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.urllib.request.urlopen")
    def test_news_fetch_success_filtering(self, mock_urlopen, mock_console):
        # 1. Setup mock response
        now = datetime.now(timezone.utc)
        recent_date = (now - timedelta(days=5)).strftime("%a, %d %b %Y %H:%M:%S %z")
        old_date = (now - timedelta(days=200)).strftime("%a, %d %b %Y %H:%M:%S %z")

        items_xml = self.item_template.format(
            title="Recent News",
            date=recent_date,
            link="http://example.com/1",
            desc="Desc 1",
        )
        items_xml += self.item_template.format(
            title="Old News", date=old_date, link="http://example.com/2", desc="Desc 2"
        )

        xml_content = self.rss_template.format(items_xml).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = xml_content
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # 2. execute
        # We also need to mock subprocess/pager or console.print will be called depending on PAGER
        # Let's mock shutil.which to return False so it falls back to console.print or fake pager logic
        # But wait, the code checks os.environ.get("PAGER").
        with (
            patch("apt_pac.commands.shutil.which", return_value=False),
            patch.dict(os.environ, {}, clear=True),
        ):
            # No pager, no 'less' -> Use console.print

            execute_command("news", [])

        # 3. Assert
        # console.print should be called with "Recent News" but NOT "Old News"
        # We need to capture what was printed.
        # The code constructs a huge string 'full_text' and prints it once or twice.

        args_list = mock_console.print.call_args_list
        found_recent = False
        found_old = False

        for args, _ in args_list:
            text = str(args[0])
            if "Recent News" in text:
                found_recent = True
            if "Old News" in text:
                found_old = True

        self.assertTrue(found_recent, "Should show recent news")
        self.assertFalse(found_old, "Should NOT show old news (older than 6 months)")

    @patch("apt_pac.commands.console")
    @patch("apt_pac.commands.urllib.request.urlopen")
    def test_news_fallback_to_latest(self, mock_urlopen, mock_console):
        # Scenario: Only old news exist. Should show the latest one.
        now = datetime.now(timezone.utc)
        # Both are old, but one is newer than the other
        old_date_1 = (now - timedelta(days=200)).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )  # Latest of the old
        old_date_2 = (now - timedelta(days=300)).strftime("%a, %d %b %Y %H:%M:%S %z")

        items_xml = self.item_template.format(
            title="Old News Leet",
            date=old_date_1,
            link="http://example.com/1",
            desc="Desc 1",
        )
        items_xml += self.item_template.format(
            title="Ancient News",
            date=old_date_2,
            link="http://example.com/2",
            desc="Desc 2",
        )

        xml_content = self.rss_template.format(items_xml).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = xml_content
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with (
            patch("apt_pac.commands.shutil.which", return_value=False),
            patch.dict(os.environ, {}, clear=True),
        ):
            execute_command("news", [])

        args_list = mock_console.print.call_args_list
        found_leet = False
        found_ancient = False

        for args, _ in args_list:
            text = str(args[0])
            if "Old News Leet" in text:
                found_leet = True
            if "Ancient News" in text:
                found_ancient = True

        self.assertTrue(found_leet, "Should fallback to show the latest old news")
        self.assertFalse(
            found_ancient,
            "Should NOT show ancient news if fallback selects only the latest",
        )

    @patch("apt_pac.commands.print_error")
    @patch("apt_pac.commands.urllib.request.urlopen")
    def test_news_fetch_error(self, mock_urlopen, mock_print_error):
        mock_urlopen.side_effect = Exception("Network Error")

        with self.assertRaises(SystemExit):
            execute_command("news", [])

        mock_print_error.assert_called()


if __name__ == "__main__":
    unittest.main()
