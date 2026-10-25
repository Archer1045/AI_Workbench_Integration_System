import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import PromptAgent from './PromptAgent';
import { promptStore, setReverseOptions } from '../stores/prompt';

describe('PromptAgent reverse-mode control', () => {
  beforeEach(() => {
    localStorage.clear();
    setReverseOptions('hybrid', 0.35);
  });

  it('switches to the visual-model mode without crashing', async () => {
    render(<PromptAgent />);
    fireEvent.click(screen.getByRole('radio', { name: '视觉模型' }));
    expect(promptStore.reverseMode).toBe('vlm');
  });

  it('switches back to wd14 and shows the threshold input again', async () => {
    render(<PromptAgent />);
    fireEvent.click(screen.getByRole('radio', { name: '视觉模型' }));
    fireEvent.click(screen.getByRole('radio', { name: 'WD14 标签' }));
    expect(promptStore.reverseMode).toBe('wd14');
    expect(screen.getByText('WD14 阈值')).toBeInTheDocument();
  });
});
