import sys
from pathlib import Path

# Ensure src/ is on path
SRC = Path(__file__).parent.parent
sys.path.insert(0, str(SRC))