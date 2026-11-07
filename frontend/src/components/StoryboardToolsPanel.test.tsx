import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  sliceStoryboard: vi.fn(),
  preflightVideoMerge: vi.fn(),
  mergeVideoSegments: vi.fn(),
}));

vi.mock('../api', () => apiMocks);

vi.mock('../stores/runtimeConfig', () => ({
  getRuntimeConfig: () => ({
    image_tools: {
      storyboard_max_bytes: 25_000_000,
      storyboard_max_pixels: 80_000_000,
      storyboard_crop_margin_max: 200,
    },
  }),
}));

import StoryboardToolsPanel from './StoryboardToolsPanel';

afterEach(() => {
  vi.clearAllMocks();
});

describe('StoryboardToolsPanel', () => {
  it('keeps slicing and merge preflight as separate explicit workflows', () => {
    render(<StoryboardToolsPanel active />);

    expect(
      screen.getByRole('heading', { name: '分镜与视频合并' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /生成 4 个分镜 PNG/ }),
    ).toBeDisabled();

    fireEvent.click(screen.getByText('视频合并'));

    expect(
      screen.getByRole('button', { name: /合并前预检/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: /无损合并/ }),
    ).toBeDisabled();
    expect(screen.getByText('至少添加两个片段')).toBeInTheDocument();
    expect(apiMocks.sliceStoryboard).not.toHaveBeenCalled();
    expect(apiMocks.preflightVideoMerge).not.toHaveBeenCalled();
    expect(apiMocks.mergeVideoSegments).not.toHaveBeenCalled();
  });
});
