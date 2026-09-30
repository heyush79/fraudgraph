import type { AskResponse, CaseDetail, Neighborhood, UserHistory } from '../lib/types';

export function buildFixtureAnswer(input: {
  detail: CaseDetail;
  history?: UserHistory | null;
  graph?: Neighborhood | null;
  question: string;
  mode?: 'live' | 'replay';
  model?: string;
}): AskResponse;
