import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoraItem } from '../api';
import DrawLoraSelector from './DrawLoraSelector';

const items: LoraItem[] = [
  {
    name: 'style-a.safetensors',
    size_mb: 120,
    purpose: 'drawing',
    compatible: true,
  },
  {
    name: 'character-b.safetensors',
    size_mb: 240,
    purpose: 'unknown',
    compatible: false,
    incompatible_reason: 'base mismatch',
  },
  {
    name: 'video-c.safetensors',
    size_mb: 300,
    purpose: 'video',
    compatible: true,
  },
];

const defaults = {
  model: 0.8,
  clip: 0.8,
  min: 0,
  max: 1.5,
  step: 0.05,
};

function props(selected: string[] = []) {
  return {
    items,
    selected,
    strengths: {
      'style-a.safetensors': { model: 0.7, clip: 0.6 },
    },
    defaults,
    loading: false,
    comboMenuItems: [],
    onComboMenu: vi.fn(),
    onToggle: vi.fn(),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onStrengthChange: vi.fn(),
    onRefresh: vi.fn(),
    onDelete: vi.fn(),
  };
}

describe('DrawLoraSelector', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts collapsed with a persistent selected summary', () => {
    render(<DrawLoraSelector {...props(['style-a.safetensors'])} />);

    expect(screen.queryByPlaceholderText('搜索 LoRA')).not.toBeInTheDocument();
    expect(screen.getByText(/style-a\.safetensors · 模型 0\.7 \/ CLIP 0\.6/)).toBeInTheDocument();
    expect(screen.getByText('1 个模型已加入当前组合')).toBeInTheDocument();
  });

  it('expands into a searchable selector and reveals incompatible items explicitly', () => {
    const callbacks = props();
    render(<DrawLoraSelector {...callbacks} />);

    fireEvent.click(screen.getByRole('button', { name: /选择 LoRA/ }));
    expect(screen.getByPlaceholderText('搜索 LoRA')).toBeInTheDocument();
    expect(screen.getByText(/style-a\.safetensors/)).toBeInTheDocument();
    expect(screen.queryByText(/character-b\.safetensors/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('switch'));
    expect(screen.getByText(/character-b\.safetensors/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('搜索 LoRA'), {
      target: { value: 'character' },
    });
    expect(screen.queryByText(/style-a\.safetensors/)).not.toBeInTheDocument();
    expect(screen.getByText(/character-b\.safetensors/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('搜索 LoRA'), {
      target: { value: 'style' },
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /style-a\.safetensors/ }));
    expect(callbacks.onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'style-a.safetensors' }),
      true,
    );
  });

  it('separates selected-strength controls from the resource library', () => {
    const callbacks = props(['style-a.safetensors']);
    render(<DrawLoraSelector {...callbacks} />);

    fireEvent.click(screen.getByRole('button', { name: /选择 LoRA/ }));

    expect(screen.getByText('已选组合')).toBeInTheDocument();
    expect(screen.getByText('选择模型')).toBeInTheDocument();
    expect(screen.getAllByText(/style-a\.safetensors/).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '移除 style-a.safetensors' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '清空' }));
    expect(callbacks.onClear).toHaveBeenCalledTimes(1);
  });

  it('persists expansion and search state', () => {
    render(<DrawLoraSelector {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: /选择 LoRA/ }));
    fireEvent.change(screen.getByPlaceholderText('搜索 LoRA'), {
      target: { value: 'style' },
    });

    const saved = JSON.parse(
      localStorage.getItem('rider-studio:lora-selector-v1') || '{}',
    );
    expect(saved.expanded).toBe(true);
    expect(saved.search).toBe('style');
  });
});
