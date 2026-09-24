#!/usr/bin/env python3
"""One-shot verification service.

Runs every required audit and exits non-zero on the first failed group:

  1. backend code tests (pytest)
  2. canonical rational weights (exact fraction strings)
  3. outside-convex-hull infeasibility
  4. tie classification (always / partial / never)
  5. long-id mass-tie audit: 3136 cost-tied solutions stay fully counted and
     classified, but the first response ships only a bounded preview and the
     remaining ties are paged out on demand
  6. build artefacts (web container serves the production bundle, which loads
     tie pages lazily instead of rendering every tie at once)
  7. API smoke (direct + through the web proxy)

Usage:  verify.py [api_base] [web_base]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_BASE", "http://api:8000")
WEB = os.environ.get("WEB_BASE", "http://web:80")
API_TESTS = os.environ.get("API_TESTS_DIR", "/srv/api")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode()


def post(url: str, payload: dict, timeout: float = 5.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def post_raw(url: str, payload: dict, timeout: float = 5.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def wait_for(url: str, label: str, attempts: int = 30) -> bool:
    for _ in range(attempts):
        try:
            status, _ = get(url)
            if status == 200:
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(1)
    print(f"[FAIL] {label} not reachable at {url}")
    return False


# ----------------------------------------------------------------- 1. tests
def run_pytest() -> None:
    print("[....] running backend pytest")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=API_TESTS,
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:]
    check("backend code tests (pytest)", proc.returncode == 0, " ".join(tail))


SQUARE = [
    {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"},
    {"id": "B", "t0": "2", "t1": "2", "t2": "0", "cost": "1"},
    {"id": "C", "t0": "0", "t1": "2", "t2": "0", "cost": "1"},
    {"id": "D", "t0": "2", "t1": "0", "t2": "0", "cost": "1"},
]

TETRA = [
    {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"},
    {"id": "B", "t0": "4", "t1": "0", "t2": "0", "cost": "1"},
    {"id": "C", "t0": "0", "t1": "4", "t2": "0", "cost": "1"},
    {"id": "D", "t0": "0", "t1": "0", "t2": "4", "cost": "1"},
]


# ----------------------------------------------- 2. canonical fraction weights
def check_canonical_weights() -> None:
    _, body = post(f"{API}/api/audit", {"endmembers": TETRA, "target": ["1", "1", "1"]})
    ok = True
    detail = ""
    if not body.get("feasible"):
        ok = False
        detail = "expected feasible tetrahedron interior point"
    else:
        sol = body["solution"]
        if sorted(w["id"] for w in sol["weights"]) != ["A", "B", "C", "D"]:
            ok = False
        for w in sol["weights"]:
            if w["fraction"] != "1/4" or (w["numerator"], w["denominator"]) != (1, 4):
                ok = False
                detail = f"bad fraction for {w['id']}: {w['fraction']}"
        if abs(sum(w["decimal"] for w in sol["weights"]) - 1.0) > 1e-9:
            ok = False
            detail = "weights do not sum to 1"
    check("canonical rational weights 1/4 (tetrahedron interior)", ok, detail)

    # decimal target 0.125 -> 7/8, 1/8 exactly
    ems = [
        {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"},
        {"id": "B", "t0": "1", "t1": "0", "t2": "0", "cost": "1"},
        {"id": "C", "t0": "0", "t1": "1", "t2": "0", "cost": "1"},
    ]
    _, body = post(f"{API}/api/audit", {"endmembers": ems, "target": ["0.125", "0", "0"]})
    frac = {w["id"]: w["fraction"] for w in body["solution"]["weights"]}
    check("four-decimal target yields exact 7/8 + 1/8", frac == {"A": "7/8", "B": "1/8"},
          str(frac))


# --------------------------------------------------- 3. outside hull infeasible
def check_outside_hull() -> None:
    _, body = post(f"{API}/api/audit", {"endmembers": SQUARE, "target": ["1", "1", "9"]})
    check(
        "outside convex hull -> feasible=false, no solution",
        body.get("feasible") is False and body.get("solution") is None
        and not body.get("errors"),
        json.dumps(body)[:300],
    )


# ----------------------------------------------------- 4. tie classification
def check_classification() -> None:
    # both diagonals tie -> all four partial
    _, body = post(f"{API}/api/audit", {"endmembers": SQUARE, "target": ["1", "1", "0"]})
    cls = body.get("classification", {})
    ok = (
        body.get("feasible")
        and body.get("tie_count") == 2
        and all(cls.get(i) == "partial" for i in "ABCD")
    )
    check("equal-cost ties -> all endmembers partial", ok, json.dumps(cls))

    # unique midpoint of A-B on the z axis with no competing representation
    ems = [
        {"id": "A", "t0": "0", "t1": "0", "t2": "0", "cost": "1"},
        {"id": "B", "t0": "2", "t1": "0", "t2": "0", "cost": "1"},
        {"id": "C", "t0": "0", "t1": "2", "t2": "0", "cost": "1"},
    ]
    _, body = post(f"{API}/api/audit", {"endmembers": ems, "target": ["1", "0", "0"]})
    cls = body.get("classification", {})
    check(
        "unique solution -> always/never classes",
        cls.get("A") == "always" and cls.get("B") == "always" and cls.get("C") == "never",
        json.dumps(cls),
    )


# ------------------------------------- 5. long-id mass-tie audit (3136 ties)
# 30 legal endmembers with ~1000-char ASCII ids in four vertex groups of
# 7/7/8/8, all cost 1, target (1,1,1): every optimal solution picks one
# member per group, so the first two levels tie 7*7*8*8 = 3136 ways.
TIE_GROUPS = [(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)]
TIE_GROUP_SIZES = [7, 7, 8, 8]
TIE_ID_LEN = 1000
EXPECTED_TIES = 7 * 7 * 8 * 8  # 3136
# The first response must stay a bounded preview, never a per-solution dump
# (the pre-fix response was 26,240,200 bytes here, ~831x the request).
MAX_FIRST_RESPONSE_BYTES = 1_000_000
TIE_PREVIEW_MAX = 24


def _long_id(group: int, idx: int) -> str:
    base = f"G{group}-E{idx:02d}-"
    return base + "x" * (TIE_ID_LEN - len(base))


def _mass_tie_payload() -> dict:
    ems = []
    for g, (n, pt) in enumerate(zip(TIE_GROUP_SIZES, TIE_GROUPS)):
        for i in range(n):
            ems.append(
                {
                    "id": _long_id(g, i),
                    "t0": str(pt[0]),
                    "t1": str(pt[1]),
                    "t2": str(pt[2]),
                    "cost": "1",
                }
            )
    return {"endmembers": ems, "target": ["1", "1", "1"]}


def check_mass_tie_long_ids() -> None:
    payload = _mass_tie_payload()
    req_bytes = len(json.dumps(payload).encode())

    # -- first response: complete conclusions, bounded enumeration -----------
    try:
        _, raw = post_raw(f"{API}/api/audit", payload, timeout=120.0)
        body = json.loads(raw.decode())
    except Exception as exc:  # noqa: BLE001
        check("3136-tie long-id audit: first response", False, str(exc))
        return

    ok = body.get("feasible") is True and body.get("tie_count") == EXPECTED_TIES
    check(
        "3136-tie long-id audit: feasible, tie_count == 3136",
        ok,
        f"feasible={body.get('feasible')} tie_count={body.get('tie_count')}",
    )

    sol = body.get("solution") or {}
    weights = sol.get("weights", [])
    ok = (
        sol.get("ids") == [_long_id(g, 0) for g in range(4)]
        and sol.get("cost") == 4
        and [w.get("fraction") for w in weights] == ["1/4"] * 4
        and [(w.get("numerator"), w.get("denominator")) for w in weights]
        == [(1, 4)] * 4
    )
    check(
        "3136-tie long-id audit: canonical solution with exact 1/4 weights",
        ok,
        json.dumps(sol)[:200],
    )

    cls = body.get("classification", {})
    submitted = [e["id"] for e in payload["endmembers"]]
    ok = sorted(cls) == sorted(submitted) and set(cls.values()) == {"partial"}
    check(
        "3136-tie long-id audit: classification over all 30 ties-based classes",
        ok,
        f"{len(cls)} entries, values={sorted(set(cls.values()))}",
    )

    preview = body.get("tied", [])
    ok = (
        0 < len(preview) <= TIE_PREVIEW_MAX
        and preview[0] == sol
        and len(raw) <= MAX_FIRST_RESPONSE_BYTES
    )
    check(
        "3136-tie long-id audit: first response is a bounded preview "
        f"(tied={len(preview)}, {len(raw)} bytes vs {req_bytes} sent)",
        ok,
        f"tied={len(preview)} bytes={len(raw)}",
    )

    # -- on-demand pages: same 3136 ties, stable canonical windows ------------
    def page(offset: int, limit: int) -> dict:
        return post(
            f"{API}/api/audit/ties",
            {**payload, "offset": offset, "limit": limit},
            timeout=120.0,
        )[1]

    try:
        p_first = page(0, len(preview))
        p_last = page(EXPECTED_TIES - 1, 5)
        p_mid = page(1000, 7)
    except Exception as exc:  # noqa: BLE001
        check("3136-tie long-id audit: tie paging endpoint reachable", False, str(exc))
        return

    ok = (
        p_first.get("tie_count") == EXPECTED_TIES
        and p_first.get("tied") == preview
        and p_last.get("tie_count") == EXPECTED_TIES
        and len(p_last.get("tied", [])) == 1
    )
    check(
        "3136-tie long-id audit: paged windows consistent with preview",
        ok,
        f"page0={len(p_first.get('tied', []))} last={len(p_last.get('tied', []))}",
    )

    mid = p_mid.get("tied", [])
    ok = len(mid) == 7 and all(
        len(s["ids"]) == 4
        and {i[:2] for i in s["ids"]} == {"G0", "G1", "G2", "G3"}
        and [w["fraction"] for w in s["weights"]] == ["1/4"] * 4
        and s["cost"] == 4
        for s in mid
    )
    check(
        "3136-tie long-id audit: mid-window page well formed",
        ok,
        json.dumps(mid[:1])[:200],
    )

    _, bad = post(
        f"{API}/api/audit/ties",
        {**payload, "offset": -1, "limit": 0},
        timeout=120.0,
    )
    fields = {e.get("field") for e in bad.get("errors", [])}
    check(
        "3136-tie long-id audit: invalid page window rejected",
        {"offset", "limit"} <= fields,
        json.dumps(bad)[:200],
    )

    # the same payload must survive the nginx proxy path unchanged
    try:
        _, proxied = post(f"{WEB}/api/audit", payload, timeout=120.0)
        ok = (
            proxied.get("tie_count") == EXPECTED_TIES
            and len(proxied.get("tied", [])) <= TIE_PREVIEW_MAX
        )
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"       proxied mass-tie audit error: {exc}")
    check("3136-tie long-id audit: capped preview through web proxy", ok)


# ------------------------------------------------------ 6. build artefacts
def check_web_build() -> None:
    try:
        status, html = get(f"{WEB}/")
    except Exception as exc:  # noqa: BLE001
        check("web build served by nginx container", False, str(exc))
        return
    has_root = status == 200 and '<div id="root">' in html
    check("web container serves production index.html", has_root)
    # the bundled JS asset referenced from the built HTML must exist
    js = ""
    try:
        m = re.search(r'src="(/assets/[^"]+\.js)"', html)
        asset_ok = bool(m)
        if m:
            s, js = get(f"{WEB}{m.group(1)}")
            asset_ok = s == 200
        check("built JS bundle asset reachable", asset_ok,
              "no asset reference" if not m else "")
    except Exception as exc:  # noqa: BLE001
        check("built JS bundle asset reachable", False, str(exc))
        return
    # the shipped UI must page tie details on demand: the first result
    # display renders only the loaded preview, never one button per tie
    ok = "/api/audit/ties" in js and "加载更多同优解" in js
    check("web bundle pages ties on demand (no full first render)", ok)


# ---------------------------------------------------------------- 7. smoke
def check_smoke() -> None:
    try:
        s, body = get(f"{API}/health")
        direct = s == 200 and json.loads(body)["status"] == "ok"
    except Exception as exc:  # noqa: BLE001
        direct = False
        print(f"       direct health error: {exc}")
    check("API smoke: GET /health direct", direct)

    try:
        s, body = get(f"{WEB}/health")
        proxied = s == 200 and json.loads(body)["status"] == "ok"
    except Exception as exc:  # noqa: BLE001
        proxied = False
        print(f"       proxied health error: {exc}")
    check("API smoke: GET /health through web proxy", proxied)

    try:
        s, body = post(f"{WEB}/api/audit",
                       {"endmembers": SQUARE, "target": ["1", "1", "0"]})
        roundtrip = s == 200 and body.get("feasible") is True
    except Exception as exc:  # noqa: BLE001
        roundtrip = False
        print(f"       proxied audit error: {exc}")
    check("API smoke: POST /api/audit through web proxy", roundtrip)


def main() -> int:
    api_ok = wait_for(f"{API}/health", "api")
    web_ok = wait_for(f"{WEB}/healthz", "web")
    if not api_ok or not web_ok:
        return 1

    run_pytest()
    check_canonical_weights()
    check_outside_hull()
    check_classification()
    check_mass_tie_long_ids()
    check_web_build()
    check_smoke()

    print("-" * 60)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {', '.join(failures)}")
        return 1
    print("ALL VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
