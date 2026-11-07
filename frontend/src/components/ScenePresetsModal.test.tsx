import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const preset = {
  id: 'scene_home_bathroom',
  category: '居家日常',
  label: '家庭浴室',
  translation: '有浴缸、独立淋浴区和瓷砖地面的日常浴室',
  tags: ['bathroom', 'bathtub'],
  rating: '普通',
  intensity: '标准',
  people: '单人',
  orientation: '单人',
  role_slots: ['主体'],
  body_separation: false,
  contact_points: [],
  setting: '居家',
  equipment: ['家具'],
  camera: '中景',
  lighting: '柔光',
  conflicts: [],
  draw_prompt: 'a home bathroom, no people',
  empty_scene_prompt: 'a home bathroom, no people',
  occupied_scene_prompt: 'a home bathroom',
  people_policy: 'empty' as const,
  has_image: false,
  image: null,
};

vi.mock('../api', () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          items: [preset],
          total: 1,
          restricted: false,
        },
      }),
    ),
  },
}));

vi.mock('../stores/settings', () => ({
  settingsStore: { restrictionEnabled: false },
}));

import ScenePresetsModal from './ScenePresetsModal';

describe('ScenePresetsModal', () => {
  it('defaults to the occupied prompt and enables empty scenes explicitly', async () => {
    const onInsert = vi.fn();
    render(
      <ScenePresetsModal
        open
        onClose={() => undefined}
        onInsert={onInsert}
      />,
    );

    await waitFor(() => expect(screen.getByText('家庭浴室')).toBeInTheDocument());
    expect(document.querySelector('.help')).toHaveTextContent(
      '当前插入格式：scene prompt',
    );

    fireEvent.click(screen.getByRole('button', { name: '插入' }));
    expect(onInsert).toHaveBeenLastCalledWith(preset, 'all', 'occupied');

    fireEvent.click(screen.getByText('空场景'));
    expect(document.querySelector('.help')).toHaveTextContent(
      '当前插入格式：scene prompt, no people',
    );
    fireEvent.click(screen.getByRole('button', { name: '插入' }));
    expect(onInsert).toHaveBeenLastCalledWith(preset, 'all', 'empty');
  });
});
