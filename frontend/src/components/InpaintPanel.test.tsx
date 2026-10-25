import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createStructuredDocumentFromLegacy } from '../promptDocument';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('../api', () => ({
  api: apiMocks,
}));

vi.mock('../stores/runtimeConfig', () => ({
  getRuntimeConfig: () => ({
    draw: {
      default_model: 'test.safetensors',
      default_negative_prompt: 'lowres',
      default_steps: 18,
      default_cfg: 1,
    },
  }),
}));

vi.mock('./ImageLibraryDrawer', () => ({
  default: () => null,
}));

import InpaintPanel, { type InpaintInitialSource } from './InpaintPanel';

const SOURCE: InpaintInitialSource = {
  recordId: 42,
  imageUrl: '/images/source.png',
  width: 512,
  height: 512,
  label: '绘画结果 #42',
  prompt: '1girl, long hair, white dress',
  negativePrompt: 'lowres',
  promptDocument: createStructuredDocumentFromLegacy(
    '1girl, long hair, white dress',
    'lowres',
  ),
};

function mockSourceImage() {
  vi.spyOn(window, 'Image').mockImplementation(() => {
    const image = {} as HTMLImageElement;
    Object.defineProperty(image, 'src', {
      configurable: true,
      set() {
        image.onload?.(new Event('load'));
      },
    });
    return image;
  });
}

function mockCanvas() {
  const imageData = {
    data: new Uint8ClampedArray([255, 255, 255, 255]),
    width: 1,
    height: 1,
  } as ImageData;
  const context = {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    getImageData: vi.fn(() => imageData),
    putImageData: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    globalCompositeOperation: 'source-over',
    strokeStyle: '#ffffff',
    lineWidth: 1,
    lineCap: 'round',
    lineJoin: 'round',
    fillStyle: '#000000',
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 512,
    bottom: 512,
    width: 512,
    height: 512,
    toJSON: () => undefined,
  });
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
    'data:image/png;base64,mask',
  );
}

function drawMask(canvas: HTMLCanvasElement) {
  fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 40, clientY: 40 });
  fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 80, clientY: 80 });
  fireEvent.pointerUp(canvas, { pointerId: 1, clientX: 80, clientY: 80 });
}

describe('InpaintPanel', () => {
  beforeEach(() => {
    apiMocks.get.mockImplementation((url: string) => {
      if (url.includes('/draw/inpaint/jobs/')) {
        return Promise.resolve({
          data: {
            job_id: 'job-1',
            status: 'queued',
            progress: { completed: 0, total: 2 },
            results: [],
          },
        });
      }
      return Promise.resolve({ data: { models: [], loras: [] } });
    });
    apiMocks.post.mockResolvedValue({ data: { job_id: 'job-1' } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    apiMocks.get.mockReset();
    apiMocks.post.mockReset();
  });

  it('shows the source, mask and candidate workflow before a source is chosen', () => {
    render(<InpaintPanel />);

    expect(screen.getByText('局部重绘')).toBeInTheDocument();
    expect(screen.getByText('上传底图')).toBeInTheDocument();
    expect(screen.getByText('从图片库选择')).toBeInTheDocument();
    expect(screen.getByText('Mask 画布')).toBeInTheDocument();
    expect(screen.getByText('候选结果')).toBeInTheDocument();
    expect(screen.getByText('先选择底图')).toBeInTheDocument();
  });

  it('draws a pointer mask and submits the inherited structured prompt document', async () => {
    mockSourceImage();
    mockCanvas();
    render(<InpaintPanel initialSource={SOURCE} />);

    expect(await screen.findByText('512 × 512')).toBeInTheDocument();
    expect(screen.getByText('已带入当前组结构化提示词')).toBeInTheDocument();
    const canvas = document.querySelector('.inpaint-canvas') as HTMLCanvasElement;
    const submit = screen.getByRole('button', { name: '生成 2 个候选' });
    expect(submit).toBeDisabled();

    drawMask(canvas);

    expect(screen.getByText('已画 mask')).toBeInTheDocument();
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => {
      expect(apiMocks.post).toHaveBeenCalledWith(
        '/draw/inpaint/jobs',
        expect.objectContaining({
          source_record_id: 42,
          prompt: SOURCE.prompt,
          prompt_document: SOURCE.promptDocument,
          mask_base64: 'data:image/png;base64,mask',
        }),
      );
    });
  });

  it('detaches the structured document when the user edits inherited text', async () => {
    mockSourceImage();
    mockCanvas();
    render(<InpaintPanel initialSource={SOURCE} />);

    const prompt = await screen.findByPlaceholderText('描述底图/当前组的整体内容');
    fireEvent.change(prompt, { target: { value: 'manual replacement prompt' } });
    expect(screen.queryByText('已带入当前组结构化提示词')).not.toBeInTheDocument();

    const canvas = document.querySelector('.inpaint-canvas') as HTMLCanvasElement;
    drawMask(canvas);
    fireEvent.click(screen.getByRole('button', { name: '生成 2 个候选' }));

    await waitFor(() => {
      const payload = apiMocks.post.mock.calls[0]?.[1];
      expect(payload.prompt).toBe('manual replacement prompt');
      expect(payload).not.toHaveProperty('prompt_document');
    });
  });
});
