// 预设库与预设组合之间的跨 Tab 选择通道
import useStore from 'resso';

export interface PresetLibrarySelection {
  kind: string;
  id: string;
  label: string;
}

export const presetLibraryStore = useStore<{
  selection: PresetLibrarySelection | null;
  requestToken: number;
}>({
  selection: null,
  requestToken: 0,
});

export function requestPresetComposition(selection: PresetLibrarySelection): void {
  presetLibraryStore.selection = selection;
  presetLibraryStore.requestToken += 1;
}

export function clearPresetCompositionRequest(): void {
  presetLibraryStore.selection = null;
}
