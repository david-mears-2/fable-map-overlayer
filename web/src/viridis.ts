// Viridis stops (perceptually uniform, spec §8). Position in [0,1] → hex colour.
export const VIRIDIS: [number, string][] = [
  [0.0, '#440154'],
  [0.111, '#482878'],
  [0.222, '#3e4989'],
  [0.333, '#31688e'],
  [0.444, '#26828e'],
  [0.556, '#1f9e89'],
  [0.667, '#35b779'],
  [0.778, '#6ece58'],
  [0.889, '#b5de2b'],
  [1.0, '#fde725'],
];

export const viridisGradient = `linear-gradient(to right, ${VIRIDIS.map(
  ([t, c]) => `${c} ${t * 100}%`
).join(', ')})`;
