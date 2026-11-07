// 后续活动日程卡片：confirmed（核对过来源）才会被「下一个活动」回答采用。
//
// 口径：候选日程只是记录，**不能**自动变成已确认；没有任何已确认日程时，助手会明确回答
// 「暂无已确认日程」，绝不用日服进度或模型记忆推断国服排期。
import { Alert, Button, Card, Empty, Input, Space, Tag, Tooltip, message } from 'antd';
import {
  CheckCircleOutlined,
  CloudDownloadOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useCallback, useEffect, useState } from 'react';
import dayjs from 'dayjs';
import {
  deleteScheduleEvent,
  loadSchedule,
  refreshOfficialSchedule,
  upsertScheduleEvent,
  type ScheduleResponse,
} from '../stores/gameAssistant';

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '时间待定';
}

export default function ScheduleCard({ onOpenCalendar }: { onOpenCalendar?: () => void }) {
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  // 摘要模式（2026-10-15 布局优化）：默认只留一行「下个活动 + 计数 + 两个入口」，
  // 候选列表与手工登记表单收进「维护面板」；展开状态记在本地（跟活动折叠同一套做法）。
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [sourceTitle, setSourceTitle] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [pulling, setPulling] = useState(false);
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

  useEffect(() => {
    setExpanded(window.localStorage.getItem('ga.schedulePanelOpen') === '1');
  }, []);

  const toggleExpanded = () => {
    setExpanded((current) => {
      const next = !current;
      window.localStorage.setItem('ga.schedulePanelOpen', next ? '1' : '0');
      return next;
    });
  };

  const handleAdd = async (confirm: boolean) => {
    if (!title.trim()) {
      message.warning('先填活动名');
      return;
    }
    setSaving(true);
    try {
      await upsertScheduleEvent({
        event_id: `evt-${title.trim()}-${startsAt || 'tbd'}`,
        title: title.trim(),
        starts_at: startsAt ? dayjs(startsAt).toISOString() : null,
        ends_at: endsAt ? dayjs(endsAt).toISOString() : null,
        source_title: sourceTitle.trim(),
        source_url: sourceUrl.trim(),
        confirm,
      });
      message.success(confirm ? '已记为已确认日程' : '已记为候选日程');
      setTitle('');
      setStartsAt('');
      setEndsAt('');
      setSourceTitle('');
      setSourceUrl('');
      await refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async (eventId: string, item: ScheduleResponse['items'][number]) => {
    try {
      await upsertScheduleEvent({
        event_id: item.event_id,
        title: item.title,
        starts_at: item.starts_at,
        ends_at: item.ends_at,
        source_title: item.source_title,
        source_url: item.source_url,
        note: item.note,
        confirm: true,
      });
      await refresh();
      void eventId;
    } catch (err) {
      message.error(err instanceof Error ? err.message : '标记失败');
    }
  };

  const handleDelete = async (eventId: string) => {
    try {
      await deleteScheduleEvent(eventId);
      await refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // 「拉取官方公告」：只把公告落成**候选**（永不自动确认），顺带刷日服参考的缓存。
  const handlePullOfficial = async () => {
    setPulling(true);
    try {
      const result = await refreshOfficialSchedule();
      const stale = result.stale?.length ?? 0;
      message.success(
        `已拉取官方公告：新增 ${result.added.length} 条候选 · 更新 ${result.updated.length} · ` +
          `跳过 ${result.skipped.length + stale}（已确认/已过期）`,
      );
      if (result.errors.length) message.warning(result.errors.slice(0, 2).join('；'));
      if (result.mooncell && !result.mooncell.ok && result.mooncell.error) {
        message.warning(result.mooncell.error);
      }
      await refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '拉取失败');
    } finally {
      setPulling(false);
    }
  };

  const items = schedule?.items ?? [];
  const candidates = items.filter((item) => item.status !== 'confirmed');
  const nextUpcoming = (schedule?.confirmed_upcoming ?? [])[0] ?? null;
  const japaneseReference = schedule?.japanese_reference;

  // 「还有 N 天开始」——按自然日算，避免 19:00 开始的活动在当天显示成 "0 天"。
  const daysUntil = (value: string | null): number | null =>
    value ? dayjs(value).startOf('day').diff(dayjs().startOf('day'), 'day') : null;

  return (
    <>
      <div className="ga-slim-row">
        <div className="ga-row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center', minWidth: 0 }}>
          {schedule ? (
            <>
              <Tag color={schedule.confirmed_count > 0 ? 'green' : 'default'}>
                已确认 {schedule.confirmed_count}
              </Tag>
              <Tag color={candidates.length ? 'orange' : 'default'}>候选 {candidates.length}</Tag>
            </>
          ) : null}
          {nextUpcoming ? (
            <span className="ga-small">
              下个活动：<strong>{nextUpcoming.title}</strong>
              <span className="ga-muted">
                {' '}
                {formatTime(nextUpcoming.starts_at)} 开始
                {(() => {
                  const days = daysUntil(nextUpcoming.starts_at);
                  if (days === null) return '';
                  return days > 0 ? `（还有 ${days} 天）` : days === 0 ? '（今天）' : '（已开始）';
                })()}
              </span>
            </span>
          ) : (
            <span className="ga-small ga-muted">暂无已确认日程（等官方公告，不会用日服进度推国服排期）</span>
          )}
        </div>
        <Space wrap size={6}>
          <Button size="small" onClick={toggleExpanded}>
            {expanded ? '收起维护面板' : '展开维护面板'}
          </Button>
          {onOpenCalendar ? (
            <Button size="small" onClick={onOpenCalendar}>
              去日历
            </Button>
          ) : null}
        </Space>
      </div>
      {expanded ? (
        <Card
          size="small"
          title="接下来的活动（维护面板）"
          extra={
            <Space>
              <Button size="small" icon={<ReloadOutlined />} onClick={() => void refresh()}>
                刷新
              </Button>
            </Space>
          }
        >
      <Alert
        type={schedule?.confirmed_count ? 'success' : 'info'}
        showIcon
        message={
          schedule?.confirmed_count
            ? '助手回答「下一个活动」时只会用下面这些已确认日程。'
            : '暂无已确认日程：助手会明确回答「暂无」（不会用日服进度或模型记忆推断）。'
        }
      />
      {error ? <Alert type="error" showIcon message={error} /> : null}
      <div className="ga-soft ga-side-card" style={{ marginBottom: 10 }}>
        <div className="ga-row ga-between">
          <strong>下个活动</strong>
          <Space>
            {japaneseReference?.fetched_at ? (
              <span className="ga-small ga-muted">日服参考更新于 {formatTime(japaneseReference.fetched_at)}</span>
            ) : null}
            <Button
              size="small"
              icon={<CloudDownloadOutlined />}
              loading={pulling}
              onClick={() => void handlePullOfficial()}
            >
              拉取官方公告
            </Button>
          </Space>
        </div>
        {nextUpcoming ? (
          <div className="ga-row">
            <span className="ga-pill green">已确认</span>
            <span className="ga-schedule-title">{nextUpcoming.title}</span>
            <span className="ga-small ga-muted">
              {formatTime(nextUpcoming.starts_at)} 开始
              {(() => {
                const days = daysUntil(nextUpcoming.starts_at);
                if (days === null) return '';
                return days > 0 ? `（还有 ${days} 天）` : days === 0 ? '（今天）' : '（已开始）';
              })()}
              {' · '}
              {nextUpcoming.ends_at ? `到 ${formatTime(nextUpcoming.ends_at)}` : '常驻 / 公告没写结束'}
            </span>
          </div>
        ) : (
          <span className="ga-small ga-muted">
            暂无已确认日程（等官方公告；不会用日服进度或模型记忆推国服排期）
          </span>
        )}
        {japaneseReference && japaneseReference.items.length > 0 ? (
          <div className="ga-small ga-muted">
            <div>日服·参考（约一年前同期，只帮你预判会遇到什么）：</div>
            {japaneseReference.items.slice(0, 4).map((item) => (
              <div key={`${item.title}-${item.starts_at}`}>
                · {formatTime(item.starts_at)} {item.type ? `[${item.type}] ` : ''}
                {item.title}
              </div>
            ))}
            <div>{japaneseReference.note}</div>
          </div>
        ) : null}
      </div>

      <div className="ga-schedule-list">
        {items.length === 0 ? (
          <Empty description="还没有登记任何日程" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          items.map((item) => (
            <div className="ga-schedule-row" key={item.event_id}>
              <Tag color={item.status === 'confirmed' ? 'green' : 'orange'}>
                {item.status === 'confirmed' ? '已确认' : '候选'}
              </Tag>
              <span className="ga-schedule-title">{item.title}</span>
              <span className="ga-small ga-muted">
                {formatTime(item.starts_at)} ~ {formatTime(item.ends_at)}
              </span>
              {item.source_title || item.source_url ? (
                <span className="ga-small ga-muted ga-schedule-source">
                  来源：{item.source_url ? <a href={item.source_url}>{item.source_title || item.source_url}</a> : item.source_title}
                </span>
              ) : (
                <Tooltip title="没有来源的日程只能当候选；核对官方公告后再标为已确认">
                  <span className="ga-small ga-muted">无来源</span>
                </Tooltip>
              )}
              <Space size={4}>
                {item.status !== 'confirmed' ? (
                  <Button
                    size="small"
                    icon={<CheckCircleOutlined />}
                    onClick={() => void handleConfirm(item.event_id, item)}
                  >
                    标为已确认
                  </Button>
                ) : null}
                <Button size="small" danger icon={<DeleteOutlined />} onClick={() => void handleDelete(item.event_id)} />
              </Space>
            </div>
          ))
        )}
      </div>
      <div className="ga-schedule-form">
        <Input placeholder="活动名（例如：某某联动活动）" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Input
          placeholder="开始时间，例如 2026-10-16 18:00"
          value={startsAt}
          onChange={(e) => setStartsAt(e.target.value)}
        />
        <Input
          placeholder="结束时间，例如 2026-10-30 13:59"
          value={endsAt}
          onChange={(e) => setEndsAt(e.target.value)}
        />
        <Input
          placeholder="来源标题，例如 国服官方公告 2026-10-15"
          value={sourceTitle}
          onChange={(e) => setSourceTitle(e.target.value)}
        />
        <Input
          placeholder="来源链接（可留空）"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
        />
        <Space wrap>
          <Button icon={<PlusOutlined />} loading={saving} onClick={() => void handleAdd(false)}>
            记为候选
          </Button>
          <Button type="primary" icon={<PlusOutlined />} loading={saving} onClick={() => void handleAdd(true)}>
            记为已确认（已核对来源）
          </Button>
        </Space>
      </div>
          {schedule?.path ? <span className="ga-small ga-muted">存储：{schedule.path}</span> : null}
        </Card>
      ) : null}
    </>
  );
}
