export interface EndmemberRow {
  id: string;
  t0: string;
  t1: string;
  t2: string;
  cost: string;
}

export interface WeightOut {
  id: string;
  fraction: string;
  numerator: number;
  denominator: number;
  decimal: number;
}

export interface SolutionOut {
  ids: string[];
  weights: WeightOut[];
  cost: number;
}

export interface FieldError {
  field: string;
  message: string;
}

export interface AuditResponse {
  feasible: boolean;
  solution: SolutionOut | null;
  // First page of the cost-tied solutions only (server preview cap); the
  // rest are fetched on demand via /api/audit/ties.  tie_count and
  // classification always cover the complete tie set.
  tied: SolutionOut[];
  tie_count: number;
  classification: Record<string, "always" | "partial" | "never">;
  errors: FieldError[];
}

export interface AuditRequest {
  endmembers: EndmemberRow[];
  target: [string, string, string];
}

export interface TiePageResponse {
  feasible: boolean;
  tie_count: number;
  offset: number;
  limit: number;
  tied: SolutionOut[];
  errors: FieldError[];
}
