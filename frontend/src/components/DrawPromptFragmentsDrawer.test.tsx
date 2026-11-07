import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DrawPromptFragmentsDrawer from './DrawPromptFragmentsDrawer';

afterEach(() => {
  localStorage.clear();
});

describe('DrawPromptFragmentsDrawer', () => {
  it('searches, favorites and inserts a fragment', () => {
    const onInsert = vi.fn();
    render(
      <DrawPromptFragmentsDrawer
        open
        onClose={() => undefined}
        onInsert={onInsert}
      />,
    );

    fireEvent.change(screen.getByLabelText('搜索提示词片段'), {
      target: { value: '电影' },
    });
    expect(screen.getByText('柔和电影光')).toBeInTheDocument();
    expect(screen.queryByText('雨天')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '收藏片段' }));
    expect(
      screen.getByRole('button', { name: '取消收藏片段' }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: '插入片段 柔和电影光' }),
    );
    expect(onInsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'fragment_light_soft' }),
    );
  });
});
