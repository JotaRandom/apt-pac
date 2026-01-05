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
    #NOTE: This is the default location for installed i18n but not the only possible location and we shouldn't depend on it as built-in but as default search path and check other or make it configurable somehow, some better solution sould be used.
    system_locale = Path("/usr/share/locale")
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
        translation = gettext.translation(
            _domain,
            localedir=_locale_dir,
            fallback=True
        )
        _ = translation.gettext
    except Exception:
        # Fallback to English (no-op)
        _ = lambda msg: msg
else:
    # No locale dir, use English
    _ = lambda msg: msg

__all__ = ["_"]
