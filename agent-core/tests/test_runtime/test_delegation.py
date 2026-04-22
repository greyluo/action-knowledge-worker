"""Tests for multi-agent delegation mechanics."""
import pytest
from sqlalchemy import select

from db import EdgeType, OntologyType
from seed import run_seed


async def test_topology_edge_types_seeded(session):
    await run_seed(session)
    for name in ["delegates_to", "next_in_chain", "parallel_with",
                 "loops_back_to", "handles", "fallback_to", "seeded_with"]:
        et = await session.scalar(select(EdgeType).where(EdgeType.name == name))
        assert et is not None, f"Edge type {name!r} not seeded"


async def test_handoff_entity_type_seeded(session):
    await run_seed(session)
    ot = await session.scalar(select(OntologyType).where(OntologyType.name == "Handoff"))
    assert ot is not None
