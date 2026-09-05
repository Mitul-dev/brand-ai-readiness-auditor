"""Import shim: makes the marketplace root importable from a skill script."""
from __future__ import annotations

import sys
from pathlib import Path


def bootstrap() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "aira" / "__init__.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return parent
    raise RuntimeError("marketplace root containing the 'aira' package not found")
