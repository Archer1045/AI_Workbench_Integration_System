import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { createDrawGroup } from '../stores/draw';
import DrawPromptHistoryDrawer from './DrawPromptHistoryDrawer';

describe('DrawPromptHistoryDrawer', () => {
  it('shows the version diff and restores the selected version', () => {
    const group = createDrawGroup('current prompt', 'group-1', 'legacy');
    const onRestore = vi.fn();
    render(
      <DrawPromptHistoryDrawer
        open
        onClose={() => undefined}
        group={group}
        versions={[
          {
            id: 'version-1',
            createdAt: '2026-10-26T04:00:00+08:00',
            mode: 'legacy',
            prompt: 'older, city',
            document: null,
          },
        ]}
        currentPrompt="current, prompt"
        onRestore={onRestore}
      />,
    );

    expect(screen.getByText('current')).toBeInTheDocument();
    expect(screen.getByText('prompt')).toBeInTheDocument();
    expect(screen.getByText('older')).toBeInTheDocument();
    expect(screen.getByText('city')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '恢复此版本' }));
    expect(onRestore).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'version-1' }),
    );
  });
});
