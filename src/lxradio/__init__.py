__version__ = "0.1.0"

import os
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lxradio"
