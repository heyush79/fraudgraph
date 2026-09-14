import { useEffect, useState } from 'react';

/**
 * A ~30-line hash router instead of react-router-dom. The app has three routes
 * and the LLD asks for a thin dashboard; a dependency would cost more than it
 * saves. Hash routing also means no server-side route config is required.
 *
 * Routes: #/live | #/cases?status=&offset= | #/cases/{caseId}
 */
export interface Route {
  path: string;
  segments: string[];
  query: URLSearchParams;
}

function read(): Route {
  const raw = window.location.hash.replace(/^#/, '') || '/live';
  const [path, search] = raw.split('?');
  return {
    path,
    segments: path.split('/').filter(Boolean),
    query: new URLSearchParams(search ?? ''),
  };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener('hashchange', onChange);
    if (!window.location.hash) window.location.replace('#/live');
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function navigate(to: string): void {
  window.location.hash = to;
}

export function href(to: string): string {
  return `#${to}`;
}
