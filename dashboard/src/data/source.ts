import type { DataMode } from '../config';
import type {
  AskResponse,
  CaseDetail,
  CasePage,
  CaseStatus,
  ChatTurn,
  FeedTick,
  Neighborhood,
  ShowcaseManifest,
  Stats,
  UserHistory,
} from '../lib/types';

/**
 * Everything the console reads, behind one interface with two implementations:
 * `live` (case service over HTTP + WebSocket, agent over HTTP) and `replay`
 * (static files under <base>/showcase/). Views never know which one they have;
 * the few places that behave differently ask `mode`, and the contract for
 * what differs is docs/showcase-contract.md.
 */
export interface DataSource {
  readonly mode: DataMode;

  /** The decision stream. Live: WS /ws/feed. Replay: feed.json at its recorded timing, looped. */
  connectFeed(sink: FeedSink): FeedConnection;

  stats(signal?: AbortSignal): Promise<Stats>;
  cases(query: CaseQuery, signal?: AbortSignal): Promise<CasePage>;
  caseDetail(caseId: string, signal?: AbortSignal): Promise<CaseDetail>;
  /** The account's last 24 h: rolling amount profile, 1m/5m/1h windows, recent decisions. */
  userHistory(userId: string, signal?: AbortSignal): Promise<UserHistory>;
  /** P2P neighbourhood of the account, depth 2. */
  neighborhood(userId: string, signal?: AbortSignal): Promise<Neighborhood>;
  /** PATCH /cases/{id}/status. Rejects in replay; the UI hides the control when READ_ONLY. */
  setStatus(caseId: string, status: CaseStatus): Promise<CaseDetail>;

  /** The recording's manifest. Null in live mode. */
  manifest(signal?: AbortSignal): Promise<ShowcaseManifest | null>;
  /** Case ids that open a detail view. Null means every id does (live). */
  openableCases(signal?: AbortSignal): Promise<ReadonlySet<string> | null>;

  /** Whether the chat can take questions at all. */
  agentStatus(signal?: AbortSignal): Promise<AgentStatus>;
  /** The questions the chat can answer for a case. Null means any question (live). */
  recordedQuestions(caseId: string, signal?: AbortSignal): Promise<string[] | null>;
  /** Rejects with AskError (lib/api.ts), whose `kind` says what the UI should tell the reader. */
  ask(caseId: string, question: string, history: ChatTurn[]): Promise<AskResponse>;
}

export type FeedState = 'connecting' | 'open' | 'closed';

export interface FeedSink {
  /** Ticks in decision order (oldest first). `backfill` marks the history a live server sends on connect. */
  batch(ticks: FeedTick[], backfill: boolean): void;
  state(state: FeedState, attempt: number, error: string | null): void;
  /** Replay only: the recording looped, so what is on screen is about to repeat. */
  reset(): void;
}

export interface FeedConnection {
  close(): void;
  /** Live: skip the backoff and reconnect now. Replay: no-op. */
  retry(): void;
}

export interface CaseQuery {
  status?: CaseStatus | '';
  limit: number;
  offset: number;
}

export type AgentStatus =
  | { state: 'up'; model: string | null; provider: string | null; fixture: boolean }
  | { state: 'down'; reason: 'no_model' | 'unreachable' };
