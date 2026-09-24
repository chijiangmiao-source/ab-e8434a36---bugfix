import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Editor } from "./components/Editor";
import { Projection, type PlotPoint } from "./components/Projection";
import { ResultsPanel } from "./components/ResultsPanel";
import { fetchHealth, fetchTies, runAudit } from "./api";
import { DEFAULT_ENDMEMBERS, DEFAULT_TARGET } from "./defaults";
import type { AuditRequest, AuditResponse, EndmemberRow, SolutionOut } from "./types";
import "./styles.css";

export default function App() {
  const [endmembers, setEndmembers] = useState<EndmemberRow[]>(DEFAULT_ENDMEMBERS);
  const [target, setTarget] = useState<[string, string, string]>(DEFAULT_TARGET);
  const [result, setResult] = useState<AuditResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTie, setSelectedTie] = useState(0);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [health, setHealth] = useState<boolean | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);

  // Paged tie browser: only one page (at most tie_page_size solutions) is
  // held per offset, and pages are fetched lazily.  The full tie set is
  // never materialised in the browser.
  const [tiePages, setTiePages] = useState<Map<number, SolutionOut[]>>(new Map());
  const [pageStart, setPageStart] = useState(0);
  const [pageLoading, setPageLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  // The exact request that produced `result`; tie pages must be paged over
  // the same input even if the editor changed afterwards.
  const resultRequest = useRef<AuditRequest | null>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    let alive = true;
    const ping = async () => setHealth(await fetchHealth());
    ping();
    const t = setInterval(() => alive && ping(), 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const errorsByField = useMemo(() => {
    const m = new Map<string, string>();
    if (result) {
      for (const e of result.errors) {
        if (!m.has(e.field)) m.set(e.field, e.message);
      }
    }
    return m;
  }, [result]);

  const batchError = useMemo(() => {
    const e = errorsByField.get("endmembers") ?? errorsByField.get("target");
    return e;
  }, [errorsByField]);

  const audit = useCallback(async () => {
    setLoading(true);
    setNetworkError(null);
    const req: AuditRequest = { endmembers, target };
    const seq = ++requestSeq.current;
    try {
      const res = await runAudit(req);
      if (seq !== requestSeq.current) return;
      resultRequest.current = req;
      setResult(res);
      setSelectedTie(0);
      // The first audit response inlines exactly the first tie page; seed
      // the cache with it instead of re-requesting, and never with more.
      setTiePages(res.tied.length ? new Map([[0, res.tied]]) : new Map());
      setPageStart(0);
      setPageError(null);
      setPageLoading(false);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setNetworkError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [endmembers, target]);

  // Lazily fetch one page of tied solutions; first page comes from the
  // initial audit response and is never fetched twice.
  const loadPage = useCallback(async (offset: number) => {
    const req = resultRequest.current;
    if (!result || !req) return;
    if (offset === 0 && tiePages.has(0)) {
      setPageStart(0);
      return;
    }
    if (tiePages.has(offset)) {
      setPageStart(offset);
      return;
    }
    const seq = ++requestSeq.current;
    setPageLoading(true);
    setPageError(null);
    try {
      const page = await fetchTies(req, offset, result.tie_page_size);
      if (seq !== requestSeq.current) return;
      if (page.errors.length) {
        setPageError(page.errors.map((e) => e.message).join("；"));
        return;
      }
      setTiePages((prev) => {
        const next = new Map(prev);
        next.set(offset, page.solutions);
        return next;
      });
      setPageStart(offset);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === requestSeq.current) setPageLoading(false);
    }
  }, [result, tiePages]);

  // Pager navigation moves the selection to the first solution of the page;
  // plain selection (numbered buttons) keeps its index and lazy-loads its
  // page when necessary.
  const gotoPage = useCallback((offset: number) => {
    setSelectedTie(offset);
    void loadPage(offset);
  }, [loadPage]);

  const addRow = () => {
    if (endmembers.length >= 30) return;
    const nextId = nextFreeId(endmembers.map((r) => r.id));
    setEndmembers([
      ...endmembers,
      { id: nextId, t0: "0", t1: "0", t2: "0", cost: "1" },
    ]);
  };

  const removeRow = (i: number) => {
    if (endmembers.length <= 3) return;
    setEndmembers(endmembers.filter((_, idx) => idx !== i));
  };

  // ---- projection geometry -------------------------------------------------
  // The selected tie lives on a lazily-fetched page; null while loading.
  const selectedSolution: SolutionOut | null = useMemo(() => {
    if (!result?.feasible) return null;
    const pageSize = result.tie_page_size;
    const offset = Math.floor(selectedTie / pageSize) * pageSize;
    const page = tiePages.get(offset);
    return page ? page[selectedTie - offset] ?? null : null;
  }, [result, selectedTie, tiePages]);

  const activeSolution = selectedSolution;

  const weightById = useMemo(() => {
    const m = new Map<string, number>();
    if (activeSolution) {
      for (const w of activeSolution.weights) m.set(w.id, w.decimal);
    }
    return m;
  }, [activeSolution]);

  const supportEdges = useMemo<[string, string][]>(() => {
    if (!activeSolution) return [];
    const ids = activeSolution.ids;
    const edges: [string, string][] = [];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) edges.push([ids[i], ids[j]]);
    }
    return edges;
  }, [activeSolution]);

  const plotPoints = useMemo<PlotPoint[]>(() => {
    return endmembers
      .map((r): PlotPoint | null => {
        const xyz: [number, number, number] = [
          Number(r.t0),
          Number(r.t1),
          Number(r.t2),
        ];
        if (xyz.some((v) => !Number.isFinite(v))) return null;
        const inSolution = weightById.has(r.id);
        return {
          id: r.id,
          xyz,
          weight: weightById.get(r.id) ?? 0,
          klass: result?.classification[r.id] ?? null,
          inSolution,
        };
      })
      .filter((p): p is PlotPoint => p !== null);
  }, [endmembers, weightById, result]);

  const targetXYZ = useMemo<[number, number, number] | null>(() => {
    const v = target.map(Number) as [number, number, number];
    return v.every((x) => Number.isFinite(x)) ? v : null;
  }, [target]);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>火山灰喷发端元混合审计</h1>
          <p className="subtitle">
            精确有理数最小支撑凸组合 · 先最少化正权端元数，再最小化复核代价和
          </p>
        </div>
        <span className={health === null ? "health unknown" : health ? "health ok" : "health down"}>
          API {health === null ? "检测中" : health ? "在线" : "离线"}
        </span>
      </header>

      {networkError && <div className="network-error">{networkError}</div>}

      <Editor
        endmembers={endmembers}
        target={target}
        errorsByField={errorsByField}
        onChange={setEndmembers}
        onTargetChange={setTarget}
        onAudit={audit}
        onAdd={addRow}
        onRemove={removeRow}
        loading={loading}
        batchError={batchError}
      />

      {result && (
        <ResultsPanel
          result={result}
          selectedTie={selectedTie}
          onSelectTie={setSelectedTie}
          pageStart={pageStart}
          pageSolutions={tiePages.get(pageStart)}
          pageLoading={pageLoading}
          pageError={pageError}
          onGotoPage={gotoPage}
          selectedSolution={selectedSolution}
        />
      )}

      <section className="projections">
        <h2>③ 联动投影（悬停任意图中的端元可同步高亮）</h2>
        <div className="legend">
          <span><i className="sw always" /> 所有同优解均出现</span>
          <span><i className="sw partial" /> 部分同优解出现</span>
          <span><i className="sw never" /> 从不出现</span>
          <span><i className="sw target" /> 目标点</span>
        </div>
        <div className="projection-grid">
          <Projection
            title="投影 A：示踪值 1 × 示踪值 2（XY）"
            axisLabels={["X", "Y"]}
            project={(p) => [p[0], p[1]]}
            points={plotPoints}
            target={targetXYZ}
            supportEdges={supportEdges}
            hoverId={hoverId}
            onHover={setHoverId}
          />
          <Projection
            title="投影 B：示踪值 1 × 示踪值 3（XZ）"
            axisLabels={["X", "Z"]}
            project={(p) => [p[0], p[2]]}
            points={plotPoints}
            target={targetXYZ}
            supportEdges={supportEdges}
            hoverId={hoverId}
            onHover={setHoverId}
          />
        </div>
      </section>

      <footer>
        点半径∝权重；点颜色表示该端元在前两级同优解（最少端元数且最小代价）中的出现情况。
      </footer>
    </div>
  );
}

function nextFreeId(used: string[]): string {
  const have = new Set(used);
  for (let n = 1; n <= 30; n++) {
    const id = `E${n}`;
    if (!have.has(id)) return id;
  }
  return `E${Date.now()}`;
}
