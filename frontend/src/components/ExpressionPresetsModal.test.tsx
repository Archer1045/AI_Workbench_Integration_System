import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const presets = [
  {
    id: 'expression_soft_smile',
    category: '基础情绪',
    label: '柔和微笑',
    translation: '闭口、温和且自然的微笑',
    tags: ['soft smile', 'gentle smile', 'closed mouth'],
    intensity: '轻',
    character_scope: ['通用'],
    rating: '普通',
    nsfw: false,
    source: 'builtin',
    aliases: [],
  },
  {
    id: 'expression_shy_blush',
    category: '基础情绪',
    label: '害羞脸红',
    translation: '轻微脸红、移开视线的腼腆表情',
    tags: ['blush', 'shy expression', 'looking away'],
    intensity: '中',
    character_scope: ['通用'],
    rating: '普通',
    nsfw: false,
    source: 'builtin',
    aliases: ['害羞'],
  },
];

vi.mock('../api', () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          items: presets,
          total: presets.length,
          categories: ['基础情绪'],
          intensities: ['轻', '中'],
          character_scopes: ['通用'],
        },
      }),
    ),
  },
}));

vi.mock('../stores/settings', () => ({
  settingsStore: { restrictionEnabled: false },
}));

import ExpressionPresetsModal from './ExpressionPresetsModal';

describe('ExpressionPresetsModal', () => {
  it('filters expressions and inserts the selected preset silently', async () => {
    const onInsert = vi.fn();
    render(
      <ExpressionPresetsModal
        open
        onClose={() => undefined}
        onInsert={onInsert}
      />,
    );

    await waitFor(() => expect(screen.getByText('柔和微笑')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('搜索表情预设'), {
      target: { value: '害羞' },
    });

    expect(screen.queryByText('柔和微笑')).not.toBeInTheDocument();
    expect(screen.getByText('害羞脸红')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '插入 害羞脸红' }));
    expect(onInsert).toHaveBeenCalledWith(presets[1], 'all');
  });
});
