"""
Internationalization (i18n) support for apt-pac.

Uses Python's gettext module to provide translations.
Falls back to English if no translation is available.
"""

import gettext
import os
from pathlib import Path


# Determine locale directory
# For installed package: /usr/share/locale
# For development: repo/locales
def _get_locale_dir():
    # Try installed location first
    # Try reading from user config manually to avoid circular import with config.py
    # Look for [directories] locale_dir = "..."
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    user_config = config_home / "apt-pac" / "config.toml"

    if user_config.exists():
        try:
            with open(user_config, "r", encoding="utf-8") as f:
                for line in f:
                    if "locale_dir" in line and "=" in line:
                        # Very basic parsing: locale_dir = "path/to/locales"
                        parts = line.split("=", 1)
                        key = parts[0].strip()
                        if key == "locale_dir":
                            val = parts[1].strip().strip("\"'")
                            custom_locale = Path(val)
                            if custom_locale.exists():
                                return str(custom_locale)
        except Exception:
            pass

    import sys

    # Try installed location based on python prefix (works for /usr, /usr/local, venvs)
    system_locale = Path(sys.prefix) / "share" / "locale"
    if system_locale.exists():
        return str(system_locale)

    # Fall back to repo locales directory (simplified structure)
    repo_root = Path(__file__).parent.parent.parent
    repo_locale = repo_root / "locales"
    if repo_locale.exists():
        return str(repo_locale)

    # No translations available
    return None


# Initialize gettext
_locale_dir = _get_locale_dir()
_domain = "apt-pac"

if _locale_dir:
    try:
        # Detect locale from environment
        lang = os.environ.get("LANG", os.environ.get("LC_ALL", "C"))

        # Python gettext handles both structures:
        # - Installed: /usr/share/locale/es/LC_MESSAGES/apt-pac.mo
        # - Development: locales/es.mo
        translation = gettext.translation(_domain, localedir=_locale_dir, fallback=True)
        _ = translation.gettext
    except Exception:
        # Fallback to English (no-op)
        def _(msg):
            return msg
else:
    # No locale dir, use English
    def _(msg):
        return msg


__all__ = ["_"]
