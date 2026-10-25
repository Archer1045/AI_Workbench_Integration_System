import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PresetAssetCandidate,
  PresetAssetDetail,
} from '../api';

const actionMocks = vi.hoisted(() => ({
  adopt: vi.fn(),
  clear: vi.fn(),
  discard: vi.fn(),
}));

vi.mock('../stores/presetAssetStore', () => ({
  adoptPresetAsset: actionMocks.adopt,
  apiErrorMessage: (_error: unknown, fallback: string) => fallback,
  clearPresetAssetCandidates: actionMocks.clear,
  discardPresetAsset: actionMocks.discard,
  presetAssetStore: {
    detail: null,
  },
}));

import { presetAssetStore } from '../stores/presetAssetStore';
import PresetAssetCompare from './PresetAssetCompare';

function candidate(
  id: number,
  status: string,
  overrides: Partial<PresetAssetCandidate> = {},
): PresetAssetCandidate {
  return {
    id,
    preset_type: 'pose',
    preset_id: `pose-${id}`,
    generation_mode: id === 2 ? 'crop' : 'ai',
    status,
    model: `model-${id}.safetensors`,
    seed: 100 + id,
    generation_width: 540,
    generation_height: 960,
    output_width: 270,
    output_height: 480,
    created_at: `2026-09-19T00:00:0${id}Z`,
    updated_at: `2026-09-19T00:00:0${id}Z`,
    thumbnail_url: `/candidate-${id}-thumb.webp`,
    preview_url: `/candidate-${id}.webp`,
    original_url: `/candidate-${id}.png`,
    ...overrides,
  };
}

function detailFor(candidates: PresetAssetCandidate[]): PresetAssetDetail {
  return {
    preset: {},
    summary: {
      preset_type: 'pose',
      preset_id: 'pose-a',
      label: 'pose-a',
      category: '测试',
      category_group: '测试',
      subcategory: '',
      rating: 'R18',
      restricted: false,
      image: null,
      has_image: false,
      active_version: null,
      source: null,
      ready_count: candidates.filter((item) => item.status === 'ready').length,
      running_count: 0,
      failed_count: 0,
      candidate_count: candidates.length,
    },
    sources: [],
    candidates,
    versions: [],
  };
}

function pointerEvent(
  type: string,
  init: { pointerId: number; clientX: number; clientY: number },
): MouseEvent {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: init.clientX,
    clientY: init.clientY,
  });
  Object.defineProperty(event, 'pointerId', {
    value: init.pointerId,
  });
  return event;
}

describe('PresetAssetCompare', () => {
  beforeEach(() => {
    actionMocks.adopt.mockReset().mockResolvedValue(undefined);
    actionMocks.clear.mockReset().mockResolvedValue(1);
    actionMocks.discard.mockReset().mockResolvedValue(undefined);
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready', {
        prompt_positive: 'portrait, beach',
        prompt_negative: 'low quality',
      }),
      candidate(2, 'adopted'),
    ]);
  });

  it('keeps quick actions in the grid and opens full details in a modal', async () => {
    const user = userEvent.setup();
    render(<PresetAssetCompare />);

    expect(screen.getAllByRole('button', { name: '人工采纳' })).toHaveLength(2);
    expect(screen.queryByText('Seed')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '查看候选 1 详情' }));

    const firstDialog = await screen.findByRole('dialog');
    expect(within(firstDialog).getByText('候选图 #1')).toBeInTheDocument();
    expect(within(firstDialog).getByText('portrait, beach')).toBeInTheDocument();

    await user.click(within(firstDialog).getByRole('button', { name: '下一张' }));

    const secondDialog = await screen.findByRole('dialog');
    expect(within(secondDialog).getByText('候选图 #2')).toBeInTheDocument();
    expect(within(secondDialog).getByText('2 / 2')).toBeInTheDocument();
  });

  it('runs grid actions directly after confirmation', async () => {
    const user = userEvent.setup();
    render(<PresetAssetCompare />);

    await user.click(screen.getAllByRole('button', { name: '人工采纳' })[0]);
    const confirmation = await screen.findByRole('tooltip');
    await user.click(within(confirmation).getByRole('button', { name: 'OK' }));

    await waitFor(() => expect(actionMocks.adopt).toHaveBeenCalledWith(1));
  });

  it('clears every non-adopted candidate after confirmation', async () => {
    const user = userEvent.setup();
    render(<PresetAssetCompare />);

    await user.click(screen.getByRole('button', { name: '一键清空' }));
    const confirmation = await screen.findByRole('tooltip');
    expect(
      within(confirmation).getByText(
        '将丢弃 1 张未采纳候选，已采纳候选不会撤销。',
      ),
    ).toBeInTheDocument();
    await user.click(
      within(confirmation).getByRole('button', { name: /清\s*空/ }),
    );

    await waitFor(() =>
      expect(actionMocks.clear).toHaveBeenCalledTimes(1),
    );
  });

  it('selects two to four candidates and opens the multi-image compare view', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
      candidate(3, 'ready'),
      candidate(4, 'ready'),
      candidate(5, 'ready'),
    ]);
    render(<PresetAssetCompare />);

    for (const candidateId of [1, 2, 3, 4]) {
      fireEvent.click(
        screen.getByRole('button', {
          name: `将候选 ${candidateId} 加入对比`,
        }),
      );
    }

    expect(screen.getByText('已选 4/4')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '将候选 5 加入对比' }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '多图对比' }));

    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });
    expect(
      within(dialog).getByRole('img', { name: '对比候选 1' }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('img', { name: '对比候选 4' }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole('img', { name: '对比候选 5' }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByText('100%')).toBeInTheDocument();
  });

  it('selects a preferred compare image and adopts it from the footer', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
    ]);
    const user = userEvent.setup();
    render(<PresetAssetCompare />);

    await user.click(screen.getByRole('button', { name: '多图对比' }));
    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });

    await user.click(
      within(dialog).getByRole('button', { name: '选择对比候选 2' }),
    );
    expect(
      within(dialog).getByRole('button', {
        name: '已选择对比候选 2',
      }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(within(dialog).getByText('已选择候选 #2')).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole('button', { name: '人工采纳' }),
    );
    const confirmation = await screen.findByRole('tooltip');
    await user.click(within(confirmation).getByRole('button', { name: 'OK' }));

    await waitFor(() => expect(actionMocks.adopt).toHaveBeenCalledWith(2));
  }, 15000);

  it('selects a candidate by clicking anywhere in its compare panel', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
    ]);
    const user = userEvent.setup();
    render(<PresetAssetCompare />);

    await user.click(screen.getByRole('button', { name: '多图对比' }));
    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });
    const secondPanel = within(dialog).getByRole('article', {
      name: '候选对比面板 2',
    });

    await user.click(
      within(secondPanel).getByRole('img', { name: '对比候选 2' }),
    );

    expect(within(dialog).getByText('已选择候选 #2')).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', {
        name: '已选择对比候选 2',
      }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('does not select from controls or after a compare drag', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
    ]);
    render(<PresetAssetCompare />);

    fireEvent.click(screen.getByRole('button', { name: '多图对比' }));
    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });
    const secondPanel = within(dialog).getByRole('article', {
      name: '候选对比面板 2',
    });

    fireEvent.click(
      within(secondPanel).getByRole('button', { name: '固定候选 2' }),
    );
    expect(within(dialog).getByText(/已选择候选 #/)).toHaveTextContent(
      '已选择候选 #1',
    );

    const viewport = secondPanel.querySelector(
      '.preset-asset-compare-viewport',
    ) as HTMLElement;
    fireEvent(
      viewport,
      pointerEvent('pointerdown', {
        pointerId: 1,
        clientX: 100,
        clientY: 100,
      }),
    );
    fireEvent(
      viewport,
      pointerEvent('pointermove', {
        pointerId: 1,
        clientX: 120,
        clientY: 100,
      }),
    );
    fireEvent(
      viewport,
      pointerEvent('pointerup', {
        pointerId: 1,
        clientX: 120,
        clientY: 100,
      }),
    );
    fireEvent.click(
      within(secondPanel).getByRole('img', { name: '对比候选 2' }),
    );

    expect(within(dialog).getByText(/已选择候选 #/)).toHaveTextContent(
      '已选择候选 #1',
    );
  });

  it('keeps pinned candidates when quick selection replaces an unpinned item', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
      candidate(3, 'ready'),
      candidate(4, 'ready'),
      candidate(5, 'ready'),
    ]);
    render(<PresetAssetCompare />);

    for (const candidateId of [1, 2, 3, 4]) {
      fireEvent.click(
        screen.getByRole('button', {
          name: `将候选 ${candidateId} 加入对比`,
        }),
      );
    }
    fireEvent.click(screen.getByRole('button', { name: '多图对比' }));

    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });
    fireEvent.click(
      within(dialog).getByRole('button', { name: '固定候选 1' }),
    );
    fireEvent.click(
      within(dialog).getByRole('button', {
        name: '将候选 5 加入对比',
      }),
    );

    expect(
      within(dialog).getByRole('img', { name: '对比候选 1' }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('img', { name: '对比候选 5' }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole('img', { name: '对比候选 2' }),
    ).not.toBeInTheDocument();
  });

  it('hides and restores a selected image and supports shared zoom reset', async () => {
    presetAssetStore.detail = detailFor([
      candidate(1, 'ready'),
      candidate(2, 'ready'),
      candidate(3, 'ready'),
    ]);
    render(<PresetAssetCompare />);

    fireEvent.click(screen.getByRole('button', { name: '多图对比' }));
    const dialog = await screen.findByRole('dialog', {
      name: '候选多图对比',
    });

    fireEvent.click(
      within(dialog).getByRole('button', { name: '隐藏候选 1' }),
    );
    expect(
      within(dialog).queryByRole('img', { name: '对比候选 1' }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(dialog).getByRole('button', { name: '恢复候选 1' }),
    );
    expect(
      within(dialog).getByRole('img', { name: '对比候选 1' }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(dialog).getByRole('button', { name: '放大多图对比' }),
    );
    expect(within(dialog).getByText('110%')).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole('button', { name: '重置视图' }),
    );
    expect(within(dialog).getByText('100%')).toBeInTheDocument();
  });
});
