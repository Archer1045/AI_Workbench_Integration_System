import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createDrawGroup } from '../stores/draw';
import DrawPreflightDrawer from './DrawPreflightDrawer';

describe('DrawPreflightDrawer', () => {
  it('summarizes enabled groups, counts and prompt issues', () => {
    const group = createDrawGroup('masterpiece, city', 'group-1', 'legacy');
    group.count = 3;
    render(
      <DrawPreflightDrawer
        open
        onClose={() => undefined}
        groups={[group]}
        previews={{
          'group-1': {
            prompt: 'masterpiece, city',
            errors: [],
            warnings: ['测试提醒'],
          },
        }}
        model="model.safetensors"
        width={1024}
        height={1024}
        steps={20}
        cfg={5}
        loras={['lora.safetensors']}
        negativePrompt="low quality"
      />,
    );

    expect(screen.getByText('可提交组')).toBeInTheDocument();
    expect(screen.getByText('计划张数')).toBeInTheDocument();
    expect(screen.getByText('第 1 组：测试提醒')).toBeInTheDocument();
  });
});
