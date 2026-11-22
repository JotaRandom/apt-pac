"""
Internationalization (i18n) support for apt-pac.

Uses Python's gettext module to provide translations.
Falls back to English if no translation is available.
"""

import gettext
import os
import sys
from pathlib import Path
from typing import Optional

_domain = "apt-pac"


def _preferred_languages() -> list[str]:
    """Return ordered list of locale codes from environment."""
    langs: list[str] = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if not val:
            continue
        for item in val.split(":"):
            code = item.strip()
            if not code or code in ("C", "POSIX"):
                continue
            base = code.split(".")[0].split("@")[0]
            if base and base not in langs:
                langs.append(base)
            short = base.split("_")[0]
            if short and short not in langs:
                langs.append(short)
        if langs:
            break
    return langs


def _read_custom_locale_dir() -> Optional[Path]:
    """Read [directories].locale_dir from user config without importing config.py."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    user_config = config_home / "apt-pac" / "config.toml"
    if not user_config.exists():
        return None
    try:
        import tomllib

        with open(user_config, "rb") as f:
            data = tomllib.load(f)
        val = data.get("directories", {}).get("locale_dir", "")
        if val:
            custom_locale = Path(val)
            if custom_locale.exists():
                return custom_locale
    except Exception:
        pass
    return None


def _get_locale_dir() -> Optional[str]:
    """Locate a directory containing compiled apt-pac translations."""
    candidates: list[Path] = []

    custom_locale = _read_custom_locale_dir()
    if custom_locale:
        candidates.append(custom_locale)

    candidates.append(Path(sys.prefix) / "share" / "locale")
    candidates.append(Path("/usr/share/locale"))
    candidates.append(Path(__file__).parent.parent.parent / "locales")

    langs = _preferred_languages()
    for candidate in candidates:
        if not candidate.exists():
            continue
        if gettext.find(_domain, localedir=str(candidate), languages=langs or None):
            return str(candidate)
        for lang in langs:
            if (candidate / f"{lang}.mo").is_file():
                return str(candidate)

    return None


def _load_translation():
    """Load gettext translation, supporting both standard and flat dev layouts."""
    locale_dir = _get_locale_dir()
    if not locale_dir:
        return None

    langs = _preferred_languages()
    if langs and gettext.find(_domain, localedir=locale_dir, languages=langs):
        return gettext.translation(_domain, localedir=locale_dir, languages=langs, fallback=True)

    # Flat development layout: locales/<lang>.mo
    for lang in langs:
        flat_mo = Path(locale_dir) / f"{lang}.mo"
        if flat_mo.is_file():
            with open(flat_mo, "rb") as fp:
                return gettext.GNUTranslations(fp)

    return None


try:
    _translation = _load_translation()
    if _translation is not None:
        _ = _translation.gettext
    else:
        def _(msg):
            return msg
except Exception:
    def _(msg):
        return msg


__all__ = ["_"]
