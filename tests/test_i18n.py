import ast
import configparser
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apt_pac import i18n

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "locales"


def _parse_po_entries(po_path: Path) -> list[tuple[bool, str, str]]:
    """Parse a gettext .po file into (is_fuzzy, msgid, msgstr) entries."""
    lines = po_path.read_text(encoding="utf-8").splitlines()
    entries: list[tuple[bool, str, str]] = []
    fuzzy = False
    mode: str | None = None
    cur_id: list[str] = []
    cur_str: list[str] = []
    seen_entry = False

    def _unquote(raw: str) -> str:
        return (
            raw.strip()[1:-1]
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )

    def _flush() -> None:
        nonlocal fuzzy, cur_id, cur_str, seen_entry
        if seen_entry:
            entries.append((fuzzy, "".join(cur_id), "".join(cur_str)))
        fuzzy = False
        cur_id = []
        cur_str = []
        seen_entry = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            _flush()
            mode = None
            continue
        if stripped.startswith("#"):
            if stripped.startswith("#,") and "fuzzy" in stripped:
                fuzzy = True
            continue
        if stripped.startswith("msgid "):
            _flush()
            seen_entry = True
            mode = "id"
            cur_id.append(_unquote(stripped[len("msgid ") :]))
        elif stripped.startswith("msgstr "):
            mode = "str"
            cur_str.append(_unquote(stripped[len("msgstr ") :]))
        elif stripped.startswith('"') and mode in ("id", "str"):
            val = _unquote(stripped)
            if mode == "id":
                cur_id.append(val)
            else:
                cur_str.append(val)

    _flush()
    return [(f, mid, mstr) for f, mid, mstr in entries if mid != ""]


class TestI18n(unittest.TestCase):
    def test_locales_ini_catalogs_exist_and_use_utf8(self):
        ini_path = LOCALES_DIR / "locales.ini"
        self.assertTrue(ini_path.is_file())
        self.assertTrue((LOCALES_DIR / "apt-pac.pot").is_file())

        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding="utf-8")
        locales = list(parser["locales"].keys())
        self.assertGreaterEqual(len(locales), 5)

        for lang in locales:
            po_file = LOCALES_DIR / f"{lang}.po"
            self.assertTrue(po_file.is_file(), f"Missing .po file for {lang}")
            head = "\n".join(po_file.read_text(encoding="utf-8").splitlines()[:25])
            self.assertIn("charset=UTF-8", head, f"{lang}.po must use UTF-8")

    def test_es_po_100_percent_translated_and_valid(self):
        es_po = LOCALES_DIR / "es.po"
        entries = _parse_po_entries(es_po)
        self.assertGreaterEqual(len(entries), 350)

        placeholder_re = re.compile(r"\{[a-zA-Z0-9_]+\}")
        for is_fuzzy, msgid, msgstr in entries:
            self.assertFalse(is_fuzzy, f"Fuzzy entry found: {msgid!r}")
            self.assertTrue(msgstr.strip(), f"Untranslated msgid: {msgid!r}")
            expected_vars = set(placeholder_re.findall(msgid))
            actual_vars = set(placeholder_re.findall(msgstr))
            self.assertEqual(
                expected_vars,
                actual_vars,
                f"Placeholder mismatch for {msgid!r}",
            )

        msgfmt = shutil.which("msgfmt")
        if msgfmt:
            with tempfile.TemporaryDirectory() as tmp:
                for po_file in sorted(LOCALES_DIR.glob("*.po")):
                    mo_out = Path(tmp) / f"{po_file.stem}.mo"
                    res = subprocess.run(
                        [msgfmt, "--check", "-o", str(mo_out), str(po_file)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        res.returncode,
                        0,
                        f"msgfmt failed for {po_file.name}: {res.stderr}",
                    )

    def test_runtime_translation_loading_and_english_fallback(self):
        msgfmt = shutil.which("msgfmt")
        if not msgfmt:
            self.skipTest("msgfmt is required to compile test .mo catalog")

        es_po = LOCALES_DIR / "es.po"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                std_mo = tmp_path / "std_locale" / "es" / "LC_MESSAGES" / "apt-pac.mo"
                std_mo.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [msgfmt, "--check", "-o", str(std_mo), str(es_po)],
                    check=True,
                )

                xdg_cfg = tmp_path / "cfg"
                cfg_file = xdg_cfg / "apt-pac" / "config.toml"
                cfg_file.parent.mkdir(parents=True, exist_ok=True)
                cfg_file.write_text(
                    f'[directories]\nlocale_dir = "{(tmp_path / "std_locale").as_posix()}"\n',
                    encoding="utf-8",
                )

                env_es = {
                    "XDG_CONFIG_HOME": str(xdg_cfg),
                    "LANGUAGE": "es_ES:es",
                    "LC_ALL": "",
                    "LC_MESSAGES": "",
                    "LANG": "es_ES.UTF-8",
                }
                with patch.dict(os.environ, env_es, clear=False):
                    tr = i18n.reload_translations()
                    self.assertEqual(
                        tr("Reading package lists"), "Leyendo lista de paquetes"
                    )
                    self.assertEqual(
                        tr("All packages are up to date."),
                        "Todos los paquetes están actualizados.",
                    )

                env_c = {
                    "XDG_CONFIG_HOME": str(xdg_cfg),
                    "LANGUAGE": "C",
                    "LC_ALL": "C",
                    "LC_MESSAGES": "C",
                    "LANG": "C",
                }
                with patch.dict(os.environ, env_c, clear=False):
                    tr_en = i18n.reload_translations()
                    self.assertEqual(
                        tr_en("Reading package lists"), "Reading package lists"
                    )
        finally:
            i18n.reload_translations()

    def test_no_source_module_shadows_gettext_underscore(self):
        for py_file in sorted((REPO_ROOT / "src" / "apt_pac").glob("*.py")):
            if py_file.name == "i18n.py":
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            imports_gettext = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "i18n"
                and any(alias.name == "_" for alias in node.names)
                for node in ast.walk(tree)
            )
            if not imports_gettext:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Store)
                    and node.id == "_"
                ):
                    self.fail(
                        f"{py_file.name}:{node.lineno} assigns to '_', shadowing gettext '_()'"
                    )


if __name__ == "__main__":
    unittest.main()
