import type { LayerMeta } from './types';

export interface PanelState {
  weights: Record<string, number>; // slider positions in [0, 10], spec §7
  solo: string | null; // layer id whose solo toggle is active
  opacity: number; // global heat-layer fill-opacity in [0, 1], spec §8
}

export interface PanelCallbacks {
  onScoringChange: () => void; // weights or solo changed → recompute composite
  onOpacityChange: () => void;
}

export function buildPanel(
  container: HTMLElement,
  layers: LayerMeta[],
  state: PanelState,
  cb: PanelCallbacks
): void {
  const heading = document.createElement('h2');
  heading.textContent = 'layer weights';
  container.appendChild(heading);

  const rows = new Map<string, HTMLElement>();

  const refresh = () => {
    for (const [id, row] of rows) {
      const dimmed =
        state.solo !== null ? state.solo !== id : state.weights[id] === 0;
      row.classList.toggle('muted', dimmed);
      row.querySelector('.solo')!.classList.toggle('active', state.solo === id);
    }
  };

  for (const layer of layers) {
    const row = document.createElement('div');
    row.className = 'panel-row';
    row.innerHTML = `
      <div class="row-head">
        <span class="row-label">${layer.label}</span>
        <button class="solo" title="Solo: temporarily zero all other weights">solo</button>
      </div>
      <div class="row-slider">
        <input type="range" min="0" max="10" step="1" value="${state.weights[layer.id]}"
               aria-label="Weight: ${layer.label}" />
        <output>${state.weights[layer.id]}</output>
      </div>`;

    const slider = row.querySelector('input')!;
    const out = row.querySelector('output')!;
    slider.addEventListener('input', () => {
      state.weights[layer.id] = Number(slider.value);
      out.textContent = slider.value;
      refresh();
      cb.onScoringChange();
    });
    row.querySelector('.solo')!.addEventListener('click', () => {
      state.solo = state.solo === layer.id ? null : layer.id;
      refresh();
      cb.onScoringChange();
    });

    rows.set(layer.id, row);
    container.appendChild(row);
  }

  const opacityRow = document.createElement('div');
  opacityRow.className = 'panel-row opacity-row';
  opacityRow.innerHTML = `
    <div class="row-head"><span class="row-label">heat opacity</span></div>
    <div class="row-slider">
      <input type="range" min="0" max="100" step="1" value="${Math.round(state.opacity * 100)}"
             aria-label="Heat layer opacity" />
      <output>${Math.round(state.opacity * 100)}%</output>
    </div>`;
  const opacitySlider = opacityRow.querySelector('input')!;
  const opacityOut = opacityRow.querySelector('output')!;
  opacitySlider.addEventListener('input', () => {
    state.opacity = Number(opacitySlider.value) / 100;
    opacityOut.textContent = `${opacitySlider.value}%`;
    cb.onOpacityChange();
  });
  container.appendChild(opacityRow);

  refresh();
}
