import { useState } from 'react';
import { source } from '../data';
import { fmtDateUtc } from '../lib/format';
import { useJumpTargets, useManifest } from '../lib/hooks';
import { INTRO_KEY, readPref, writePref } from '../lib/prefs';
import { caseHref, href } from '../lib/useHashRoute';
import { Glyph } from './Bits';

const REPLAY = source.mode === 'replay';

/**
 * First-visit orientation: what this is in two sentences, and a way straight
 * to the interesting cases. Dismissed once, remembered per browser.
 */
export function IntroStrip({ selectedCaseId }: { selectedCaseId: string | null }) {
  const [dismissed, setDismissed] = useState(() => readPref(INTRO_KEY) === 'dismissed');
  const jumps = useJumpTargets();
  const manifest = useManifest();
  if (dismissed) return null;

  const m = manifest.data;
  const dismiss = () => {
    writePref(INTRO_KEY, 'dismissed');
    setDismissed(true);
  };

  return (
    <section className="intro" aria-label="Introduction">
      <div className="intro__text">
        <p className="intro__lead">
          <strong>FraudGraph</strong> scores every payment as it happens and decides ALLOW, REVIEW or
          BLOCK in about 15 ms. Each flagged payment becomes a case, and an AI analyst investigates it
          with every claim checked against the evidence by code.{' '}
          <a href={href('/about')}>How it works</a>
        </p>
        <p className="intro__sub">
          {REPLAY ? (
            m?.sample ? (
              <>
                You are watching a small development sample assembled from the running system, not the
                full recording. The same console also runs live against the pipeline.
              </>
            ) : (
              <>
                You are watching a recorded session of the real pipeline
                {m?.recordedAt ? <>, captured {fmtDateUtc(m.recordedAt)},</> : null} replayed at its
                original timing. The same console also runs live against the pipeline.
              </>
            )
          ) : (
            <>This console is connected to a running pipeline: the feed on the left is live.</>
          )}
        </p>
      </div>
      {jumps.targets.length > 0 ? (
        <div className="intro__jumps" role="group" aria-label="Go to an example">
          {jumps.targets.map((j) => (
            <a
              key={`${j.kind}-${j.caseId}`}
              className="jump"
              href={caseHref(j.caseId)}
              aria-current={j.caseId === selectedCaseId ? 'true' : undefined}
              title={j.title ? `${j.title}. ${j.blurb ?? ''}` : undefined}
            >
              {j.label}
              <Glyph name="arrow" />
            </a>
          ))}
        </div>
      ) : null}
      <button type="button" className="iconbtn intro__close" onClick={dismiss} aria-label="Dismiss the introduction">
        <Glyph name="close" />
      </button>
    </section>
  );
}
