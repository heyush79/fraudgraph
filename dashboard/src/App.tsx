import { useHashRoute } from './lib/useHashRoute';
import { useLiveFeed } from './lib/useLiveFeed';
import { Header } from './components/Header';
import { LiveFeed } from './views/LiveFeed';
import { CasesTable } from './views/CasesTable';
import { CaseDetail } from './views/CaseDetail';

export default function App() {
  const route = useHashRoute();
  // The socket lives here, not in the view, so the buffer survives navigation.
  const feed = useLiveFeed(200);

  return (
    <div className="app">
      <Header
        route={route.path}
        conn={feed.state}
        attempt={feed.attempt}
        onReconnect={feed.reconnectNow}
      />
      <main className="main">{view(route, feed)}</main>
      <footer className="foot">
        <span>
          FraudGraph dashboard — a window into the case service. Verdicts are produced by the
          stream engine; <code className="rule">DEGRADED</code> means the ML scorer was
          unreachable and rules decided alone.
        </span>
      </footer>
    </div>
  );
}

function view(route: ReturnType<typeof useHashRoute>, feed: ReturnType<typeof useLiveFeed>) {
  const [head, id] = route.segments;
  if (head === 'cases' && id) return <CaseDetail caseId={id} />;
  if (head === 'cases') return <CasesTable query={route.query} />;
  return <LiveFeed feed={feed} />;
}
