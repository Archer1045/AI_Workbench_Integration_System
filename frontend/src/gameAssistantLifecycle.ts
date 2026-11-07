// 活动生命周期文案（纯函数，便于单测）——口径与后端 `service.event_status` / `shop_state` 一致：
//   * running：进行中；
//   * ended_shop_open：活动已结束，但交换所还开着（副本不能再刷、素材还能换，所以只折叠不删）；
//   * closed：都结束了。
// 天数由后端 `shop.days_left` 给（向上取整）；不足 24 小时用 `ends_today` 让文案改口径，
// 避免出现「剩余 0 天」。
import dayjs from 'dayjs';

import type { EventShopState, EventStatus } from './stores/gameAssistant';

export function isEnded(status: EventStatus | undefined): boolean {
  return status === 'ended_shop_open' || status === 'closed';
}

/** 折叠条右边那半句：`商店剩余兑换时间 5 天（截止 10-22 13:59）`。 */
export function shopCountdownLabel(shop: EventShopState | undefined): string {
  if (!shop || shop.state !== 'open' || !shop.ends_at) {
    return '商店已关闭';
  }
  const moment = dayjs(shop.ends_at);
  if (shop.ends_today) {
    return `商店今天 ${moment.format('HH:mm')} 截止`;
  }
  return `商店剩余兑换时间 ${shop.days_left} 天（截止 ${moment.format('MM-DD HH:mm')}）`;
}

/** 折叠条右半句。左边已经有「已结束」标签，所以这里**不重复**说"已结束"。 */
export function endedSummaryLabel(shop: EventShopState | undefined): string {
  return shopCountdownLabel(shop);
}

export function shopWarning(shop: EventShopState | undefined): boolean {
  return Boolean(shop && shop.state === 'open' && (shop.ends_today || (shop.days_left ?? 99) <= 3));
}
