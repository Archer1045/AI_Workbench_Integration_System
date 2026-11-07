import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import TagCompareTable from './TagCompareTable';

const rows = [
  { tag: '1girl', translation: '女孩' },
  { tag: 'long hair', translation: '长发' },
  { tag: 'unknown_tag', translation: '' },
];

describe('TagCompareTable', () => {
  it('renders all tags and deduplicates', () => {
    render(<TagCompareTable rows={[...rows, { tag: '1girl', translation: '女孩' }]} />);
    expect(screen.getAllByText('1girl')).toHaveLength(1);
    expect(screen.getByText('long hair')).toBeInTheDocument();
    expect(screen.getByText('unknown_tag')).toBeInTheDocument();
  });

  it('filters tags by search keyword', async () => {
    const user = userEvent.setup();
    render(<TagCompareTable rows={rows} />);
    await user.type(screen.getByPlaceholderText('搜索标签'), 'long');
    expect(screen.queryByText('1girl')).not.toBeInTheDocument();
    expect(screen.getByText('long hair')).toBeInTheDocument();
  });

  it('switches to original highlight mode with matched segments', async () => {
    const user = userEvent.setup();
    render(<TagCompareTable rows={rows} originalText="1girl, long hair, custom style" />);
    await user.click(screen.getByText('原文高亮'));
    expect(screen.getByText('1girl')).toBeInTheDocument();
    expect(screen.getByText('custom style')).toBeInTheDocument();
  });
});
