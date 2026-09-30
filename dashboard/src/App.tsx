import { useEffect } from 'react';
import { source } from './data';
import { feedStore } from './lib/feedStore';
import { useHashRoute } from './lib/useHashRoute';
import { Header } from './components/Header';
import { About } from './views/About';
import { CasesTable } from './views/CasesTable';
import { Console } from './views/Console';

export default function App() {
  const route = useHashRoute();

  // The feed lives for the whole page, not a view, so the ticker and the
  // header's numbers survive a visit to About or the cases table.
  useEffect(() => feedStore.start(source), []);

  useEffect(() => {
    if (route.name !== 'console') window.scrollTo(0, 0);
  }, [route.name]);

  return (
    <div className={`app app--${route.name}`}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <Header route={route.name} />
      <main className="main" id="main">
        {route.name === 'console' ? (
          <Console caseId={route.caseId} />
        ) : route.name === 'cases' ? (
          <CasesTable query={route.query} />
        ) : (
          <About />
        )}
      </main>
    </div>
  );
}
