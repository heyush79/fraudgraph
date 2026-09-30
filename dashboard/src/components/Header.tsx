import { source } from '../data';
import { feedStore, usePulse } from '../lib/feedStore';
import { fmtDateUtc, fmtInt, isNum } from '../lib/format';
import { useManifest } from '../lib/hooks';
import { useTheme } from '../lib/prefs';
import type { Route } from '../lib/useHashRoute';
import { href } from '../lib/useHashRoute';
import { VERDICTS } from '../lib/types';
import { Glyph } from './Bits';

const REPLAY = source.mode === 'replay';

/**
 * Product name, what this deployment is (LIVE or REPLAY), and the pipeline's
 * vital signs. Throughput and latency are computed here, in the browser, from
 * the ticks themselves — the same way in both modes, so the numbers mean the
 * same thing whether the stream is live or recorded.
 */
export function Header({ route }: { route: Route['name'] }) {
  const pulse = usePulse();
  const manifest = useManifest();
  const [theme, toggleTheme] = useTheme();

  return (
    <header className="topbar">
      <a className="brand" href={href('/')} aria-label="FraudGraph console">
        <BrandMark />
        <span className="brand__name">FraudGraph</span>
      </a>

      <ModeBadge
        conn={pulse.conn}
        attempt={pulse.attempt}
        recordedAt={manifest.data?.recordedAt ?? null}
        sample={Boolean(manifest.data?.sample)}
      />

      <dl className="kpis" aria-label="Pipeline, measured in this browser">
        <Kpi
          label="Decisions/s"
          value={isNum(pulse.tps) ? pulse.tps.toFixed(pulse.tps < 100 ? 1 : 0) : '—'}
          title="Decisions per second over the last 10 s, counted from the feed"
        />
        <Kpi
          label="p50"
          value={isNum(pulse.p50) ? `${fmtInt(pulse.p50)} ms` : '—'}
          title={`Median decision latency, payment timestamp to verdict, last 30 s (${fmtInt(pulse.samples)} decisions)`}
        />
        <Kpi
          label="p99"
          value={isNum(pulse.p99) ? `${fmtInt(pulse.p99)} ms` : '—'}
          title={`99th percentile decision latency, last 30 s (${fmtInt(pulse.samples)} decisions)`}
        />
        <span className="kpis__sep" aria-hidden="true" />
        {VERDICTS.map((v) => (
          <Kpi
            key={v}
            label={v}
            value={fmtInt(pulse.counts[v])}
            tone={v.toLowerCase()}
            title={`${v} decisions since this page opened`}
          />
        ))}
      </dl>

      <nav className="nav" aria-label="Pages">
        <a className="nav__item" href={href('/')} aria-current={route === 'console' ? 'page' : undefined}>
          Console
        </a>
        <a className="nav__item" href={href('/cases')} aria-current={route === 'cases' ? 'page' : undefined}>
          Cases
        </a>
        <a className="nav__item" href={href('/about')} aria-current={route === 'about' ? 'page' : undefined}>
          About
        </a>
      </nav>

      <button
        type="button"
        className="iconbtn"
        onClick={toggleTheme}
        aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
        title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
      >
        <Glyph name={theme === 'dark' ? 'sun' : 'moon'} />
      </button>
    </header>
  );
}

function ModeBadge({
  conn,
  attempt,
  recordedAt,
  sample,
}: {
  conn: string;
  attempt: number;
  recordedAt: string | null;
  sample: boolean;
}) {
  if (REPLAY) {
    return (
      <span
        className="mode mode--replay"
        title={`${sample ? 'Development sample. ' : ''}Replaying a recorded session of the real pipeline${recordedAt ? `, recorded ${fmtDateUtc(recordedAt)}` : ''}, at its original timing.`}
      >
        <span className="mode__dot" aria-hidden="true" />
        {sample ? 'REPLAY · SAMPLE' : 'REPLAY'}
      </span>
    );
  }
  const label = conn === 'open' ? 'LIVE' : conn === 'connecting' ? 'CONNECTING' : 'OFFLINE';
  return (
    <button
      type="button"
      className={`mode mode--${conn}`}
      onClick={() => feedStore.retry()}
      title={
        conn === 'open'
          ? 'Connected to the running pipeline over a WebSocket. Click to reconnect.'
          : `Not connected${attempt ? ` (retry ${attempt})` : ''}. Click to retry now.`
      }
    >
      <span className="mode__dot" aria-hidden="true" />
      {label}
    </button>
  );
}

function Kpi({ label, value, title, tone }: { label: string; value: string; title: string; tone?: string }) {
  return (
    <div className={tone ? `kpi kpi--${tone}` : 'kpi'} title={title}>
      <dt className="kpi__label">{label}</dt>
      <dd className="kpi__value">{value}</dd>
    </div>
  );
}

/** Three accounts and the transfer that closes the loop between them. */
export function BrandMark() {
  return (
    <svg className="brand__mark" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M10 3.2 16.2 14.6H3.8Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <circle cx="10" cy="3.2" r="2.3" className="brand__node" />
      <circle cx="16.2" cy="14.6" r="2.3" className="brand__node" />
      <circle cx="3.8" cy="14.6" r="2.3" className="brand__node brand__node--hot" />
    </svg>
  );
}
