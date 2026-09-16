"""Make the self-contained skill helpers and maintainer adapters importable."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills/litigation/document-discovery/scripts"))
