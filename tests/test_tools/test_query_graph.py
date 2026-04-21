"""Tests for mock_tools canned data (original) + query_graph read-path (new)."""
import uuid

import pytest
from sqlalchemy import select

from db import Edge, EdgeType, Entity, OntologyType


# ---------------------------------------------------------------------------
# Original mock_tools tests (unchanged)
# ---------------------------------------------------------------------------


def test_mock_company_data_has_overlap():
    from mock_tools import COMPANY_DATA, EMAIL_THREADS
    acme_emails = {e["email"] for e in COMPANY_DATA["Acme Corp"]["employees"]}
    thread_emails = {
        p["email"]
        for t in EMAIL_THREADS.values()
        for p in t.get("participants", [])
    }
    assert acme_emails & thread_emails, "No email overlap between company data and threads"


def test_fetch_company_data_returns_json():
    from mock_tools import COMPANY_DATA
    acme = COMPANY_DATA.get("Acme Corp")
    assert acme is not None
    assert "employees" in acme
    assert len(acme["employees"]) >= 2


def test_fetch_email_thread_has_participants():
    from mock_tools import EMAIL_THREADS
    for tid, thread in EMAIL_THREADS.items():
        assert "participants" in thread, f"Thread {tid} missing participants"
        assert "messages" in thread, f"Thread {tid} missing messages"


# ---------------------------------------------------------------------------
# Helpers shared by query_graph tests
# ---------------------------------------------------------------------------


async def _seed_type(session, name: str) -> uuid.UUID:
    """Get or create an OntologyType by name, return its id."""
    existing = await session.scalar(select(OntologyType).where(OntologyType.name == name))
    if existing:
        return existing.id
    ot = OntologyType(name=name, fields={}, status="provisional")
    session.add(ot)
    await session.flush()
    return ot.id


async def _seed_edge_type(
    session,
    name: str,
    is_transitive: bool = False,
    is_inverse_of: str | None = None,
) -> uuid.UUID:
    """Get or create an EdgeType by name, return its id."""
    existing = await session.scalar(select(EdgeType).where(EdgeType.name == name))
    if existing:
        return existing.id
    et = EdgeType(name=name, is_transitive=is_transitive, is_inverse_of=is_inverse_of)
    session.add(et)
    await session.flush()
    return et.id


async def _make_entity(session, type_id: uuid.UUID, props: dict) -> Entity:
    e = Entity(type_id=type_id, properties=props, source_refs=[])
    session.add(e)
    await session.flush()
    return e


async def _make_edge(
    session, src_id: uuid.UUID, dst_id: uuid.UUID, edge_type_id: uuid.UUID
) -> Edge:
    e = Edge(src_id=src_id, dst_id=dst_id, edge_type_id=edge_type_id)
    session.add(e)
    await session.flush()
    return e


# ---------------------------------------------------------------------------
# query_graph tests — call _query directly with the test session
# ---------------------------------------------------------------------------


async def test_query_by_entity_type(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Task_qbt")
    await _make_entity(session, type_id, {"title": "Test task"})

    result = await _query(session, "Task_qbt", None, None, None, 1, False)

    assert len(result["entities"]) >= 1
    assert all(e["type"] == "Task_qbt" for e in result["entities"])


async def test_query_by_properties(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Entity_qbp")
    await _make_entity(session, type_id, {"status": "needle", "other": "val"})
    await _make_entity(session, type_id, {"status": "haystack"})

    result = await _query(session, "Entity_qbp", {"status": "needle"}, None, None, 1, False)

    assert len(result["entities"]) == 1
    assert result["entities"][0]["properties"]["status"] == "needle"


async def test_query_related_to(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Entity_qrt")
    et_id = await _seed_edge_type(session, "related_to_qrt")

    a = await _make_entity(session, type_id, {"name": "A"})
    b = await _make_entity(session, type_id, {"name": "B"})
    await _make_edge(session, a.id, b.id, et_id)

    result = await _query(session, None, None, str(a.id), None, 1, False)

    entity_ids = {e["id"] for e in result["entities"]}
    assert str(b.id) in entity_ids
    assert len(result["edges"]) >= 1


async def test_query_multi_hop(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Entity_qmh")
    et_id = await _seed_edge_type(session, "related_to_qmh")

    a = await _make_entity(session, type_id, {"name": "A"})
    b = await _make_entity(session, type_id, {"name": "B"})
    c = await _make_entity(session, type_id, {"name": "C"})
    await _make_edge(session, a.id, b.id, et_id)
    await _make_edge(session, b.id, c.id, et_id)

    result = await _query(session, None, None, str(a.id), None, 2, False)

    entity_ids = {e["id"] for e in result["entities"]}
    assert str(c.id) in entity_ids


async def test_edges_have_names_not_uuids(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Entity_enn")
    et_id = await _seed_edge_type(session, "related_to_enn")

    a = await _make_entity(session, type_id, {"name": "A"})
    b = await _make_entity(session, type_id, {"name": "B"})
    await _make_edge(session, a.id, b.id, et_id)

    result = await _query(session, None, None, str(a.id), None, 1, False)

    assert len(result["edges"]) >= 1
    for edge in result["edges"]:
        # type must be a string name, not a UUID hex string
        edge_type = edge["type"]
        assert isinstance(edge_type, str)
        try:
            uuid.UUID(edge_type)
            pytest.fail(f"Edge type looks like a UUID: {edge_type!r}")
        except ValueError:
            pass  # not a UUID — correct


async def test_apply_inference_false(session):
    from query_graph import _query

    type_id = await _seed_type(session, "Entity_aif")
    # Use a non-transitive, non-inverse edge type so inference adds nothing
    et_id = await _seed_edge_type(session, "plain_edge_aif", is_transitive=False, is_inverse_of=None)

    a = await _make_entity(session, type_id, {"name": "A"})
    b = await _make_entity(session, type_id, {"name": "B"})
    await _make_edge(session, a.id, b.id, et_id)

    result = await _query(session, None, None, str(a.id), None, 1, False)

    # With apply_inference=False, no derived edges should be present
    for edge in result["edges"]:
        assert edge.get("derived") is False, f"Unexpected derived edge: {edge}"
