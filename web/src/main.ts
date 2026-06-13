import maplibregl from 'maplibre-gl';
import type { ExpressionSpecification } from 'maplibre-gl';
import proj4 from 'proj4';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import type { GridArtefact } from './types';
import { VIRIDIS, viridisGradient } from './viridis';
import { computeScores, type Scored } from './scoring';
import { buildPanel, type PanelState } from './panel';

const UNSCORED_OPACITY = 0.15;

async function fetchGrid(): Promise<GridArtefact> {
  const res = await fetch(`${import.meta.env.BASE_URL}grid.json`);
  if (!res.ok) throw new Error(`grid.json fetch failed: HTTP ${res.status}`);
  return res.json();
}

// EPSG:27700 (British National Grid) — must match the pipeline's compute CRS.
const BNG =
  '+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 ' +
  '+ellps=airy +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 +units=m +no_defs';
const bngToWgs = proj4(BNG, 'EPSG:4326');

// Cell geometry comes from reprojecting the true BNG corners encoded in cellIds.
// BNG grid north is rotated ~1.5° from true north across London (the grid's central
// meridian is 2°W), so quads built axis-aligned in lat/lon stair-step and overlap.
// Corners are shared between neighbouring cells, so memoizing the transform makes
// adjacent quads reuse the identical vertex — the grid tiles with no gaps or overlaps.
function buildGeoJSON(grid: GridArtefact): GeoJSON.FeatureCollection {
  const size = grid.meta.cellSizeM;
  const cache = new Map<string, [number, number]>();
  const corner = (e: number, n: number): [number, number] => {
    const key = `${e}_${n}`;
    let c = cache.get(key);
    if (!c) {
      c = bngToWgs.forward([e, n]) as [number, number];
      cache.set(key, c);
    }
    return c;
  };

  return {
    type: 'FeatureCollection',
    features: grid.cellIds.map((cellId, i) => {
      const [e, n] = cellId.split('_').map(Number);
      const ring = [
        corner(e, n),
        corner(e + size, n),
        corner(e + size, n + size),
        corner(e, n + size),
        corner(e, n),
      ];
      return {
        type: 'Feature',
        id: i,
        properties: { residential: grid.residential[i] },
        geometry: { type: 'Polygon', coordinates: [ring] },
      };
    }),
  };
}

// Cells unscored under the current weights (solo on a layer that is null there)
// render like non-residential land: grey, faded, no partial border.
const scoredFlag: ExpressionSpecification = ['boolean', ['feature-state', 'scored'], false];

const heatColor: ExpressionSpecification = [
  'case',
  ['!', scoredFlag],
  '#9a9a9a',
  ['interpolate', ['linear'], ['coalesce', ['feature-state', 'p'], 0], ...VIRIDIS.flat()],
];

const heatOpacity = (opacity: number): ExpressionSpecification => [
  'case',
  scoredFlag,
  opacity,
  UNSCORED_OPACITY,
];

// Partial-data marker (spec §7): hairline border on cells missing an active layer.
const partialOutline: ExpressionSpecification = [
  'case',
  ['all', scoredFlag, ['boolean', ['feature-state', 'partial'], false]],
  'rgba(255, 255, 255, 0.85)',
  'rgba(0, 0, 0, 0)',
];

function applyFeatureState(map: maplibregl.Map, grid: GridArtefact, scored: Scored) {
  for (let i = 0; i < grid.cellIds.length; i++) {
    if (!grid.residential[i]) continue;
    const p = scored.percentile[i];
    map.setFeatureState(
      { source: 'grid', id: i },
      {
        p: Number.isNaN(p) ? 0 : p,
        scored: !Number.isNaN(p),
        partial: scored.missing[i].length > 0,
      }
    );
  }
}

// Slider input events fire faster than the screen repaints; recompute at most once
// per browser paint and let intermediate values collapse (spec §8).
function rafThrottle(fn: () => void): () => void {
  let pending = false;
  return () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      fn();
    });
  };
}

function setupTooltip(map: maplibregl.Map, grid: GridArtefact, current: () => Scored) {
  const tooltip = document.getElementById('tooltip')!;

  map.on('mousemove', 'cells-heat', (e) => {
    const feature = e.features?.[0];
    if (!feature || typeof feature.id !== 'number') return;
    const i = feature.id;
    const scored = current();

    const rows = grid.meta.layers
      .map((l) => {
        const raw = grid.layers[l.id].raw[i];
        const value =
          raw === null
            ? '<span class="missing">no data</span>'
            : `${raw.toLocaleString()}${l.rawUnit ? ' ' + l.rawUnit : ''}`;
        return `<tr><td>${l.label}</td><td>${value}</td></tr>`;
      })
      .join('');
    const note =
      scored.missing[i].length > 0
        ? `<p class="partial-note">scored without: ${scored.missing[i].join(', ')}</p>`
        : '';
    const composite = Number.isNaN(scored.composite[i])
      ? '<p class="composite">—<span>no data for active layers</span></p>'
      : `<p class="composite">${scored.composite[i].toFixed(2)}
           <span>composite · p${Math.round(scored.percentile[i] * 100)}</span></p>`;

    tooltip.innerHTML = `<p class="cell-id">${grid.cellIds[i]}</p>${composite}<table>${rows}</table>${note}`;
    tooltip.style.display = 'block';
    tooltip.style.transform = `translate(${e.point.x + 14}px, ${e.point.y + 14}px)`;
  });

  map.on('mouseleave', 'cells-heat', () => {
    tooltip.style.display = 'none';
  });
}

async function main() {
  const status = document.getElementById('status')!;
  const map = new maplibregl.Map({
    container: 'map',
    style: 'https://tiles.openfreemap.org/styles/positron',
    center: [-0.118, 51.5],
    zoom: 9.7,
    minZoom: 8,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

  const [grid] = await Promise.all([
    fetchGrid(),
    new Promise<void>((resolve) => map.once('load', () => resolve())),
  ]);

  const state: PanelState = {
    weights: Object.fromEntries(grid.meta.layers.map((l) => [l.id, 5])),
    solo: null,
    opacity: 0.72,
  };

  // Solo temporarily zeroes every other weight (spec §8); the soloed layer's own
  // slider value is irrelevant since a one-layer composite renormalizes to itself.
  const effectiveWeights = (): Record<string, number> =>
    state.solo === null
      ? state.weights
      : Object.fromEntries(grid.meta.layers.map((l) => [l.id, l.id === state.solo ? 1 : 0]));

  let scored = computeScores(grid, effectiveWeights());

  const updateStatus = () => {
    const active = state.solo
      ? `solo: ${grid.meta.layers.find((l) => l.id === state.solo)!.label}`
      : `${grid.meta.layers.filter((l) => state.weights[l.id] > 0).length}/${
          grid.meta.layers.length
        } layers active`;
    status.textContent = `${grid.cellIds.length.toLocaleString()} cells · ${active} · ${grid.meta.generated.slice(0, 10)}`;
  };

  map.addSource('grid', { type: 'geojson', data: buildGeoJSON(grid) });
  applyFeatureState(map, grid, scored);

  // Insert beneath the basemap's labels so place names stay readable over the heat.
  const firstSymbolId = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

  map.addLayer(
    {
      id: 'cells-nonres',
      type: 'fill',
      source: 'grid',
      filter: ['==', ['get', 'residential'], false],
      paint: {
        'fill-color': '#8a8a8a',
        'fill-opacity': 0.12,
        'fill-outline-color': 'rgba(120, 120, 120, 0.25)',
      },
    },
    firstSymbolId
  );
  map.addLayer(
    {
      id: 'cells-heat',
      type: 'fill',
      source: 'grid',
      filter: ['==', ['get', 'residential'], true],
      paint: {
        'fill-color': heatColor,
        'fill-opacity': heatOpacity(state.opacity),
        'fill-outline-color': partialOutline,
      },
    },
    firstSymbolId
  );

  setupTooltip(map, grid, () => scored);

  buildPanel(document.getElementById('panel')!, grid.meta.layers, state, {
    onScoringChange: rafThrottle(() => {
      scored = computeScores(grid, effectiveWeights());
      applyFeatureState(map, grid, scored);
      updateStatus();
    }),
    onOpacityChange: rafThrottle(() => {
      map.setPaintProperty('cells-heat', 'fill-opacity', heatOpacity(state.opacity));
    }),
  });

  document.getElementById('legend-bar')!.style.background = viridisGradient;
  updateStatus();
}

main().catch((err) => {
  document.getElementById('status')!.textContent = `failed to load: ${err.message}`;
  console.error(err);
});
