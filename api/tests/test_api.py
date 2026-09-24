from fastapi.testclient import TestClient

from app.main import MAX_TIE_PAGE_LIMIT, TIE_PREVIEW_LIMIT, app

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


# ------------------------------------------------------- mass-tie behaviour
def _groups_payload(sizes=(3, 3, 3, 3)):
    """One group per tetrahedron vertex; target (1,1,1) forces one pick from
    each group, so the tie count is the product of the group sizes."""
    pts = [(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)]
    ems = []
    for g, n in enumerate(sizes):
        for i in range(n):
            ems.append(
                {
                    "id": f"G{g}E{i}",
                    "t0": str(pts[g][0]),
                    "t1": str(pts[g][1]),
                    "t2": str(pts[g][2]),
                    "cost": "1",
                }
            )
    return {"endmembers": ems, "target": ["1", "1", "1"]}


def test_tied_preview_capped_but_count_and_classification_full():
    body = _post(_groups_payload()).json()
    assert body["feasible"] is True
    # 3*3*3*3 tied solutions exist, but the first response must not
    # enumerate them all -- only a bounded preview in canonical order.
    assert body["tie_count"] == 81
    assert len(body["tied"]) == TIE_PREVIEW_LIMIT
    assert body["tied"][0] == body["solution"]
    # conclusions still cover the complete tie set
    assert len(body["classification"]) == 12
    assert set(body["classification"].values()) == {"partial"}
    weights = {w["id"]: w["fraction"] for w in body["solution"]["weights"]}
    assert weights == {"G0E0": "1/4", "G1E0": "1/4", "G2E0": "1/4", "G3E0": "1/4"}
    assert body["solution"]["cost"] == 4


def test_tie_paging_covers_every_tie_consistently():
    payload = _groups_payload()
    first = _post(payload).json()

    pages = []
    offset = 0
    while True:
        r = client.post(
            "/api/audit/ties", json={**payload, "offset": offset, "limit": 30}
        )
        body = r.json()
        assert body["feasible"] is True
        assert body["tie_count"] == 81
        if not body["tied"]:
            break
        pages.extend(body["tied"])
        offset += len(body["tied"])
    assert len(pages) == 81  # every tied solution reachable through paging

    # the preview in the audit response is exactly the first page
    assert pages[:TIE_PREVIEW_LIMIT] == first["tied"]

    keys = [tuple(s["ids"]) for s in pages]
    assert len(set(keys)) == 81
    assert keys == sorted(keys)  # canonical lexicographic order
    for s in pages:
        assert s["cost"] == 4
        assert [w["fraction"] for w in s["weights"]] == ["1/4"] * 4


def test_tie_paging_window_edges():
    payload = _groups_payload()
    r = client.post("/api/audit/ties", json={**payload, "offset": 80, "limit": 30})
    page = r.json()["tied"]
    assert len(page) == 1  # clamped at the end of the tie set
    r = client.post("/api/audit/ties", json={**payload, "offset": 81, "limit": 30})
    assert r.json()["tied"] == []


def test_tie_paging_rejects_bad_window():
    payload = _groups_payload()
    r = client.post("/api/audit/ties", json={**payload, "offset": -1, "limit": 0})
    fields = {e["field"] for e in r.json()["errors"]}
    assert "offset" in fields and "limit" in fields
    r = client.post(
        "/api/audit/ties",
        json={**payload, "offset": 0, "limit": MAX_TIE_PAGE_LIMIT + 1},
    )
    assert "limit" in {e["field"] for e in r.json()["errors"]}


def test_tie_paging_infeasible_and_invalid_requests():
    r = client.post(
        "/api/audit/ties",
        json={"endmembers": SQUARE, "target": ["1", "1", "9"]},
    )
    body = r.json()
    assert body["feasible"] is False and body["tied"] == [] and not body["errors"]

    r = client.post(
        "/api/audit/ties",
        json={"endmembers": SQUARE[:2], "target": ["1", "1", "0"]},
    )
    assert any(e["field"] == "endmembers" for e in r.json()["errors"])
