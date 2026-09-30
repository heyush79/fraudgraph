import { useSyncExternalStore } from 'react';
import type { DataSource } from '../data';
import { AskError } from './api';
import type { AskResponse, ChatTurn } from './types';

/**
 * Chat history, per case, for as long as the page is open. Module-level so a
 * conversation survives switching cases, visiting About, or the chat drawer
 * closing. Nothing is persisted: a reload starts clean.
 */

export interface ChatEntry {
  id: number;
  question: string;
  askedAt: number;
  status: 'pending' | 'done' | 'error';
  response: AskResponse | null;
  error: AskError | null;
}

const EMPTY: readonly ChatEntry[] = [];
/** The ask endpoint reads at most the last six turns (contract §2). */
const HISTORY_TURNS = 6;
/** The endpoint rejects a turn longer than this (agent/server.py ChatTurn). */
const TURN_CHARS = 4_000;
/** When a 429 carries no usable Retry-After. */
const DEFAULT_COOLDOWN_S = 30;

class ChatStore {
  private byCase = new Map<string, readonly ChatEntry[]>();
  private subs = new Set<() => void>();
  private cooldownUntil = 0;
  private noAsk = false;
  private seq = 0;

  subscribe = (cb: () => void) => {
    this.subs.add(cb);
    return () => {
      this.subs.delete(cb);
    };
  };

  entries(caseId: string | null): readonly ChatEntry[] {
    return (caseId && this.byCase.get(caseId)) || EMPTY;
  }

  /** Epoch ms until which the rate limit applies. It is per visitor, so it spans every case. */
  cooldown = (): number => this.cooldownUntil;

  /** True once the agent has shown it has no ask endpoint; asking again cannot help. */
  unsupported = (): boolean => this.noAsk;

  /** One question at a time per case; answers land in their case even if the reader has moved on. */
  ask(source: DataSource, caseId: string, question: string): void {
    const q = question.trim();
    if (!q) return;
    const prior = this.entries(caseId);
    if (prior.some((e) => e.status === 'pending')) return;
    const entry: ChatEntry = {
      id: ++this.seq,
      question: q,
      askedAt: Date.now(),
      status: 'pending',
      response: null,
      error: null,
    };
    this.put(caseId, [...prior, entry]);
    source.ask(caseId, q, historyOf(prior)).then(
      (response) => this.settle(caseId, entry.id, { status: 'done', response }),
      (err: unknown) => {
        const error =
          err instanceof AskError
            ? err
            : new AskError('failed', 0, err instanceof Error ? err.message : String(err));
        if (error.kind === 'rate_limited') {
          this.cooldownUntil = Date.now() + (error.retryAfterSecs ?? DEFAULT_COOLDOWN_S) * 1_000;
        }
        if (error.kind === 'unsupported') this.noAsk = true;
        this.settle(caseId, entry.id, { status: 'error', error });
      },
    );
  }

  private settle(caseId: string, id: number, patch: Partial<ChatEntry>): void {
    this.put(
      caseId,
      this.entries(caseId).map((e) => (e.id === id ? { ...e, ...patch } : e)),
    );
  }

  private put(caseId: string, list: readonly ChatEntry[]): void {
    this.byCase.set(caseId, list);
    this.subs.forEach((cb) => cb());
  }
}

/** The conversation so far, as the endpoint wants it: answered turns only, oldest first. */
function historyOf(entries: readonly ChatEntry[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const e of entries) {
    if (e.status !== 'done' || !e.response) continue;
    const said = e.response.answer.map((s) => s.text).join(' ');
    turns.push({ role: 'user', content: e.question.slice(0, TURN_CHARS) });
    turns.push({
      role: 'assistant',
      content: (said || 'I could not produce a supportable answer.').slice(0, TURN_CHARS),
    });
  }
  return turns.slice(-HISTORY_TURNS);
}

export const chatStore = new ChatStore();

export function useChat(caseId: string | null): readonly ChatEntry[] {
  return useSyncExternalStore(chatStore.subscribe, () => chatStore.entries(caseId));
}

export function useCooldownUntil(): number {
  return useSyncExternalStore(chatStore.subscribe, chatStore.cooldown);
}

export function useAskUnsupported(): boolean {
  return useSyncExternalStore(chatStore.subscribe, chatStore.unsupported);
}
