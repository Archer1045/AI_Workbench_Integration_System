import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('../api', () => ({
  api: apiMocks,
}));

vi.mock('resso', () => ({
  default: (initialState: unknown) => initialState,
}));

import { servicesStore, toggleService } from './services';

describe('services store', () => {
  beforeEach(() => {
    apiMocks.get.mockResolvedValue({
      data: { ollama: true, comfyui: false },
    });
    apiMocks.post.mockReset();
    servicesStore.ollama = false;
    servicesStore.comfyui = false;
    servicesStore.loading = { ollama: false, comfyui: false };
  });

  it('keeps service loading independent', async () => {
    let finishStart: (() => void) | undefined;
    apiMocks.post.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishStart = resolve;
        }),
    );

    const startingOllama = toggleService('ollama', true);
    expect(servicesStore.loading.ollama).toBe(true);
    expect(servicesStore.loading.comfyui).toBe(false);

    finishStart?.();
    await startingOllama;

    expect(servicesStore.loading.ollama).toBe(false);
    expect(servicesStore.loading.comfyui).toBe(false);
    expect(apiMocks.post).toHaveBeenCalledWith('/services/start', {
      name: 'ollama',
    });
  });
});
