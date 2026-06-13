// Generates a schema-conformant dummy grid.json (see ../london-heatmap-spec.md §4).
// Stand-in for the Python pipeline: real 250 m BNG grid geometry, synthetic layer
// values shaped to look spatially plausible so the frontend can be exercised at
// full cell count. Deterministic (seeded) so regeneration is reproducible.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import proj4 from 'proj4';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'grid.json');

const BNG =
  '+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 ' +
  '+ellps=airy +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 +units=m +no_defs';
const bngToWgs = proj4(BNG, 'EPSG:4326');

const CELL = 250;
// Ellipse approximating the Greater London boundary (true clip comes with the pipeline).
const CENTRE_E = 530000;
const CENTRE_N = 180500;
const SEMI_E = 28000;
const SEMI_N = 21000;

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Sum of random Gaussian bumps: cheap spatially-correlated noise so dummy layers
// have neighbourhood structure instead of white noise.
function blobField(rng, count, sigmaMin, sigmaMax, signed = false) {
  const blobs = Array.from({ length: count }, () => ({
    e: CENTRE_E + (rng() * 2 - 1) * SEMI_E,
    n: CENTRE_N + (rng() * 2 - 1) * SEMI_N,
    amp: signed ? rng() * 2 - 1 : rng(),
    sigma: sigmaMin + rng() * (sigmaMax - sigmaMin),
  }));
  return (e, n) => {
    let v = 0;
    for (const b of blobs) {
      const d2 = (e - b.e) ** 2 + (n - b.n) ** 2;
      v += b.amp * Math.exp(-d2 / (2 * b.sigma ** 2));
    }
    return v;
  };
}

const rng = mulberry32(20260613);
const priceNoise = blobField(rng, 40, 1500, 5000, true);
const parkBlobs = blobField(rng, 60, 600, 2500);
const townCentres = blobField(rng, 10, 800, 1600);
const travelNoise = blobField(rng, 30, 2000, 6000, true);
const nonResBlobs = blobField(rng, 35, 400, 1200);

// Crude Thames: a sine meander, ~600 m wide band of non-residential cells.
const thamesN = (e) => 179200 + 2300 * Math.sin((e - 504000) / 7800) - (e - CENTRE_E) * 0.04;

const workA = proj4('EPSG:4326', BNG).forward([-0.17, 51.49]); // [E, N], matches spec config

const cellIds = [];
const centroids = [];
const residential = [];
const raws = { price: [], travel_workA_pt: [], restaurants: [], parks: [] };

const eMin = Math.floor((CENTRE_E - SEMI_E) / CELL) * CELL;
const eMax = Math.ceil((CENTRE_E + SEMI_E) / CELL) * CELL;
const nMin = Math.floor((CENTRE_N - SEMI_N) / CELL) * CELL;
const nMax = Math.ceil((CENTRE_N + SEMI_N) / CELL) * CELL;

for (let n = nMin; n < nMax; n += CELL) {
  for (let e = eMin; e < eMax; e += CELL) {
    const ce = e + CELL / 2;
    const cn = n + CELL / 2;
    if (((ce - CENTRE_E) / SEMI_E) ** 2 + ((cn - CENTRE_N) / SEMI_N) ** 2 > 1) continue;

    const [lon, lat] = bngToWgs.forward([ce, cn]);
    cellIds.push(`${e}_${n}`);
    centroids.push([Math.round(lon * 1e5) / 1e5, Math.round(lat * 1e5) / 1e5]);

    const isThames = Math.abs(cn - thamesN(ce)) < 300;
    const isRes = !isThames && nonResBlobs(ce, cn) < 0.75;
    residential.push(isRes);

    if (!isRes) {
      for (const k of Object.keys(raws)) raws[k].push(null);
      continue;
    }

    const distCentre = Math.hypot(ce - CENTRE_E, cn - CENTRE_N);

    // Price: expensive core decaying outward; central cells often null (the 3-bed+
    // filter thins observations in central London, spec §5).
    const priceNull = rng() < 0.55 * Math.exp(-distCentre / 4000) + 0.03;
    raws.price.push(
      priceNull ? null : Math.round(2800 + 11000 * Math.exp(-distCentre / 9000) + 1200 * priceNoise(ce, cn))
    );

    // Travel: minutes grow with distance from Work A, plus corridor-ish noise.
    const distA = Math.hypot(ce - workA[0], cn - workA[1]);
    raws.travel_workA_pt.push(Math.max(3, Math.round(8 + (distA / 1000) * 2.4 + 7 * travelNoise(ce, cn))));

    // Restaurants: dense core plus suburban town centres.
    raws.restaurants.push(
      Math.max(0, Math.round(110 * Math.exp(-distCentre / 5000) + 45 * townCentres(ce, cn) + (rng() - 0.4) * 6))
    );

    // Parks: gravity-style accessibility, blobby by construction.
    raws.parks.push(Math.round(parkBlobs(ce, cn) * 250) / 100);
  }
}

// Winsorized linear rescaling (spec §7): clamp to cut-offs, rescale, flip if lower_better.
function percentile(sorted, p) {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (idx - lo);
}

const layerMeta = [
  { id: 'price', label: 'Price (£/m², 3-bed+ houses)', direction: 'lower_better', rawUnit: '£/m²', cutoffs: { low: 4000, high: 12000 } },
  { id: 'travel_workA_pt', label: 'Work A by public transport', direction: 'lower_better', rawUnit: 'min', cutoffs: null },
  { id: 'restaurants', label: 'Restaurants within 500 m', direction: 'higher_better', rawUnit: 'venues', cutoffs: null },
  { id: 'parks', label: 'Park access (gravity score)', direction: 'higher_better', rawUnit: '', cutoffs: null },
];

const layers = {};
for (const meta of layerMeta) {
  const raw = raws[meta.id];
  if (!meta.cutoffs) {
    const sorted = raw.filter((v) => v !== null).sort((a, b) => a - b);
    meta.cutoffs = {
      low: Math.round(percentile(sorted, 2) * 100) / 100,
      high: Math.round(percentile(sorted, 98) * 100) / 100,
    };
  }
  const { low, high } = meta.cutoffs;
  const scores = raw.map((v) => {
    if (v === null) return null;
    let s = Math.min(1, Math.max(0, (v - low) / (high - low)));
    if (meta.direction === 'lower_better') s = 1 - s;
    return Math.round(s * 1000) / 1000;
  });
  layers[meta.id] = { scores, raw };
  meta.source = 'dummy generator';
  meta.vintage = '2026-06';
}

const artefact = {
  meta: {
    generated: new Date().toISOString(),
    cellSizeM: CELL,
    computeCrs: 'EPSG:27700',
    layers: layerMeta,
  },
  cellIds,
  centroids,
  residential,
  layers,
};

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(artefact));

const resCount = residential.filter(Boolean).length;
const priceNulls = layers.price.scores.filter((s, i) => residential[i] && s === null).length;
console.log(`grid.json: ${cellIds.length} cells (${resCount} residential, ${priceNulls} null-price residential)`);
console.log(`cutoffs: ${layerMeta.map((m) => `${m.id}=[${m.cutoffs.low}, ${m.cutoffs.high}]`).join('  ')}`);
