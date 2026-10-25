import { describe, expect, it } from 'vitest';

import { endedSummaryLabel, isEnded, shopCountdownLabel, shopWarning } from './gameAssistantLifecycle';

describe('活动生命周期文案', () => {
  it('区分进行中与已结束', () => {
    expect(isEnded('running')).toBe(false);
    expect(isEnded('ended_shop_open')).toBe(true);
    expect(isEnded('closed')).toBe(true);
    expect(isEnded(undefined)).toBe(false);
  });

  it('交换所还开着时报剩余天数（含截止时刻）', () => {
    const label = shopCountdownLabel({
      ends_at: '2026-10-22T13:59:00+08:00', state: 'open', days_left: 5, ends_today: false,
    });
    expect(label).toBe('商店剩余兑换时间 5 天（截止 10-22 13:59）');
    // 折叠条左侧已经有「已结束」标签，右半句只讲商店倒计时（不重复说"已结束"）
    expect(endedSummaryLabel({
      ends_at: '2026-10-22T13:59:00+08:00', state: 'open', days_left: 5, ends_today: false,
    })).toBe('商店剩余兑换时间 5 天（截止 10-22 13:59）');
  });

  it('最后一天改口径，不出现「剩余 0 天」', () => {
    expect(shopCountdownLabel({
      ends_at: '2026-10-22T13:59:00+08:00', state: 'open', days_left: 1, ends_today: true,
    })).toBe('商店今天 13:59 截止');
  });

  it('关闭 / 没有交换所 / 没数据时都写「商店已关闭」', () => {
    expect(shopCountdownLabel({ ends_at: null, state: 'none', days_left: null, ends_today: false }))
      .toBe('商店已关闭');
    expect(shopCountdownLabel({
      ends_at: '2026-10-22T13:59:00+08:00', state: 'closed', days_left: null, ends_today: false,
    })).toBe('商店已关闭');
    expect(shopCountdownLabel(undefined)).toBe('商店已关闭');
  });

  it('剩 ≤3 天或最后一天给警示色', () => {
    expect(shopWarning({ ends_at: null, state: 'open', days_left: 7, ends_today: false })).toBe(false);
    expect(shopWarning({ ends_at: null, state: 'open', days_left: 3, ends_today: false })).toBe(true);
    expect(shopWarning({ ends_at: null, state: 'open', days_left: 1, ends_today: true })).toBe(true);
    expect(shopWarning({ ends_at: null, state: 'closed', days_left: null, ends_today: false })).toBe(false);
  });
});
