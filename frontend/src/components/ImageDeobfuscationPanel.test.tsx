import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  deobfuscateImage: vi.fn(),
}));

vi.mock('../api', () => ({
  deobfuscateImage: apiMocks.deobfuscateImage,
}));

vi.mock('../stores/runtimeConfig', () => ({
  getRuntimeConfig: () => ({
    image_tools: {
      max_bytes: 25_000_000,
      max_pixels: 12_000_000,
      max_concurrency: 1,
      roughness_ratio_max: 0.85,
      min_roughness_drop: 0.02,
    },
  }),
}));

import ImageDeobfuscationPanel from './ImageDeobfuscationPanel';

const report = {
  algorithm: 'xiaofanqie-gilbert-v1',
  operation: 'decode' as const,
  source_format: 'JPEG',
  width: 720,
  height: 1145,
  mode: 'RGB',
  pixel_count: 824_400,
  roughness_before: 11.39888,
  roughness_after: 8.638439,
  roughness_ratio: 0.757832,
  accepted: true,
  forced: false,
  input_sha256: 'A'.repeat(64),
  output_sha256: 'B'.repeat(64),
};

describe('ImageDeobfuscationPanel', () => {
  const createObjectUrl = vi.fn(() => 'blob:preview');
  const revokeObjectUrl = vi.fn();

  beforeEach(() => {
    apiMocks.deobfuscateImage.mockReset();
    createObjectUrl.mockClear();
    revokeObjectUrl.mockClear();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectUrl,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('uploads a selected image and shows the decoded preview and report', async () => {
    apiMocks.deobfuscateImage.mockResolvedValue({
      blob: new Blob(['png'], { type: 'image/png' }),
      report,
    });
    const { container } = render(<ImageDeobfuscationPanel active />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['source'], 'sample.jpg', { type: 'image/jpeg' });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(apiMocks.deobfuscateImage).toHaveBeenCalledWith(file, { force: false }),
    );
    expect(await screen.findByText('识别通过')).toBeInTheDocument();
    expect(screen.getByAltText('解混淆后的图片')).toHaveAttribute('src', 'blob:preview');
    expect(screen.getByText('720 × 1145')).toBeInTheDocument();
    expect(screen.getByText('75.8%')).toBeInTheDocument();
    expect(screen.getByText(report.input_sha256)).toBeInTheDocument();
  });

  it('explains a failed recognition and retries in forced mode', async () => {
    apiMocks.deobfuscateImage
      .mockRejectedValueOnce({
        response: {
          status: 422,
          data: { detail: '解混淆后粗糙度未明显下降，可能不是小番茄混淆图' },
        },
      })
      .mockResolvedValueOnce({
        blob: new Blob(['png'], { type: 'image/png' }),
        report: { ...report, accepted: false, forced: true },
      });
    const { container } = render(<ImageDeobfuscationPanel active />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['source'], 'normal.png', { type: 'image/png' });

    fireEvent.change(input, { target: { files: [file] } });

    expect(
      await screen.findByText('解混淆后粗糙度未明显下降，可能不是小番茄混淆图'),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('checkbox', { name: '强制查看未通过识别的结果' }),
    );
    fireEvent.click(screen.getByRole('button', { name: '重新解混淆' }));

    await waitFor(() =>
      expect(apiMocks.deobfuscateImage).toHaveBeenLastCalledWith(file, { force: true }),
    );
    expect(await screen.findByText('当前为强制查看结果')).toBeInTheDocument();
  });

  it('accepts an image pasted from the clipboard while the tool is active', async () => {
    apiMocks.deobfuscateImage.mockResolvedValue({
      blob: new Blob(['png'], { type: 'image/png' }),
      report,
    });
    render(<ImageDeobfuscationPanel active />);
    const file = new File(['pasted'], 'clipboard.png', { type: 'image/png' });
    const event = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'clipboardData', {
      value: { files: [file] },
    });

    window.dispatchEvent(event);

    await waitFor(() =>
      expect(apiMocks.deobfuscateImage).toHaveBeenCalledWith(file, { force: false }),
    );
  });
});
