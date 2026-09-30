/**
 * Mirrors the case-service contract (port 8082) and the showcase contract
 * (docs/showcase-contract.md). Hand-written on purpose: the backend is Java and
 * Python, there is no shared schema for the REST layer, and these types are the
 * only place the contract is written down on this side.
 */

export type Verdict = 'ALLOW' | 'REVIEW' | 'BLOCK';
export type Mode = 'FULL' | 'DEGRADED';
export const VERDICTS: readonly Verdict[] = ['ALLOW', 'REVIEW', 'BLOCK'];

export const CASE_STATUSES = [
  'OPEN',
  'INVESTIGATING',
  'REPORTED',
  'CLOSED_FRAUD',
  'CLOSED_FP',
] as const;
export type CaseStatus = (typeof CASE_STATUSES)[number];

/** A tick pushed over /ws/feed — one decision, every verdict including ALLOW. */
export interface FeedTick {
  txnId: string;
  userId: string;
  verdict: Verdict;
  mode: Mode;
  mlScore: number | null;
  firedRules: string[];
  latencyMs: number;
  decidedAt: string;
  caseId: string | null;
}

export interface Signal {
  code: string;
  severity: number;
  evidence: Record<string, unknown>;
}

export interface Contribution {
  feature: string;
  shap: number;
}

/** The full fraud.decisions event, stored verbatim as cases.decision_doc. */
export interface DecisionDoc {
  txnId: string;
  userId: string;
  verdict: Verdict;
  mode: Mode;
  mlScore: number | null;
  firedRules: string[];
  signals: Signal[];
  features: Record<string, number | string | boolean | null>;
  contributions: Contribution[];
  latencyMs: number;
  decidedAt: string;
  merchantId?: string;
  merchantCategory?: string;
}

export interface CaseSummary {
  caseId: string;
  txnId: string;
  userId: string;
  verdict: 'REVIEW' | 'BLOCK';
  mlScore: number | null;
  status: CaseStatus;
  firedRules: string[];
  createdAt: string;
  updatedAt: string;
}

export interface CaseEvent {
  eventType: string;
  payload: Record<string, unknown> | null;
  at: string;
}

/**
 * The analyst agent's output (LLD §6.2). Null while the agent has not run, is
 * disabled, or failed.
 *
 * Every field is optional on purpose. The body of this document is written by
 * an LLM and passes through the agent and the case service before it gets
 * here, so the shape below is the contract, not a guarantee. Do not read it
 * directly in a component — run it through `normalizeReport` in
 * `lib/report.ts`, which makes every field total.
 */
export type FraudType = 'RING' | 'VELOCITY' | 'GEO' | 'MIXED' | 'UNCERTAIN';
export type RecommendedAction = 'CONFIRM_BLOCK' | 'RELEASE' | 'ESCALATE';

/**
 * One read-only tool call the agent made, and its outcome. Exactly one of
 * `payload` (the result, arbitrary JSON) or `error` is meaningful: an entry
 * with `error` carries no data and must never be cited — the verify node
 * rejects a claim that cites one.
 */
export interface EvidenceEntry {
  index?: number;
  tool?: string;
  args?: Record<string, unknown> | null;
  payload?: unknown;
  error?: string | null;
}

/** A claim, plus the `evidence[]` indices that are supposed to support it. */
export interface Finding {
  claim?: string;
  evidence_refs?: number[];
}

export type ViolationKind = 'no_refs' | 'bad_ref' | 'uncited_number' | 'failed_tool_ref';

/**
 * One citation check the verify node failed. `finding_index` is -1 when the
 * failure was not tied to a specific claim (no report was produced at all).
 * The list is the union across attempts, so an index may not correspond to a
 * finding still present in `findings[]` — an escalated report has its
 * unsupported findings removed.
 */
export interface Violation {
  finding_index?: number;
  kind?: ViolationKind | string;
  detail?: string;
}

/**
 * The programmatic citation check — the point of the whole feature. When
 * `passed` is false the report is generally UNCERTAIN / 0.0 / ESCALATE with a
 * reduced or empty `findings`, and `violations` is why.
 */
export interface Verification {
  passed?: boolean;
  attempts?: number;
  violations?: Violation[];
  toolCallsUsed?: number;
  evidenceCount?: number;
}

export interface ReportDoc {
  summary?: string;
  fraud_type?: FraudType | string;
  confidence?: number;
  findings?: Finding[];
  recommended_action?: RecommendedAction | string;
  evidence?: EvidenceEntry[];
  verification?: Verification | null;
}

export interface CaseDetail extends CaseSummary {
  decisionDoc: DecisionDoc;
  reportDoc: ReportDoc | null;
  events: CaseEvent[];
}

export interface CasePage {
  items: CaseSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface Stats {
  byStatus: Partial<Record<CaseStatus, number>>;
  total: number;
  last1h: { cases: number; block: number; review: number };
}

export interface RecentDecision {
  txnId: string;
  userId: string;
  verdict: Verdict;
  mode: Mode;
  mlScore: number | null;
  firedRules: string[];
  decidedAt: string;
  latencyMs?: number;
  caseId?: string | null;
}

export interface UserHistory {
  userId: string;
  hours?: number;
  profile: { n: number; mean: number; std: number } | null;
  windows: {
    cnt1m: number;
    sum1m: number;
    cnt5m: number;
    sum5m: number;
    cnt1h: number;
    sum1h: number;
  } | null;
  /** Newest-first, may be empty. */
  recent: RecentDecision[];
}

export interface GraphNode {
  id: string;
  degree: number;
  /** Hop distance from the queried user, when the engine sends it. */
  depth?: number;
}

export interface GraphEdge {
  src: string;
  dst: string;
  amount: number;
  /** ISO time. Older engines send this; current ones send `tsMs`. */
  ts?: string;
  /** Epoch milliseconds. */
  tsMs?: number;
  /** How many hops of pass-through this transfer continued: 0 for ordinary money. */
  chainDepth?: number;
}

export interface Neighborhood {
  userId: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Cycles the queried user sits on, each a node list that starts and ends on that user. */
  cycles?: string[][];
  componentSize: number;
  depth: number;
}

/* ---------- showcase contract (docs/showcase-contract.md §2–§4) ---------- */

export interface AnswerSentence {
  text: string;
  refs: number[];
  verified: boolean;
}

export interface RemovedClaim {
  text: string;
  reason: string;
}

export interface AskStep {
  kind: 'evidence' | 'tool' | 'draft' | 'verify';
  label: string;
  detail?: string;
  ms?: number;
}

/**
 * POST /agent/cases/{caseId}/ask. `answer[i].refs` index into this response's
 * own `evidence`, never the case report's, and `evidence[i].index === i`.
 */
export interface AskResponse {
  caseId: string;
  question: string;
  answer: AnswerSentence[];
  removed: RemovedClaim[];
  evidence: EvidenceEntry[];
  steps: AskStep[];
  verification: Verification;
  model: string;
  latencyMs: number;
  mode: 'live' | 'replay';
  /** True when the server answered from its answer cache (same question, same case, within the hour). */
  cached?: boolean;
  /** Not in the contract: agent/ask.py adds it when it could not load the case. */
  note?: string;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface FeaturedCase {
  caseId: string;
  /** RING | GEO | VELOCITY | POLICY; anything else is shown by its title alone. */
  pattern: string;
  title: string;
  blurb: string;
}

export interface ShowcaseManifest {
  recordedAt: string;
  durationMs: number;
  tps: number;
  scorerModel: string;
  agentModel: string;
  stats: Stats;
  featured: FeaturedCase[];
  /** Set by scripts/snapshot-sample.mjs. A real recording omits it. */
  sample?: boolean;
}

/** feed.json: every tick with `at`, ms since the recording started, ascending. */
export type ReplayTick = FeedTick & { at: number };
export interface ReplayFeed {
  ticks: ReplayTick[];
}

/** ask/{caseId}.json: one recorded answer per recorded question. */
export interface ReplayAnswers {
  answers: AskResponse[];
}

/** GET /agent/health */
export interface AgentHealth {
  status: 'UP' | 'NO_MODEL' | string;
  model?: string;
  provider?: string;
}
