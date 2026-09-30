import { useEffect, useState } from 'react';

/**
 * A small hash router instead of react-router-dom. Hash routing needs no server
 * configuration, which is what lets the same build run behind nginx and on
 * GitHub Pages under /fraudgraph/: only the part after `#` ever changes.
 *
 *   #/             the console (a default case is chosen)
 *   #/case/{id}    the console with that case selected
 *   #/cases        the cases table (?status=&offset=)
 *   #/about        what this is
 *
 * The routes of the previous dashboard (#/live, #/cases/{id}) still resolve.
 */
export type Route =
  | { name: 'console'; caseId: string | null }
  | { name: 'cases'; query: URLSearchParams }
  | { name: 'about' };

function read(): Route {
  const raw = window.location.hash.replace(/^#/, '');
  const [path, search] = raw.split('?');
  const seg = path.split('/').filter(Boolean);
  if ((seg[0] === 'case' || seg[0] === 'cases') && seg[1]) {
    return { name: 'console', caseId: decodeURIComponent(seg[1]) };
  }
  if (seg[0] === 'cases') return { name: 'cases', query: new URLSearchParams(search ?? '') };
  if (seg[0] === 'about') return { name: 'about' };
  return { name: 'console', caseId: null };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener('hashchange', onChange);
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

export function caseHref(caseId: string): string {
  return `#/case/${encodeURIComponent(caseId)}`;
}
