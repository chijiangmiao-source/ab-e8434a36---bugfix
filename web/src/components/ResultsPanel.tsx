import { useEffect, useState } from "react";
import type { AuditResponse, SolutionOut } from "../types";

interface ResultsProps {
  result: AuditResponse;
  selectedTie: number;
  onSelectTie: (index: number) => void;
  // Paged tie browser.  Only the current page (at most tie_page_size
  // solutions) is mounted at a time; pages are fetched lazily.
  pageStart: number;
  pageSolutions: SolutionOut[] | undefined;
  pageLoading: boolean;
  pageError: string | null;
  onGotoPage: (offset: number) => void;
  // The selected solution taken from the cached page it belongs to, or null
  // while that page is still loading.
  selectedSolution: SolutionOut | null;
}

const CLASS_LABEL: Record<string, { text: string; cls: string }> = {
  always: { text: "所有", cls: "tag always" },
  partial: { text: "部分", cls: "tag partial" },
  never: { text: "从不", cls: "tag never" },
};

export function ResultsPanel({
  result,
  selectedTie,
  onSelectTie,
  pageStart,
  pageSolutions,
  pageLoading,
  pageError,
  onGotoPage,
  selectedSolution,
}: ResultsProps) {
  const canonical = result.solution ?? undefined;
  const sol = selectedSolution ?? undefined;
  const pageSize = result.tie_page_size;
  const pageCount = Math.max(1, Math.ceil(result.tie_count / pageSize));
  const currentPage = Math.floor(pageStart / pageSize); // 0-based

  // Jump-to-page input, local text state.
  const [pageInput, setPageInput] = useState("");
  useEffect(() => setPageInput(""), [result]);

  const visibleCount = Math.min(pageSize, result.tie_count - pageStart);

  const gotoInputPage = () => {
    const n = Number(pageInput);
    if (Number.isInteger(n) && n >= 1 && n <= pageCount) {
      onGotoPage((n - 1) * pageSize);
      setPageInput("");
    }
  };

  return (
    <section className="results">
      <h2>② 最小端元解释</h2>
      {result.feasible && canonical ? (
        <>
          <p className="summary">
            正权端元 <strong>{canonical.ids.length}</strong> 个 · 复核代价和{" "}
            <strong>{canonical.cost}</strong> · 两级同优解共{" "}
            <strong>{result.tie_count}</strong> 组
          </p>

          {sol ? (
            <>
              {result.tie_count > 1 && (
                <p className="tie-caption" data-testid="tie-caption">
                  当前展示第 <strong>{selectedTie + 1}</strong> /{" "}
                  {result.tie_count} 组同优解
                  {selectedTie === 0 && <>（第 1 组为按标识字典序确定的规范解）</>}
                </p>
              )}
              <table className="weight-table">
                <thead>
                  <tr>
                    <th>端元</th>
                    <th>规范权重（精确分数）</th>
                    <th>小数</th>
                    <th>占比</th>
                    <th>归类</th>
                  </tr>
                </thead>
                <tbody>
                  {sol.weights.map((w) => {
                    const tag = CLASS_LABEL[result.classification[w.id] ?? "never"];
                    return (
                      <tr key={w.id}>
                        <td className="mono">{w.id}</td>
                        <td className="mono frac">{w.fraction}</td>
                        <td className="mono">
                          {w.decimal.toFixed(w.denominator > 1 ? 6 : 0)}
                        </td>
                        <td>
                          <div className="bar-cell">
                            <div
                              className="bar"
                              style={{ width: `${Math.max(w.decimal * 100, 1.5)}%` }}
                            />
                            <span>{(w.decimal * 100).toFixed(2)}%</span>
                          </div>
                        </td>
                        <td>
                          <span className={tag.cls}>{tag.text}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          ) : (
            <p className="tie-loading">同优解明细加载中…</p>
          )}

          {result.tie_count > 1 && (
            <div className="tie-browser">
              <div className="tie-pager">
                <span>
                  同优解 {result.tie_count} 组 · 第 {currentPage + 1}/{pageCount} 页
                  （每页 {pageSize} 组，编号选择后在上方查看明细）
                </span>
                <div className="tie-controls">
                  <button
                    type="button"
                    className="tie-step"
                    disabled={currentPage === 0 || pageLoading}
                    onClick={() => onGotoPage(pageStart - pageSize)}
                  >
                    上一页
                  </button>
                  <div className="tie-page-nums">
                    {Array.from({ length: visibleCount }, (_, k) => {
                      const globalIndex = pageStart + k;
                      const s = pageSolutions?.[k];
                      return (
                        <button
                          // Global ordinal is a stable, short key; full ids are
                          // never used as button labels here.
                          key={globalIndex}
                          type="button"
                          className={
                            globalIndex === selectedTie ? "tie-num active" : "tie-num"
                          }
                          disabled={!s || pageLoading}
                          title={s ? `查看第 ${globalIndex + 1} 组同优解` : "加载中…"}
                          onClick={() => onSelectTie(globalIndex)}
                        >
                          {globalIndex + 1}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    className="tie-step"
                    disabled={currentPage >= pageCount - 1 || pageLoading}
                    onClick={() => onGotoPage(pageStart + pageSize)}
                  >
                    下一页
                  </button>
                  <span className="tie-jump">
                    跳至第
                    <input
                      value={pageInput}
                      onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ""))}
                      onKeyDown={(e) => e.key === "Enter" && gotoInputPage()}
                      size={4}
                      aria-label="页码"
                    />
                    / {pageCount} 页
                    <button
                      type="button"
                      className="tie-step"
                      disabled={pageLoading}
                      onClick={gotoInputPage}
                    >
                      跳转
                    </button>
                  </span>
                  {pageLoading && <span className="tie-status">加载中…</span>}
                </div>
                {pageError && <span className="tie-error">{pageError}</span>}
              </div>
            </div>
          )}
        </>
      ) : (
        !result.errors.length && (
          <div className="infeasible">
            <strong>凸包外无解。</strong>
            目标点不在任一端元凸组合的覆盖范围内，不存在非负权重和为 1 的精确表示。
            已保留当前编辑内容，可调整端元示踪值或目标后重新审计。
          </div>
        )
      )}
    </section>
  );
}
