"""Pytest fixture-root for the thin API.

The thin API is packaged as a Lambda with asset root ``api/`` and handler
``app.main.handler`` — so at runtime the ``app`` package is the top-level module,
NOT ``api.app``. Intra-package imports are therefore ``app.*`` (review finding 1).

Putting the ``api/`` directory on ``sys.path`` here makes ``app`` importable during
tests via the SAME path the deployed Lambda uses, so the unit suite exercises the
real cold-start import resolution rather than masking it behind an ``api`` package.
"""

from __future__ import annotations

import os
import sys

_API_DIR = os.path.dirname(os.path.abspath(__file__))
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)
