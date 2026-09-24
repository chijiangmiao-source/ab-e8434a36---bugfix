#!/usr/bin/env python3
"""One-shot verification service.

Runs every required audit and exits non-zero on the first failed group:

  1. backend code tests (pytest)
  2. canonical rational weights (exact fraction strings)
  3. outside-convex-hull infeasibility
  4. tie classification (always / partial / never)
  5. build artefacts (web container serves the production bundle)
  6. API smoke (direct + through the web proxy)

Usage:  verify.py [api_base] [web_base]
"""

from __future__ import annotations

import json
import math
import os
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


def post_raw(url: str, payload: dict, timeout: float = 30.0):
    """POST returning the unparsed body so its exact size can be checked."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return r.status, raw, len(data)


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


# ------------------------------------------------------ 5. build artefacts
def check_web_build() -> None:
    try:
        status, html = get(f"{WEB}/")
    except Exception as exc:  # noqa: BLE001
        check("web build served by nginx container", False, str(exc))
        return
    has_root = status == 200 and '<div id="root">' in html
    check("web container serves production index.html", has_root)
    # the bundled JS asset referenced from the built HTML must exist
    try:
        import re

        m = re.search(r'src="(/assets/[^"]+\.js)"', html)
        asset_ok = bool(m)
        if m:
            s, _ = get(f"{WEB}{m.group(1)}")
            asset_ok = s == 200
        check("built JS bundle asset reachable", asset_ok,
              "no asset reference" if not m else "")
    except Exception as exc:  # noqa: BLE001
        check("built JS bundle asset reachable", False, str(exc))


# ---------------------------------------------------------------- 6. smoke
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


# -------------------------------- 7. large tie set with long identifiers
def _long_id_payload():
    """30 endmembers (~1000-char unique ASCII ids) in four tetrahedron
    groups of 7/7/8/8; target (1,1,1) forces one endmember from each group,
    so the first-two-level tie set is exactly 7*7*8*8 = 3136."""
    origins = [(0, 0, 0), (4, 0, 0), (0, 4, 0), (0, 0, 4)]
    counts = (7, 7, 8, 8)
    ems = []
    for g, (origin, n) in enumerate(zip(origins, counts)):
        for k in range(n):
            stem = f"G{g}E{k:02d}-"
            ems.append({
                "id": stem + "x" * (1000 - len(stem)),
                "t0": str(origin[0]), "t1": str(origin[1]),
                "t2": str(origin[2]), "cost": "1",
            })
    return {"endmembers": ems, "target": ["1", "1", "1"]}


def check_large_tie_paging() -> None:
    payload = _long_id_payload()

    # Submitted over the Compose network through the web proxy, exactly like
    # the reported failure; the complete response is read and measured.
    try:
        status, raw, req_size = post_raw(f"{WEB}/api/audit", payload)
        body = json.loads(raw.decode())
    except Exception as exc:  # noqa: BLE001
        check("3136 long-id ties: first audit response", False, str(exc))
        return

    page_size = body.get("tie_page_size")
    ok = (
        status == 200
        and body.get("feasible") is True
        and body.get("tie_count") == 3136
        and page_size == 20
        and len(body.get("tied", [])) == 20
        and body.get("tie_offset") == 0
    )
    check(
        "3136 long-id ties: tie_count exact, only one page inlined",
        ok,
        json.dumps({k: body.get(k) for k in
                    ("feasible", "tie_count", "tie_offset", "tie_page_size")})
        + f" inlined={len(body.get('tied', []))}",
    )

    # Response/request size ratio used to be ~831x (26.2 MB vs 33 KB); with
    # one page inlined it must stay a small single-digit-ish multiple and in
    # any case far below the megabytes a full expansion needs.
    ratio = len(raw) / req_size
    size_ok = req_size < 100_000 and len(raw) < 500_000 and ratio < 20
    check(
        f"first response compact (req {req_size} B, resp {len(raw)} B, {ratio:.1f}x)",
        size_ok,
        f"req={req_size} resp={len(raw)} ratio={ratio:.1f}",
    )

    # Canonical solution and exact weights survive the display limit.
    sol = body.get("solution") or {}
    weights = sol.get("weights", [])
    canon_ok = (
        [w["id"][:5] for w in weights] == ["G0E00", "G1E00", "G2E00", "G3E00"]
        and len(weights) == 4
        and all(w["fraction"] == "1/4" and (w["numerator"], w["denominator"]) == (1, 4)
                for w in weights)
    )
    check("canonical solution with exact 1/4 weights preserved", canon_ok,
          json.dumps([(w["id"][:5], w["fraction"]) for w in weights]))

    # Classification still spans every endmember and is derived from the
    # complete 3136-solution tie set: every member is in some but not all.
    cls = body.get("classification", {})
    cls_ok = len(cls) == 30 and all(v == "partial" for v in cls.values())
    check("classification covers all 30 endmembers as partial", cls_ok,
          f"{len(cls)} classes, values={set(cls.values())}")

    # Walk every page through the proxy and reconstruct the canonical-order
    # enumeration; this is how users still reach any required tie detail.
    combos: list[tuple[str, ...]] = []
    pages_ok = True
    page_detail = ""
    expected_counts = {}
    for g, n in enumerate((7, 7, 8, 8)):
        for k in range(n):
            # ties containing one fixed member = product of the other groups
            others = [m for h, m in enumerate((7, 7, 8, 8)) if h != g]
            expected_counts[f"G{g}E{k:02d}"] = math.prod(others)
    try:
        for offset in range(0, 3136, page_size):
            _, pbody = post(
                f"{WEB}/api/audit/ties",
                {**payload, "offset": offset, "limit": page_size},
                timeout=30.0,
            )
            if pbody.get("tie_count") != 3136 or pbody.get("offset") != offset:
                pages_ok = False
                page_detail = f"bad page header at offset {offset}"
                break
            sols = pbody.get("solutions", [])
            if len(sols) != min(page_size, 3136 - offset):
                pages_ok = False
                page_detail = f"bad page size at offset {offset}: {len(sols)}"
                break
            for s in sols:
                ids = tuple(s["ids"])
                combos.append(ids)
                if [i[:2] for i in ids] != ["G0", "G1", "G2", "G3"]:
                    pages_ok = False
                    page_detail = f"group mix wrong at {offset}"
                if not all(w["fraction"] == "1/4" for w in s["weights"]):
                    pages_ok = False
                    page_detail = f"weight not 1/4 at {offset}"
    except Exception as exc:  # noqa: BLE001
        pages_ok = False
        page_detail = str(exc)

    enumeration_ok = (
        pages_ok
        and len(combos) == 3136
        and len(set(combos)) == 3136       # all distinct
        and combos == sorted(combos)       # canonical lexicographic order
    )
    check("all 3136 ties reachable page-by-page, ordered, exact 1/4 weights",
          enumeration_ok, page_detail or f"reconstructed={len(combos)}")

    # The first-response classification must agree with the full enumeration:
    # per-member occurrence counts are exactly the products of other groups.
    counts: dict[str, int] = {}
    for ids in combos:
        for i in ids:
            prefix = i[:5]
            counts[prefix] = counts.get(prefix, 0) + 1
    counts_ok = counts == expected_counts
    check("full-enumeration membership counts match the all-partial classes",
          counts_ok,
          "" if counts_ok else json.dumps(counts)[:300])

    # First UI render must not mount 3136 buttons: the production bundle must
    # drive the numbered, page-sized lazy browser instead of mapping over the
    # whole tie list with full joined ids as labels.
    try:
        import re

        _, html = get(f"{WEB}/")
        m = re.search(r'src="(/assets/[^"]+\.js)"', html)
        bundle = get(f"{WEB}{m.group(1)}")[1] if m else ""
        bundle_ok = bool(m) and "audit/ties" in bundle and "tie-num" in bundle
        check("built UI uses numbered lazy tie browser (/api/audit/ties)",
              bundle_ok, "markers missing from bundle" if not bundle_ok else "")
    except Exception as exc:  # noqa: BLE001
        check("built UI uses numbered lazy tie browser (/api/audit/ties)",
              False, str(exc))


def main() -> int:
    api_ok = wait_for(f"{API}/health", "api")
    web_ok = wait_for(f"{WEB}/healthz", "web")
    if not api_ok or not web_ok:
        return 1

    run_pytest()
    check_canonical_weights()
    check_outside_hull()
    check_classification()
    check_web_build()
    check_smoke()
    check_large_tie_paging()

    print("-" * 60)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {', '.join(failures)}")
        return 1
    print("ALL VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
