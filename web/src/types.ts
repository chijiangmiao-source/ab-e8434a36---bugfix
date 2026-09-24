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
  // Only the first page of tied solutions; tie_count is the exact total.
  tied: SolutionOut[];
  tie_count: number;
  tie_offset: number;
  tie_page_size: number;
  classification: Record<string, "always" | "partial" | "never">;
  errors: FieldError[];
}

export interface TiePageOut {
  offset: number;
  tie_count: number;
  solutions: SolutionOut[];
  errors: FieldError[];
}

export interface AuditRequest {
  endmembers: EndmemberRow[];
  target: [string, string, string];
}
