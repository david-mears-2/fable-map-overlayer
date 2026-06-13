import type { GridArtefact } from './types';

// 'mean': weighted arithmetic mean (spec §7) — layers trade off freely.
// 'product': weighted geometric mean — a single near-zero layer drags the whole
// composite down, so one terrible layer can't be fully compensated away.
export type CompositionMode = 'mean' | 'product';

export interface Scored {
  composite: Float64Array; // NaN for cells unscored under current weights
  percentile: Float64Array;
  missing: string[][]; // active-layer ids that are null for this cell
}

// Score floor for product mode: scores reach exactly 0 at a layer's worst cut-off,
// and ln(0) = -inf would zero the whole composite, collapsing every cell that hits
// 0 anywhere into an indistinguishable mass. Flooring keeps such cells heavily
// penalised but still ranked by their other layers.
const PRODUCT_FLOOR = 1e-3;

// The colour ramp maps the composite's percentile (not its raw value) so visual
// contrast is stable whatever the weights or composition mode (spec §8).
export function computeScores(
  grid: GridArtefact,
  weights: Record<string, number>,
  mode: CompositionMode = 'mean'
): Scored {
  const n = grid.cellIds.length;
  const composite = new Float64Array(n).fill(NaN);
  const percentile = new Float64Array(n).fill(NaN);
  const missing: string[][] = Array.from({ length: n }, () => []);

  const active = grid.meta.layers.filter((l) => (weights[l.id] ?? 0) > 0);
  for (let i = 0; i < n; i++) {
    if (!grid.residential[i]) continue;
    // Both modes accumulate a weighted sum over non-null layers and divide by the
    // weight total; product works in log space, so its mean is exponentiated back.
    let sum = 0;
    let wSum = 0;
    for (const l of active) {
      const s = grid.layers[l.id].scores[i];
      if (s === null) {
        missing[i].push(l.id);
      } else {
        sum += weights[l.id] * (mode === 'product' ? Math.log(Math.max(s, PRODUCT_FLOOR)) : s);
        wSum += weights[l.id];
      }
    }
    if (wSum > 0) composite[i] = mode === 'product' ? Math.exp(sum / wSum) : sum / wSum;
  }

  const scored = [];
  for (let i = 0; i < n; i++) if (!Number.isNaN(composite[i])) scored.push(i);
  scored.sort((a, b) => composite[a] - composite[b]);
  for (let k = 0; k < scored.length; k++) {
    percentile[scored[k]] = scored.length > 1 ? k / (scored.length - 1) : 0.5;
  }
  return { composite, percentile, missing };
}
