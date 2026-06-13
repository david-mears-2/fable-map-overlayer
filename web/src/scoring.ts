import type { GridArtefact } from './types';

export interface Scored {
  composite: Float64Array; // NaN for cells unscored under current weights
  percentile: Float64Array;
  missing: string[][]; // active-layer ids that are null for this cell
}

// Composite = weighted mean over non-null active layers (spec §7); the colour ramp
// maps the composite's percentile so visual contrast is stable whatever the weights (§8).
export function computeScores(grid: GridArtefact, weights: Record<string, number>): Scored {
  const n = grid.cellIds.length;
  const composite = new Float64Array(n).fill(NaN);
  const percentile = new Float64Array(n).fill(NaN);
  const missing: string[][] = Array.from({ length: n }, () => []);

  const active = grid.meta.layers.filter((l) => (weights[l.id] ?? 0) > 0);
  for (let i = 0; i < n; i++) {
    if (!grid.residential[i]) continue;
    let sum = 0;
    let wSum = 0;
    for (const l of active) {
      const s = grid.layers[l.id].scores[i];
      if (s === null) {
        missing[i].push(l.id);
      } else {
        sum += weights[l.id] * s;
        wSum += weights[l.id];
      }
    }
    if (wSum > 0) composite[i] = sum / wSum;
  }

  const scored = [];
  for (let i = 0; i < n; i++) if (!Number.isNaN(composite[i])) scored.push(i);
  scored.sort((a, b) => composite[a] - composite[b]);
  for (let k = 0; k < scored.length; k++) {
    percentile[scored[k]] = scored.length > 1 ? k / (scored.length - 1) : 0.5;
  }
  return { composite, percentile, missing };
}
