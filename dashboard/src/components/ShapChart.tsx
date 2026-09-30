import type { Contribution } from '../lib/types';
import { isNum } from '../lib/format';
import { featureLabel } from '../lib/signals';

/**
 * Signed horizontal bars around a zero axis — a diverging encoding, because the
 * sign is the whole point: right pushed the model toward fraud, left pulled it
 * away. Bars are sorted by magnitude and every bar carries its signed value, so
 * direction and number both say what the colour says.
 */
export function ShapChart({ contributions }: { contributions: Contribution[] }) {
  const rows = (contributions ?? []).filter((c) => c && isNum(c.shap));
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((c) => Math.abs(c.shap)));
  const scale = max > 0 ? max : 1;
  const sorted = [...rows].sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap));

  return (
    <div className="shap">
      <ul className="shap__rows">
        {sorted.map((c) => {
          const pct = (Math.abs(c.shap) / scale) * 50; // half-width max
          const pos = c.shap >= 0;
          return (
            <li className="shap__row" key={c.feature}>
              <span className="shap__label" title={c.feature}>
                {featureLabel(c.feature)}
              </span>
              <span className="shap__track" aria-hidden="true">
                <span className="shap__axis" />
                <span
                  className={`shap__bar ${pos ? 'shap__bar--pos' : 'shap__bar--neg'}`}
                  style={pos ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
                />
              </span>
              <span className="shap__value mono">
                {pos ? '+' : '−'}
                {Math.abs(c.shap).toFixed(2)}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="shap__legend">
        <span>
          <i className="swatch swatch--neg" aria-hidden="true" /> pulled toward allow
        </span>
        <span>
          <i className="swatch swatch--pos" aria-hidden="true" /> pushed toward fraud
        </span>
      </div>
    </div>
  );
}
