import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { drawStore, type DrawGroup } from '../stores/draw';
import PromptSetsDrawer from './PromptSetsDrawer';

function drawGroup(id: string, prompt: string): DrawGroup {
  return {
    id,
    prompt,
    prompt_document: null,
    mode: 'legacy',
    body_profile: {
      height_frame: 'none',
      body_build: 'none',
    },
    count: 1,
  };
}

afterEach(() => {
  drawStore.groups = [drawGroup('group-1', '')];
});

describe('PromptSetsDrawer', () => {
  it('keeps hook order stable when the active group is removed', () => {
    const first = drawGroup('group-1', 'first');
    const second = drawGroup('group-2', 'second');
    drawStore.groups = [first, second];

    const view = render(
      <PromptSetsDrawer open={false} onClose={vi.fn()} activeGroupId={second.id} />,
    );

    drawStore.groups = [first];

    expect(() =>
      view.rerender(
        <PromptSetsDrawer open={false} onClose={vi.fn()} activeGroupId={second.id} />,
      ),
    ).not.toThrow();
  });
});
