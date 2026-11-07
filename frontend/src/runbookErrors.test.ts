import { describe, expect, it } from 'vitest';
import { runbookRequestErrorMessage } from './runbookErrors';

describe('runbookRequestErrorMessage', () => {
  it('prefers the backend plan compilation detail', () => {
    expect(
      runbookRequestErrorMessage({
        response: {
          data: {
            detail: '计划编译不过：第 1 回合排了 2 个出手卡位，必须正好 3 个',
          },
        },
      }),
    ).toBe('计划编译不过：第 1 回合排了 2 个出手卡位，必须正好 3 个');
  });

  it('formats structured validation messages', () => {
    expect(
      runbookRequestErrorMessage({
        response: {
          data: {
            detail: [
              { msg: 'name 不能为空' },
              { msg: 'team 格式错误' },
            ],
          },
        },
      }),
    ).toBe('name 不能为空；team 格式错误');
  });

  it('falls back to the underlying error message', () => {
    expect(runbookRequestErrorMessage(new Error('Network Error'))).toBe(
      'Network Error',
    );
  });
});
