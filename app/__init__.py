"""ToCheck Next — local bid-document duplicate checker."""
import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

__version__ = "1.0.0"
