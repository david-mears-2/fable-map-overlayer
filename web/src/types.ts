// TypeScript mirror of the data artefact schema (london-heatmap-spec.md §4).
export interface LayerMeta {
  id: string;
  label: string;
  direction: 'lower_better' | 'higher_better';
  source: string;
  vintage: string;
  cutoffs: { low: number; high: number };
  rawUnit: string;
}

export interface LayerData {
  scores: (number | null)[];
  raw: (number | null)[];
}

export interface GridArtefact {
  meta: {
    generated: string;
    cellSizeM: number;
    computeCrs: string;
    layers: LayerMeta[];
  };
  cellIds: string[];
  centroids: [number, number][];
  residential: boolean[];
  layers: Record<string, LayerData>;
}
