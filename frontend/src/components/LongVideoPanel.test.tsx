import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  startLongVideo: vi.fn(),
  getLongVideoStatus: vi.fn(),
  stopLongVideo: vi.fn(),
  resumeLongVideo: vi.fn(),
}));

vi.mock('../api', () => apiMocks);

vi.mock('../stores/runtimeConfig', () => ({
  getRuntimeConfig: () => ({
    video: {
      default_frames: 121,
      default_fps: 24,
      default_width: 512,
      default_height: 512,
      default_steps: 20,
      default_cfg: 6,
      default_denoise: 1,
      default_lora_strength: 1,
      long_video_max_segments: 20,
      long_video_max_total_frames: 600,
      steps_min: 1,
      steps_max: 100,
      cfg_min: 0.5,
      cfg_max: 20,
      cfg_step: 0.5,
      denoise_min: 0,
      denoise_max: 1,
      denoise_step: 0.05,
      allowed_frames: [33, 81, 121],
      allowed_sizes: [
        [512, 512],
        [832, 480],
        [480, 832],
      ],
    },
  }),
}));

import LongVideoPanel from './LongVideoPanel';

afterEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

describe('LongVideoPanel', () => {
  it('starts with two ordered segments and requires an explicit start', async () => {
    apiMocks.api.get.mockResolvedValue({ data: { items: [] } });
    render(<LongVideoPanel />);

    expect(
      screen.getByRole('heading', { name: '长视频分段接力' }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText('第 1 段动作描述')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('第 2 段动作描述')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /开始分段生成/ }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMocks.api.get).toHaveBeenCalledWith('/video/keyframes');
    });
    expect(apiMocks.startLongVideo).not.toHaveBeenCalled();
    expect(apiMocks.resumeLongVideo).not.toHaveBeenCalled();
  });
});
