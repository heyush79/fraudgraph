import { LLD_URL, REPO_URL } from '../config';
import { source } from '../data';
import { fmtDateUtc } from '../lib/format';
import { useManifest } from '../lib/hooks';
import { href } from '../lib/useHashRoute';
import { ArchitectureDiagram } from '../components/ArchitectureDiagram';

const NUMBERS: { value: string; text: string }[] = [
  { value: '~15 ms', text: 'decision latency at p99, from the payment’s timestamp to its verdict, at 50 payments a second' },
  { value: '150 ms', text: 'deadline on each model call; past it, a circuit breaker lets the rules decide alone' },
  { value: '5 hops', text: 'how deep the ring search goes in the in-memory graph of peer-to-peer transfers' },
  { value: '20,000', text: 'synthetic accounts; 2% of their payments are injected fraud of three kinds' },
  { value: '1', text: 'case per flagged payment, however many times Kafka redelivers it' },
  { value: '0', text: 'language-model calls on the decision path: the analyst runs only after a case exists' },
];

export function About() {
  const manifest = useManifest();
  const m = manifest.data;

  return (
    <article className="about">
      <header className="about__hero">
        <p className="label">About this project</p>
        <h1 className="about__title">FraudGraph</h1>
        <p className="about__lede">
          Real-time payment fraud detection, with an AI analyst that has to show its work.
        </p>
      </header>

      <div className="about__body">
        <p>
          FraudGraph decides every payment as it happens. A stream-processing engine checks each one
          for bursts of spending, for a card turning up in two cities at once, and for money moving in a
          circle between accounts, asks a machine-learning model for a second opinion, and returns{' '}
          <strong>ALLOW</strong>, <strong>REVIEW</strong> or <strong>BLOCK</strong> in about 15 ms.
        </p>
        <p>
          Flagged payments become cases. For each one an AI analyst gathers evidence through read-only
          tools and writes a report in which every claim must cite that evidence. Before anyone sees the
          report, ordinary code checks that each number a claim quotes really appears in the evidence it
          cites, and removes the claims that fail.
        </p>

        <h2 className="about__h">The pipeline</h2>
        <ArchitectureDiagram />

        <h2 className="about__h">In numbers</h2>
        <dl className="numbers">
          {NUMBERS.map((n) => (
            <div className="numbers__item" key={n.value}>
              <dt className="numbers__value">{n.value}</dt>
              <dd className="numbers__text">{n.text}</dd>
            </div>
          ))}
        </dl>

        <h2 className="about__h">How a payment is decided</h2>
        <ul className="about__list">
          <li>
            <strong>Velocity.</strong> Sliding one-minute, five-minute and one-hour windows per account.
            More than 8 payments in a minute is a signal.
          </li>
          <li>
            <strong>Impossible travel.</strong> The distance between an account&rsquo;s consecutive
            payments over the time between them. Faster than 900 km/h across more than 100 km is a
            signal: no traveller moves that fast, but a cloned card can.
          </li>
          <li>
            <strong>Laundering rings.</strong> Peer-to-peer transfers form an in-memory graph. A bounded
            search from each payment looks for a path back to the payer, which means the money went round
            in a circle; a related check flags money forwarded on as soon as it arrives.
          </li>
          <li>
            <strong>Hard rules.</strong> A payment to a sanctioned merchant, or above an absolute cap, is
            blocked outright.
          </li>
          <li>
            <strong>The model.</strong> When any signal fires, an XGBoost model scores the payment over
            gRPC and SHAP says which features drove the score. If the model is slow or down, the engine
            decides on rules alone and marks the decision <span className="mono">DEGRADED</span> rather than
            stall.
          </li>
        </ul>

        <h2 className="about__h">Why the analyst&rsquo;s word can be checked</h2>
        <p>
          The analyst is a LangGraph agent on a free-tier model. It never sits on the decision path, it has
          no database or Kafka access, and it reads only through the case service&rsquo;s internal API.
          Every sentence it writes carries numbered citations. A verifier written in plain Python rejects
          any sentence that cites nothing, cites a tool call that failed, or quotes a number that is not in
          the evidence it cites. The console shows what was removed and why, so the guard is visible rather
          than taken on trust.
        </p>

        <h2 className="about__h">What you are looking at</h2>
        <p>
          The <a href={href('/')}>console</a> has three parts. On the left, every decision as the engine
          makes it. In the centre, one case: the signals that fired, the analyst&rsquo;s cited report, the
          model&rsquo;s attribution, the account&rsquo;s transaction network and recent activity. On the
          right, you can ask the analyst about that case.
        </p>
        <p>
          {source.mode === 'replay' ? (
            <>
              This deployment is a <strong>replay</strong>: a recording of the real pipeline
              {m?.recordedAt ? <>, captured {fmtDateUtc(m.recordedAt)}</> : null}, played back at its
              original timing, with no backend behind it. Every decision, case, report and answer in it
              was produced by the running system
              {m?.agentModel ? <>, the answers by {m.agentModel}</> : null}. The same console runs live
              against the pipeline from the repository.
              {m?.sample ? ' This build carries a small development sample rather than the full recording.' : ''}
            </>
          ) : (
            <>
              This deployment is <strong>live</strong>: the feed, the cases and the analyst&rsquo;s answers
              come from a running pipeline.
            </>
          )}
        </p>

        <footer className="about__links">
          <a className="btn btn--primary" href={REPO_URL} target="_blank" rel="noreferrer">
            Source on GitHub
          </a>
          <a className="btn" href={LLD_URL} target="_blank" rel="noreferrer">
            Read the low-level design
          </a>
        </footer>
      </div>
    </article>
  );
}
