import type { Contribution } from '../lib/types';
import { humanKey, isNum } from '../lib/format';

/**
 * Signed horizontal bars around a zero axis — a diverging encoding, because the
 * sign is the whole point: right/red pushed the model toward fraud, left/green
 * pulled it away. Bars are sorted by magnitude and every bar is directly
 * labelled, so colour is never the only cue.
 */
export function ShapChart({ contributions }: { contributions: Contribution[] }) {
  const rows = (contributions ?? []).filter((c) => c && isNum(c.shap));
  if (rows.length === 0) {
    return <p className="state state--empty">No SHAP contributions on this decision.</p>;
  }
  const max = Math.max(...rows.map((c) => Math.abs(c.shap)));
  const scale = max > 0 ? max : 1;
  const sorted = [...rows].sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap));

  return (
    <div className="shap">
      <div className="shap__legend">
        <span><i className="swatch swatch--neg" /> pulls away from fraud</span>
        <span><i className="swatch swatch--pos" /> pushes toward fraud</span>
      </div>
      <ul className="shap__rows">
        {sorted.map((c) => {
          const pct = (Math.abs(c.shap) / scale) * 50; // half-width max
          const pos = c.shap >= 0;
          return (
            <li className="shap__row" key={c.feature}>
              <span className="shap__label mono" title={c.feature}>
                {humanKey(c.feature)}
              </span>
              <span className="shap__track">
                <span className="shap__axis" aria-hidden="true" />
                <span
                  className={`shap__bar ${pos ? 'shap__bar--pos' : 'shap__bar--neg'}`}
                  style={pos ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
                />
              </span>
              <span className="shap__value mono">
                {c.shap >= 0 ? '+' : '−'}
                {Math.abs(c.shap).toFixed(3)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
