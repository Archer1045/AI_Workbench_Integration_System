import type { GenerationCanvasPreset, GenerationProfile } from './api';

export function normalizeGenerationDimension(
  value: number,
  profile: GenerationProfile,
): number {
  const step = Math.max(1, Math.round(profile.resolution_step || 8));
  const minimum = Math.max(1, Math.round(profile.min_size || step));
  const maximum = Math.max(minimum, Math.round(profile.max_size || minimum));
  const numeric = Number.isFinite(value) ? value : minimum;
  const snapped = Math.round(numeric / step) * step;
  return Math.min(maximum, Math.max(minimum, snapped));
}

export function normalizeGenerationSize(
  width: number,
  height: number,
  profile: GenerationProfile,
): [number, number] {
  return [
    normalizeGenerationDimension(width, profile),
    normalizeGenerationDimension(height, profile),
  ];
}

export function selectedCanvasPreset(
  width: number,
  height: number,
  profile: GenerationProfile,
): GenerationCanvasPreset | null {
  return (
    profile.canvas_presets.find(
      (item) => item.width === width && item.height === height,
    ) || null
  );
}

export function canvasPresetOptions(
  profile: GenerationProfile,
): GenerationCanvasPreset[] {
  const presets = profile.canvas_presets.filter(
    (item) => item.width > 0 && item.height > 0,
  );
  return presets.length > 0
    ? presets
    : [
        {
          id: '1:1',
          label: '1:1 方形',
          width: normalizeGenerationDimension(1024, profile),
          height: normalizeGenerationDimension(1024, profile),
        },
      ];
}
