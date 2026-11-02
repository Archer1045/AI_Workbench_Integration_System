import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  getComicCapabilities: vi.fn(),
  parseComicScript: vi.fn(),
  renderComicText: vi.fn(),
  detectComicBubbles: vi.fn(),
}));

vi.mock('../api', () => apiMocks);

vi.mock('../stores/runtimeConfig', () => ({
  getRuntimeConfig: () => ({
    image_tools: {
      comic_max_bytes: 25_000_000,
      comic_max_pixels: 12_000_000,
      comic_max_boxes: 50,
    },
  }),
}));

import ComicTextPanel from './ComicTextPanel';

afterEach(() => {
  vi.clearAllMocks();
});

describe('ComicTextPanel', () => {
  it('extracts dialogue and exposes the opt-in bubble capability boundary', async () => {
    apiMocks.getComicCapabilities.mockResolvedValue({
      fonts: [{ id: 'system:msyh.ttc', label: 'msyh', source: '系统白名单' }],
      default_font: 'system:msyh.ttc',
      opencv: false,
      auto_bubble_requires: 'opencv-python',
    });
    apiMocks.parseComicScript.mockResolvedValue({
      cleaned_prompt: '漫画分镜，一个标准大小的纯白对话框',
      dialogues: [
        {
          index: 1,
          text: '你好。',
          length: 3,
          bubble_size: '微小',
        },
      ],
      dialogue_count: 1,
      warning: '',
    });

    render(<ComicTextPanel active />);

    expect(
      screen.getByRole('heading', { name: '漫画文字' }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByText('自动气泡检测当前不可用'),
      ).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText(
        '例：漫画分镜，空白气泡。[这是第一句。] [Second line.]',
      ),
      { target: { value: '漫画分镜，[你好。]' } },
    );
    fireEvent.click(
      screen.getByRole('button', { name: /提取对白并清洗提示词/ }),
    );

    await waitFor(() => {
      expect(apiMocks.parseComicScript).toHaveBeenCalledWith({
        raw_prompt: '漫画分镜，[你好。]',
        base_bubble_description: '纯白干净的空白对话框',
      });
      expect(
        screen.getByText('漫画分镜，一个标准大小的纯白对话框'),
      ).toBeInTheDocument();
      expect(screen.getByText(/1\. 你好。 · 微小/)).toBeInTheDocument();
    });
    expect(
      screen.getByRole('button', { name: /自动检测气泡/ }),
    ).toBeDisabled();
  });
});
