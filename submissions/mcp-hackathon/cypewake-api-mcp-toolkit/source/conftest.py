"""pytest 根 conftest：确保项目根目录在 sys.path 上，使 tests/ 能 import core / server。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
