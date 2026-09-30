/**
 * The pipeline, hand-drawn as inline SVG. Every colour is a token (set through
 * CSS classes), so the diagram follows the theme. Below ~760 px the SVG's text
 * would shrink past legibility, so a plain ordered list of the same stages is
 * shown instead.
 *
 * Read it as a snake: the top row is the decision path, left to right; the
 * rows below are what happens to a decision afterwards, right to left.
 */
export function ArchitectureDiagram() {
  return (
    <figure className="arch">
      <svg
        className="arch__svg"
        viewBox="0 0 1000 470"
        role="img"
        aria-labelledby="arch-title arch-desc"
      >
        <title id="arch-title">FraudGraph architecture</title>
        <desc id="arch-desc">
          A generator publishes payments to Kafka. A Kafka Streams engine deduplicates, enriches,
          checks and decides each one, calling an ML scorer over gRPC. Decisions go to a second Kafka
          topic, read by a case service that stores flagged cases in Postgres, streams every decision to
          this console, and hands each case to an analyst agent, which reads back through the case
          service only.
        </desc>
        <defs>
          <marker id="arch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="arch__head" />
          </marker>
        </defs>

        {/* ---- the decision path ---- */}
        <text x="338" y="16" className="arch__path">DECISION PATH · ABOUT 15 MS AT P99</text>
        <line x1="338" y1="21" x2="984" y2="21" className="arch__pathline" />

        <Box x={16} y={58} w={132} h={64} title="Generator" lines={['Python · 50 payments/s', '2% injected fraud']} />
        <Box x={176} y={58} w={132} h={64} title="Kafka" lines={['transactions.raw', '6 partitions, by account']} mono={0} />

        <rect x="338" y="28" width="468" height="124" rx="6" className="arch__frame" />
        <text x="352" y="48" className="arch__title">
          Stream engine <tspan className="arch__sub">· Java, Kafka Streams, exactly-once</tspan>
        </text>
        <Box x={352} y={62} w={92} h={74} title="dedup" lines={['by txnId']} stage />
        <Box x={454} y={62} w={92} h={74} title="enrich" lines={['amount profile', 'last location']} stage />
        <Box x={556} y={62} w={132} h={74} title="checks" lines={['velocity windows', 'impossible travel', 'ring search']} stage />
        <Box x={698} y={62} w={94} h={74} title="decide" lines={['rules, then', 'model score']} stage />

        <Box x={838} y={62} w={146} h={74} title="ML scorer" lines={['XGBoost + SHAP', 'only if a signal fires']} />

        <Edge d="M148 90 H176" />
        <Edge d="M308 90 H338" />
        <Edge d="M444 99 H454" />
        <Edge d="M546 99 H556" />
        <Edge d="M688 99 H698" />
        <Edge d="M792 91 H838" />
        <Edge d="M838 109 H792" />
        <text x="911" y="154" className="arch__label" textAnchor="middle">gRPC, 150 ms deadline,</text>
        <text x="911" y="168" className="arch__label" textAnchor="middle">circuit breaker → rules only</text>

        {/* ---- after the decision ---- */}
        <Box x={660} y={214} w={146} h={64} title="Kafka" lines={['fraud.decisions', 'every verdict']} mono={0} />
        <Edge d="M745 152 V214" />

        <Box x={418} y={214} w={190} h={64} title="Case service" lines={['Java, Spring Boot', 'REST + WebSocket']} />
        <Edge d="M660 246 H608" />

        <Box x={16} y={214} w={190} h={64} title="This console" lines={['React, no UI kit', 'every decision, live']} accent />
        <Edge d="M418 246 H206" />
        <text x="312" y="238" className="arch__label" textAnchor="middle">WebSocket + REST</text>

        <Box x={418} y={350} w={190} h={58} title="Postgres" lines={['one case per txnId']} />
        <Edge d="M450 278 V350" />
        <text x="442" y="312" className="arch__label" textAnchor="end">REVIEW and BLOCK</text>
        <text x="442" y="326" className="arch__label" textAnchor="end">become cases</text>

        <Box x={660} y={350} w={190} h={74} title="Analyst agent" lines={['Python, LangGraph', 'cites evidence per claim', 'verifier checks numbers']} />
        <Edge d="M560 278 V322 H700 V350" />
        <text x="552" y="302" className="arch__label" textAnchor="end">case id, async</text>
        <Edge d="M790 350 V306 H596 V278" dashed />
        <text x="693" y="300" className="arch__label" textAnchor="middle">reads /internal/* only</text>

        <Box x={872} y={350} w={112} h={58} title="LLM" lines={['via Groq', 'free tier']} />
        <Edge d="M850 380 H872" />

        {/* ---- legend ---- */}
        <line x1="16" y1="452" x2="44" y2="452" className="arch__edge" />
        <text x="52" y="456" className="arch__label">data flow</text>
        <line x1="130" y1="452" x2="158" y2="452" className="arch__edge arch__edge--dashed" />
        <text x="166" y="456" className="arch__label">read-only access</text>
        <text x="16" y="436" className="arch__label">The analyst never sits on the decision path, and has no database or Kafka access.</text>
      </svg>

      <ol className="arch__list" aria-label="The pipeline, in order">
        <li>
          <strong>Generator</strong> <span>Python, 50 payments a second, 2% injected fraud</span>
        </li>
        <li>
          <strong>Kafka</strong> <span className="mono">transactions.raw</span>, 6 partitions keyed by account
        </li>
        <li>
          <strong>Stream engine</strong> <span>dedup → enrich → checks → decide, exactly-once</span>
          <ul>
            <li>
              <strong>ML scorer</strong> over gRPC: XGBoost + SHAP, 150 ms deadline, circuit breaker
            </li>
          </ul>
        </li>
        <li>
          <strong>Kafka</strong> <span className="mono">fraud.decisions</span>, every verdict
        </li>
        <li>
          <strong>Case service</strong> stores REVIEW and BLOCK as cases in Postgres and streams every
          decision to this console
        </li>
        <li>
          <strong>Analyst agent</strong> investigates each case through read-only tools; a verifier
          checks every claim&rsquo;s numbers against its evidence
        </li>
      </ol>
    </figure>
  );
}

function Box({
  x,
  y,
  w,
  h,
  title,
  lines,
  stage,
  accent,
  mono,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  lines: string[];
  stage?: boolean;
  accent?: boolean;
  /** Index of a line to set in mono (a topic name). */
  mono?: number;
}) {
  const cls = stage ? 'arch__box arch__box--stage' : accent ? 'arch__box arch__box--accent' : 'arch__box';
  const cx = x + w / 2;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="5" className={cls} />
      <text x={cx} y={y + 21} className="arch__title" textAnchor="middle">
        {title}
      </text>
      {lines.map((l, i) => (
        <text
          key={l}
          x={cx}
          y={y + 38 + i * 14}
          className={i === mono ? 'arch__sub arch__sub--mono' : 'arch__sub'}
          textAnchor="middle"
        >
          {l}
        </text>
      ))}
    </g>
  );
}

function Edge({ d, dashed }: { d: string; dashed?: boolean }) {
  return <path d={d} className={dashed ? 'arch__edge arch__edge--dashed' : 'arch__edge'} markerEnd="url(#arch-arrow)" />;
}
