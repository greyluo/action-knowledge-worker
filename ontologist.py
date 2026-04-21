"""Ontologist stub — full implementation in Task 6.

Provides make_ontologist_hook for spec_factory wiring.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_factory import RunContext


def make_ontologist_hook(run_ctx: "RunContext"):
    async def _hook(*args, **kwargs):
        return {}

    return _hook
