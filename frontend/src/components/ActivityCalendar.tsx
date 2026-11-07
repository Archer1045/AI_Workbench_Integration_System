// 活动日历：一张月历里画六类条目 —— 在办活动 / 交换所期 / 已确认日程 / 候选日程 /
// 日服·参考（灰显）/ 维护窗口。
//
// 口径（2026-10-15 定）：
//   * **日服条目只作参考**，灰显并标注，永不参与「下一个活动」的回答；
//   * 维护窗口来自单独的 `maintenance_cn.json`（不进活动日程，避免污染回答）；
//   * 「标为已确认」永远由人点（这里只显示候选，确认去「接下来的活动」卡片上点）。
import { Alert, Button, Modal, Space, Tag } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadSchedule, type EventView, type ScheduleResponse } from '../stores/gameAssistant';

type Kind = 'current' | 'shop' | 'confirmed' | 'candidate' | 'jp' | 'maintenance';

interface CalendarEntry {
  key: string;
  kind: Kind;
  title: string;
  start: string;
  end: string | null;
  detail: string;
  sourceUrl?: string;
}

const KIND_META: Record<Kind, { label: string; className: string }> = {
  current: { label: '在办活动', className: 'current' },
  shop: { label: '交换所期', className: 'shop' },
  confirmed: { label: '已确认日程', className: 'confirmed' },
  candidate: { label: '候选日程', className: 'candidate' },
  jp: { label: '日服·参考', className: 'jp' },
  maintenance: { label: '维护窗口', className: 'maintenance' },
};

const KIND_ORDER: Kind[] = ['current', 'shop', 'confirmed', 'candidate', 'jp', 'maintenance'];

function fmt(value: string | null | undefined): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '未写';
}

export default function ActivityCalendar({ eventView }: { eventView: EventView | null }) {
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [detail, setDetail] = useState<CalendarEntry | null>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      setSchedule(await loadSchedule());
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取日程失败');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const entries = useMemo<CalendarEntry[]>(() => {
    const list: CalendarEntry[] = [];
    const event = eventView?.event;
    if (event) {
      list.push({
        key: `current-${event.event_id}`,
        kind: 'current',
        title: event.title,
        start: event.starts_at,
        end: event.ends_at,
        detail: `活动本体：${fmt(event.starts_at)} ~ ${fmt(event.ends_at)}（副本到 ${fmt(event.ends_at)} 为止）`,
      });
      if (event.exchange_ends_at) {
        list.push({
          key: `shop-${event.event_id}`,
          kind: 'shop',
          title: `${event.title} · 交换所`,
          start: event.ends_at,
          end: event.exchange_ends_at,
          detail: `交换所还开着：到 ${fmt(event.exchange_ends_at)} 为止（副本已关，素材还能换）`,
        });
      }
    }
    for (const item of schedule?.items ?? []) {
      list.push({
        key: `sched-${item.event_id}`,
        kind: item.status === 'confirmed' ? 'confirmed' : 'candidate',
        title: item.title,
        start: item.starts_at ?? '',
        end: item.ends_at,
        detail: [
          item.starts_at ? `开始：${fmt(item.starts_at)}` : '开始时间待人工核对',
          item.ends_at ? `结束：${fmt(item.ends_at)}` : '结束时间待人工核对',
          item.source_title ? `来源：${item.source_title}` : '',
          item.note,
          item.status === 'confirmed' ? '已确认（可用于「下一个活动」回答）' : '候选：要在「接下来的活动」卡片上点「标为已确认」才会被采用',
        ]
          .filter(Boolean)
          .join('；'),
        sourceUrl: item.source_url,
      });
    }
    for (const item of schedule?.japanese_reference?.items ?? []) {
      list.push({
        key: `jp-${item.title}-${item.starts_at}`,
        kind: 'jp',
        title: item.title,
        start: item.starts_at,
        end: item.ends_at,
        detail: `日服·参考（${item.type ?? '未标类型'}）：${fmt(item.starts_at)} ~ ${fmt(item.ends_at)}。不代表国服排期。`,
      });
    }
    for (const item of schedule?.maintenance ?? []) {
      list.push({
        key: `maint-${item.announcement_id}`,
        kind: 'maintenance',
        title: item.title,
        start: item.starts_at,
        end: item.ends_at,
        detail: `${fmt(item.starts_at)} ~ ${fmt(item.ends_at)}（预计）。${item.note ?? ''}`,
        sourceUrl: item.source_url,
      });
    }
    return list.filter((entry) => entry.start);
  }, [eventView, schedule]);

  const grid = useMemo(() => {
    const first = month.startOf('month');
    const offset = (first.day() + 6) % 7;   // 周一开头
    const start = first.subtract(offset, 'day');
    return Array.from({ length: 42 }, (_value, index) => start.add(index, 'day'));
  }, [month]);

  const entriesOn = useCallback(
    (day: Dayjs) => {
      const dayStart = day.startOf('day');
      const dayEnd = day.endOf('day');
      return entries
        .filter((entry) => {
          const begins = dayjs(entry.start);
          const ends = entry.end ? dayjs(entry.end) : begins;
          return begins.isBefore(dayEnd) && ends.isAfter(dayStart);
        })
        // 排序：**当天开始/截止**的排前面（那才是"这天发生了什么"），整天都在进行的长条排后面
        .map((entry) => {
          const begins = dayjs(entry.start);
          const ends = entry.end ? dayjs(entry.end) : begins;
          const startsToday = begins.isSame(day, 'day');
          const endsToday = ends.isSame(day, 'day');
          return { entry, startsToday, endsToday };
        })
        .sort((left, right) => {
          const weight = (item: { startsToday: boolean; endsToday: boolean; entry: CalendarEntry }) =>
            (item.startsToday || item.endsToday ? 0 : 10) + KIND_ORDER.indexOf(item.entry.kind);
          return weight(left) - weight(right);
        })
        .map((item) => ({
          ...item.entry,
          marker: item.startsToday && item.endsToday
            ? '开始·截止'
            : item.startsToday
              ? '开始'
              : item.endsToday
                ? '截止'
                : '',
        }));
    },
    [entries],
  );

  return (
    <div className="ga-section-stack">
      <div className="ga-heading">
        <div>
          <h2>活动日历</h2>
          <p className="ga-small ga-muted">
            在办活动 / 交换所期 / 已确认日程 / 候选日程 / 日服·参考 / 维护窗口。日期口径 +08:00。
          </p>
        </div>
        <Space wrap>
          <Button size="small" icon={<LeftOutlined />} onClick={() => setMonth((m) => m.subtract(1, 'month'))} />
          <Button size="small" onClick={() => setMonth(dayjs())}>本月</Button>
          <Button size="small" icon={<RightOutlined />} onClick={() => setMonth((m) => m.add(1, 'month'))} />
          <Button size="small" onClick={() => void refresh()}>刷新</Button>
          <Tag>{month.format('YYYY 年 M 月')}</Tag>
        </Space>
      </div>

      <Space wrap>
        {KIND_ORDER.map((kind) => (
          <span key={kind} className={`ga-cal-legend ga-cal-${kind}`}>
            {KIND_META[kind].label}
          </span>
        ))}
      </Space>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <div className="ga-cal">
        {['一', '二', '三', '四', '五', '六', '日'].map((day) => (
          <div key={day} className="ga-cal-head">{day}</div>
        ))}
        {grid.map((day) => {
          const dayEntries = entriesOn(day);
          const outside = day.month() !== month.month();
          return (
            <div key={day.format('YYYY-MM-DD')} className={`ga-cal-cell${outside ? ' outside' : ''}`}>
              <div className="ga-cal-date">{day.format('D')}</div>
              {dayEntries.slice(0, 3).map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  className={`ga-cal-chip ga-cal-${entry.kind}${entry.marker ? ' ga-cal-edge' : ''}`}
                  title={`${entry.title}${entry.marker ? `（${entry.marker}）` : ''}`}
                  onClick={() => setDetail(entry)}
                >
                  {entry.marker ? <b>{entry.marker}</b> : null}
                  {entry.title}
                </button>
              ))}
              {dayEntries.length > 3 ? (
                <span className="ga-small ga-muted">还有 {dayEntries.length - 3} 条</span>
              ) : null}
            </div>
          );
        })}
      </div>

      <span className="ga-small ga-muted">
        {schedule?.japanese_reference?.note ??
          '日服·参考：日服比国服早约 12 个月，只作参考、不代表国服排期。'}
        {schedule?.japanese_reference?.fetched_at
          ? `（日服表抓取于 ${fmt(schedule.japanese_reference.fetched_at)}）`
          : ''}
      </span>

      <Modal
        open={Boolean(detail)}
        title={detail ? `${KIND_META[detail.kind].label}：${detail.title}` : ''}
        footer={null}
        onCancel={() => setDetail(null)}
      >
        {detail ? (
          <div className="ga-small">
            <p>{detail.detail}</p>
            {detail.sourceUrl ? (
              <p>
                来源：<a href={detail.sourceUrl} target="_blank" rel="noreferrer">{detail.sourceUrl}</a>
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
