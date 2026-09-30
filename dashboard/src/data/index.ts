import { createLiveSource } from './live';
import { createReplaySource } from './replay';
import type { DataSource } from './source';

export type { AgentStatus, DataSource, FeedState } from './source';

/**
 * The one data source for this build, chosen by VITE_DATA_MODE at build time.
 * Compared against import.meta.env directly so the bundler can drop the
 * implementation the build does not use.
 */
export const source: DataSource =
  import.meta.env.VITE_DATA_MODE === 'replay' ? createReplaySource() : createLiveSource();
