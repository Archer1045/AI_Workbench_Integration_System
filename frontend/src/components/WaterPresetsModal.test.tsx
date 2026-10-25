import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const presets = [
  {
    id: 'water_half_submerged',
    category: '浸水状态',
    label: '半身浸水',
    translation: '角色身体下半部浸在水中',
    tags: ['waist-deep water', 'half-submerged body'],
    water_level: '腰水',
    target: '角色',
    intensity: '中',
    rating: '普通',
    nsfw: false,
    source: 'builtin',
  },
  {
    id: 'water_steam',
    category: '环境氛围',
    label: '温泉蒸汽',
    translation: '温泉或浴池上方升起柔和蒸汽',
    tags: ['rising steam', 'hot spring mist'],
    water_level: '环境',
    target: '环境',
    intensity: '中',
    rating: '普通',
    nsfw: false,
    source: 'builtin',
  },
];

vi.mock('../api', () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          items: presets,
          categories: ['浸水状态', '环境氛围'],
          water_levels: ['腰水', '环境'],
          targets: ['角色', '环境'],
        },
      }),
    ),
  },
}));

import WaterPresetsModal from './WaterPresetsModal';

describe('WaterPresetsModal', () => {
  it('filters reusable water modifiers and inserts them without generating art', async () => {
    const onInsert = vi.fn();
    render(
      <WaterPresetsModal
        open
        onClose={() => undefined}
        onInsert={onInsert}
      />,
    );

    await waitFor(() => expect(screen.getByText('半身浸水')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('搜索水中玩法'), {
      target: { value: '蒸汽' },
    });

    expect(screen.queryByText('半身浸水')).not.toBeInTheDocument();
    expect(screen.getByText('温泉蒸汽')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '插入 温泉蒸汽' }));
    expect(onInsert).toHaveBeenCalledWith(presets[1], 'all');
  });
});
