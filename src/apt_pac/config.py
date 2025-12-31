"""
Configuration management for apt-pac.

Hierarchy:
1. Global: /etc/apt-pac/config.toml (system-wide defaults)
2. User: ~/.config/apt-pac/config.toml (user overrides)

Directory fallback logic:
- Config: $XDG_CONFIG_HOME/apt-pac → ~/.config/apt-pac → ~/.apt-pac → /etc/apt-pac (readonly)
- Cache: $XDG_CACHE_HOME/apt-pac → ~/.cache/apt-pac → /tmp/apt-pac-cache → None (error)

If user config doesn't exist, it's auto-created from global.
If user config has errors, falls back to global gracefully.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

# Default configuration values (used as ultimate fallback)
DEFAULT_CONFIG = {
    "safeguards": {
        "mass_removal_threshold": 20,
        "warn_partial_upgrades": True,
    },
    "tools": {
        "privilege_tool": "auto",  # auto, sudo, doas, run0
        "editor": "",  # Empty = use $EDITOR
    },
    "ui": {
        "show_output": "apt-pac",  # apt-pac, apt, pacman
        "force_colors": False,
        "verbosity": 1,
        "show_pacman_command": False,
    },
    "defaults": {
        "always_sync_files": True,
    },
    "directories": {
        "cache_dir": "",  # Empty = auto-detect with XDG fallback
    },
    "performance": {
        "rpc_cache_ttl": 30,  # minutes
    }
}

DEFAULT_CONFIG_TOML = """# apt-pac Configuration File
# This file controls apt-pac wrapper behavior.
# System configuration (repos, mirrors, etc.) is still in /etc/pacman.conf

[safeguards]
# Warn when removing more than this many packages
mass_removal_threshold = 20

# Warn about partial upgrades (installing packages when updates available)
warn_partial_upgrades = true

[tools]
# Privilege escalation tool: "auto", "sudo", "doas", "run0"
# "auto" tries run0 > doas > sudo in order
privilege_tool = "auto"

# Editor for edit-sources command (empty = use $EDITOR)
editor = ""

[ui]
# Output format: "apt-pac", "apt", or "pacman"
# - "apt-pac" or "apt": Formatted, colorized APT-style output (default)
# - "pacman": Show raw pacman output without formatting
show_output = "apt-pac"

# Force colors even in non-TTY environments
force_colors = false

# Verbosity level: 0 (quiet), 1 (normal), 2 (verbose), 3 (debug)
verbosity = 1

# Show the actual pacman command before executing
show_pacman_command = false

[defaults]
# Always sync file database (-Fy) during upgrade
always_sync_files = true

[directories]
# Custom cache directory (empty = auto-detect)
# If set, overrides XDG fallback logic
cache_dir = ""

[performance]
# Time to live for AUR RPC cache in minutes (0 = disable cache)
rpc_cache_ttl = 30
"""

def _get_config_dir() -> Optional[Path]:
    """
    Get config directory with fallback logic.
    
    Priority:
    1. $XDG_CONFIG_HOME/apt-pac
    2. ~/.config/apt-pac
    3. ~/.apt-pac
    4. /etc/apt-pac (read-only, last resort)
    """
    # Try XDG_CONFIG_HOME
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        config_dir = Path(xdg_config) / "apt-pac"
        if _try_create_dir(config_dir):
            return config_dir
    
    # Try ~/.config/apt-pac
    home = os.environ.get("HOME")
    if home:
        config_dir = Path(home) / ".config" / "apt-pac"
        if _try_create_dir(config_dir):
            return config_dir
        
        # Try ~/.apt-pac
        config_dir = Path(home) / ".apt-pac"
        if _try_create_dir(config_dir):
            return config_dir
    
    # Last resort: /etc/apt-pac (read-only)
    return Path("/etc/apt-pac")

def _get_cache_dir(custom_path: Optional[str] = None) -> Optional[Path]:
    """
    Get cache directory with fallback logic.
    
    Priority:
    0. Custom path from config (if provided)
    1. $XDG_CACHE_HOME/apt-pac
    2. ~/.cache/apt-pac
    3. $XDG_RUNTIME_DIR/apt-pac (systemd user runtime dir)
    4. /run/user/$UID/apt-pac (systemd runtime fallback)
    5. /tmp/apt-pac-cache
    6. None (system is read-only, critical error)
    """
    # 0. Try custom path from config
    if custom_path:
        cache_dir = Path(custom_path)
        if _try_create_dir(cache_dir):
            return cache_dir
    
    # 1. Try XDG_CACHE_HOME
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        cache_dir = Path(xdg_cache) / "apt-pac"
        if _try_create_dir(cache_dir):
            return cache_dir
    
    # 2. Try ~/.cache/apt-pac
    home = os.environ.get("HOME")
    if home:
        cache_dir = Path(home) / ".cache" / "apt-pac"
        if _try_create_dir(cache_dir):
            return cache_dir
    
    # 3. Try XDG_RUNTIME_DIR (systemd user runtime)
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        cache_dir = Path(xdg_runtime) / "apt-pac"
        if _try_create_dir(cache_dir):
            return cache_dir
    
    # 4. Try systemd runtime directory fallback
    uid = os.getuid() if hasattr(os, 'getuid') else None
    if uid is not None:
        cache_dir = Path(f"/run/user/{uid}/apt-pac")
        if _try_create_dir(cache_dir):
            return cache_dir
    
    # 5. Try /tmp/apt-pac-cache
    cache_dir = Path("/tmp") / "apt-pac-cache"
    if _try_create_dir(cache_dir):
        return cache_dir
    
    # 6. All failed - critical error
    return None

def _try_create_dir(path: Path) -> bool:
    """Try to create directory. Returns True if successful or already exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        # Test write access
        test_file = path / ".write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except (OSError, IOError, PermissionError):
        return False

class Config:
    def __init__(self):
        # Determine config directory with fallback logic
        self.global_config_path = Path("/etc/apt-pac/config.toml")
        self.config_dir = _get_config_dir()
        
        # Determine user config file path
        if self.config_dir and self.config_dir != Path("/etc/apt-pac"):
            self.user_config_path = self.config_dir / "config.toml"
        else:
            self.user_config_path = None
        
        # Load config early to get custom cache path
        self.data = self._deep_copy(DEFAULT_CONFIG)
        self._load_config_only()
        
        # Get custom cache dir from config (if set)
        custom_cache = self.data.get("directories", {}).get("cache_dir", "")
        self.cache_dir = _get_cache_dir(custom_cache if custom_cache else None)
        
        # Warn if cache is unavailable
        if self.cache_dir is None:
            import sys
            print("W: Cannot create cache directory - system appears to be read-only", file=sys.stderr)
            print("W: ABS/AUR features will not be available", file=sys.stderr)
        
        # Re-load to get all settings
        self._load()
    
    def _deep_copy(self, d: Dict) -> Dict:
        """Deep copy a dictionary."""
        import copy
        return copy.deepcopy(d)
    
    def _load_config_only(self):
        """Load config early (before cache dir setup) to get custom cache path."""
        if self.user_config_path:
            self._ensure_user_config()
            user_loaded = self._try_load_config(self.user_config_path)
            if user_loaded:
                return
        
        # Try global if user failed
        self._try_load_config(self.global_config_path)
    
    def _load(self):
        """Load configuration with hierarchical fallback."""
        # 1. Ensure user config exists (copy from global if needed)
        if self.user_config_path:
            self._ensure_user_config()
            
            # 2. Try to load user config first
            user_loaded = self._try_load_config(self.user_config_path)
            
            if user_loaded:
                return
        
        # 3. If user config failed or unavailable, try global
        global_loaded = self._try_load_config(self.global_config_path)
        if not global_loaded:
            # Both failed, use hardcoded defaults (already loaded)
            pass
    
    def _ensure_user_config(self):
        """Ensure user config exists, creating from global or defaults."""
        if not self.user_config_path:
            return
            
        if self.user_config_path.exists():
            return
        
        # Try to copy from global
        if self.global_config_path.exists():
            try:
                shutil.copy2(self.global_config_path, self.user_config_path)
                return
            except (OSError, IOError):
                pass  # Fall through to create from defaults
        
        # Create from defaults
        try:
            with open(self.user_config_path, "w") as f:
                f.write(DEFAULT_CONFIG_TOML)
        except (OSError, IOError):
            pass  # Can't create config, will use defaults
    
    def _try_load_config(self, config_path: Path) -> bool:
        """Try to load a config file. Returns True if successful."""
        if not config_path or not config_path.exists():
            return False
        
        try:
            # Try Python 3.11+ built-in tomllib first
            try:
                import tomllib
            except ImportError:
                # Fallback to tomli for older Python
                try:
                    import tomli as tomllib
                except ImportError:
                    # No TOML parser available
                    return False
            
            with open(config_path, "rb") as f:
                loaded_config = tomllib.load(f)
                
                # Validate and merge with defaults
                if self._validate_config(loaded_config):
                    self._deep_merge(self.data, loaded_config)
                    return True
                else:
                    # Invalid config, don't use it
                    return False
                    
        except Exception:
            # Parse error or other issue
            return False
    
    def _validate_config(self, config: Dict) -> bool:
        """Validate config structure and values."""
        # Basic structure check
        if not isinstance(config, dict):
            return False
        
        # Validate specific options
        if "ui" in config and isinstance(config["ui"], dict):
            show_output = config["ui"].get("show_output")
            if show_output and show_output not in ["apt-pac", "apt", "pacman"]:
                # Invalid value, use default for this key
                config["ui"]["show_output"] = "apt-pac"
            
        if "tools" in config and isinstance(config["tools"], dict):
            privilege_tool = config["tools"].get("privilege_tool")
            if privilege_tool and privilege_tool not in ["auto", "sudo", "doas", "run0"]:
                config["tools"]["privilege_tool"] = "auto"
        
        return True
    
    def _deep_merge(self, base: Dict, update: Dict):
        """Deep merge update dict into base dict."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.data.get(section, {}).get(key, default)
    
    def get_cache_dir(self) -> Optional[Path]:
        """Get cache directory path. Returns None if unavailable."""
        return self.cache_dir

# Global config instance
_config = None

def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
