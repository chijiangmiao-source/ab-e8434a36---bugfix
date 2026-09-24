from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _post(payload):
    return client.post("/api/audit", json=payload)


SQUARE = [
    {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"},
    {"id": "B", "t0": "2", "t1": "2", "t2": "0", "cost": "1"},
    {"id": "C", "t0": "0", "t1": "2", "t2": "0", "cost": "1"},
    {"id": "D", "t0": "2", "t1": "0", "t2": "0", "cost": "1"},
]


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_feasible_returns_canonical_fractions():
    r = _post({"endmembers": SQUARE, "target": ["1", "1", "0"]})
    body = r.json()
    assert body["feasible"] is True
    assert body["solution"]["ids"] == ["A", "B"]
    weights = {w["id"]: w for w in body["solution"]["weights"]}
    assert weights["A"]["fraction"] == "1/2"
    assert weights["A"]["numerator"] == 1
    assert weights["A"]["denominator"] == 2
    assert body["tie_count"] == 2


def test_infeasible_outside_hull():
    r = _post({"endmembers": SQUARE, "target": ["1", "1", "9"]})
    body = r.json()
    assert body["feasible"] is False
    assert body["solution"] is None
    assert body["errors"] == []


def test_invalid_integer_is_field_localised():
    ems = [dict(e) for e in SQUARE]
    ems[1]["t1"] = "2.5"
    r = _post({"endmembers": ems, "target": ["1", "1", "0"]})
    body = r.json()
    assert body["feasible"] is False
    fields = {e["field"] for e in body["errors"]}
    assert "endmembers[1].t1" in fields


def test_tracer_boundary_and_cost_rules():
    ems = [dict(e) for e in SQUARE]
    ems[0]["t0"] = "1000001"
    ems[2]["cost"] = "0"
    r = _post({"endmembers": ems, "target": ["1", "1", "0"]})
    fields = {e["field"] for e in r.json()["errors"]}
    assert "endmembers[0].t0" in fields
    assert "endmembers[2].cost" in fields


def test_target_too_many_decimals_rejected():
    r = _post({"endmembers": SQUARE, "target": ["1.12345", "1", "0"]})
    fields = {e["field"] for e in r.json()["errors"]}
    assert "target[0]" in fields


def test_duplicate_and_non_ascii_ids_rejected():
    ems = [dict(e) for e in SQUARE]
    ems[3]["id"] = "B"
    ems[0]["id"] = "火山A"
    r = _post({"endmembers": ems, "target": ["1", "1", "0"]})
    fields = {e["field"] for e in r.json()["errors"]}
    assert "endmembers[0].id" in fields
    assert "endmembers[3].id" in fields


def test_batch_size_limits():
    r = _post({"endmembers": SQUARE[:2], "target": ["1", "1", "0"]})
    assert any(e["field"] == "endmembers" for e in r.json()["errors"])


def test_malformed_json_body_still_200_with_field_error():
    r = client.post("/api/audit", json={"endmembers": "nope"})
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is False and body["errors"]


def test_classification_payload():
    ems = [dict(e) for e in SQUARE]
    ems.append({"id": "E", "t0": "40", "t1": "40", "t2": "40", "cost": "1"})
    r = _post({"endmembers": ems, "target": ["1", "1", "0"]})
    cls = r.json()["classification"]
    assert cls["A"] == "partial" and cls["E"] == "never"


# ------------------------------------------------------------- tie paging
def _four_groups(counts=(7, 7, 8, 8), id_len=1000):
    """30 endmembers in four tetrahedron groups; (1,1,1) picks one of each."""
    origins = [(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)]
    ems = []
    for g, (origin, n) in enumerate(zip(origins, counts)):
        for k in range(n):
            # unique legal ASCII id, deterministic and ~id_len characters
            stem = f"G{g}E{k:02d}-"
            ems.append({
                "id": stem + "x" * (id_len - len(stem)),
                "t0": str(origin[0]), "t1": str(origin[1]),
                "t2": str(origin[2]), "cost": "1",
            })
    return ems


def test_first_response_inlines_only_one_tie_page():
    payload = {"endmembers": _four_groups(), "target": ["1", "1", "1"]}
    r = _post(payload)
    body = r.json()
    assert body["feasible"] is True
    assert body["tie_count"] == 3136
    assert body["tie_offset"] == 0
    assert body["tie_page_size"] == 20
    assert len(body["tied"]) == 20
    # canonical solution is still the lexicographically first tie
    assert body["solution"]["ids"] == body["tied"][0]["ids"]
    assert {w["fraction"] for w in body["solution"]["weights"]} == {"1/4"}
    # the first response must not repeat every long id: far below one full
    # expansion (3136 solutions * ~8 KB/solution ~= 26 MB)
    assert len(r.content) < 300_000


def test_classification_covers_all_thirty_on_full_tie_set():
    payload = {"endmembers": _four_groups(), "target": ["1", "1", "1"]}
    cls = _post(payload).json()["classification"]
    # every endmember participates in some (but not all) of the 3136 ties
    assert len(cls) == 30
    assert all(v == "partial" for v in cls.values())


def test_tie_pages_cover_full_set_in_canonical_order():
    ems = _four_groups()
    payload = {"endmembers": ems, "target": ["1", "1", "1"]}
    seen = []
    for offset in range(0, 3136, 20):
        r = client.post("/api/audit/ties", json={**payload, "offset": offset, "limit": 20})
        page = r.json()
        assert page["tie_count"] == 3136
        assert page["offset"] == offset
        seen.extend(tuple(s["ids"]) for s in page["solutions"])
    assert len(seen) == 3136
    assert len(set(seen)) == 3136  # all unique
    assert seen == sorted(seen)     # canonical lexicographic order
    # weights are the exact quarter on every solution
    for s_ids in (seen[0], seen[-1], seen[len(seen) // 2]):
        assert len(s_ids) == 4
        # every combination takes exactly one endmember from each group
        assert [s_id[:2] for s_id in s_ids] == ["G0", "G1", "G2", "G3"]


def test_tie_page_weights_are_exact_quarters():
    ems = _four_groups()
    r = client.post(
        "/api/audit/ties",
        json={"endmembers": ems, "target": ["1", "1", "1"], "offset": 100, "limit": 5},
    )
    for sol in r.json()["solutions"]:
        assert len(sol["weights"]) == 4
        assert all(w["fraction"] == "1/4" and w["numerator"] == 1
                   and w["denominator"] == 4 for w in sol["weights"])


def test_tie_page_beyond_end_is_empty_and_errors_propagate():
    r = client.post(
        "/api/audit/ties",
        json={"endmembers": SQUARE, "target": ["1", "1", "0"], "offset": 99},
    )
    body = r.json()
    assert body["tie_count"] == 2
    assert body["solutions"] == []

    bad = [dict(e) for e in SQUARE]
    bad[0]["cost"] = "0"
    r = client.post(
        "/api/audit/ties",
        json={"endmembers": bad, "target": ["1", "1", "0"], "offset": 0},
    )
    assert r.json()["errors"]


def test_small_tie_sets_still_fully_inlined():
    # the two-diagonal case fits inside one page: nothing lost for small jobs
    body = _post({"endmembers": SQUARE, "target": ["1", "1", "0"]}).json()
    assert body["tie_count"] == 2
    assert [s["ids"] for s in body["tied"]] == [["A", "B"], ["C", "D"]]
