import os
import sys
import time
import getpass
from pathlib import Path

def setup_logger():
    """
    Determines the appropriate log file path based on permissions and existence.
    Priorities:
    1. /var/log/apt-pac.log (if writable or running as root)
    2. /run/log/apt-pac.log (if writable)
    3. User local state: $XDG_STATE_HOME/apt-pac/history.log
    """
    uid = os.getuid()
    
    # Potential system paths
    system_paths = [
        Path("/var/log/apt-pac.log"),
        Path("/run/log/apt-pac.log")
    ]
    
    log_file = None
    
    # Try system paths if root or if we have write access
    for path in system_paths:
        try:
            # Check if directory exists
            if not path.parent.exists():
                continue
                
            # Check writability
            if uid == 0:
                # Root can write anywhere usually
                log_file = path
                break
            elif path.exists() and os.access(path, os.W_OK):
                # File exists and is writable by us
                log_file = path
                break
            elif not path.exists() and os.access(path.parent, os.W_OK):
                # File doesn't exist but dir is writable
                log_file = path
                break
        except Exception:
            continue
            
    # Fallback to user local state
    if not log_file:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        if xdg_state:
            base_dir = Path(xdg_state)
        else:
            base_dir = Path.home() / ".local" / "state"
            
        log_dir = base_dir / "apt-pac"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "history.log"
        except Exception:
            # Last resort: just don't log if we can't create user dir
            return None

    return log_file

def log_action(apt_cmd, extra_args):
    """
    Logs the executed command and arguments to the determined log file.
    Format: YYYY-MM-DD HH:MM:SS [USER] apt-pac <command> <args>
    """
    log_path = setup_logger()
    if not log_path:
        return

    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Get real user if running via sudo
        sudo_user = os.environ.get("SUDO_USER")
        current_user = getpass.getuser()
        
        if sudo_user and sudo_user != current_user:
            user_str = f"{sudo_user}(as {current_user})"
        else:
            user_str = current_user
            
        # Reconstruct command string
        args_str = " ".join(extra_args)
        log_entry = f"{timestamp} [{user_str}] apt-pac {apt_cmd} {args_str}\n"
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
    except Exception:
        # Silently fail logging (should not crash the app)
        pass
