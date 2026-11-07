import { Column } from '@ant-design/charts';
import { Tag } from 'antd';

import type { DashboardV3Data } from '../api';
import { uiStore } from '../stores/ui';

function renderStatusTags(status?: Record<string, number>) {
  if (!status || Object.keys(status).length === 0) return <Tag>暂无</Tag>;
  return Object.entries(status).map(([key, value]) => (
    <Tag key={key}>{key}: {value}</Tag>
  ));
}

function formatNumber(value?: number | null, digits = 4): string {
  if (value == null) return '-';
  return Number(value).toFixed(digits).replace(/\.?0+$/, '');
}

export default function DashboardOverview({
  data,
  loading,
  sort,
}: {
  data: DashboardV3Data | null;
  loading: boolean;
  sort: 'default' | 'recent';
}) {
  if (loading && !data) return <div className="train-status-text">加载中...</div>;

  const primary = [
    {
      key: 'draw',
      score: data?.overview.draw.total || 0,
      node: (
        <div className="module-card" onClick={() => { uiStore.activeTab = 'draw'; }}>
          <div className="module-card-header"><b>AI 绘画</b><Tag>{data?.overview.draw.total ?? 0} 张</Tag></div>
          <div className="module-card-stats">
            <Tag color="green">成功 {data?.overview.draw.success_count ?? 0}</Tag>
            <Tag color="red">失败 {data?.overview.draw.error_count ?? 0}</Tag>
            <Tag>批次 {data?.draw.batch_count ?? 0}</Tag>
          </div>
          <div className="module-card-footer">
            <span>平均 {data?.overview.draw.avg_duration ?? 0}s</span>
            <span>成功率 {Math.round(((data?.overview.draw.success_count || 0) / Math.max(1, data?.overview.draw.total || 0)) * 100)}%</span>
          </div>
          <div className="module-card-list">
            LoRA Top：{Object.entries(data?.draw.lora_counts || {}).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([name, count]) => `${name}(${count})`).join('、') || '暂无'}
          </div>
        </div>
      ),
    },
    {
      key: 'train',
      score: data?.overview.train.count || 0,
      node: (
        <div className="module-card" onClick={() => { uiStore.activeTab = 'train'; }}>
          <div className="module-card-header"><b>LoRA 训练</b><Tag>{data?.overview.train.count ?? 0} 次</Tag></div>
          <div className="module-card-stats">{renderStatusTags(data?.overview.train.status)}</div>
          <div className="module-card-footer">
            <span>失败率 {Math.round((data?.train.error_rate ?? 0) * 100)}%</span>
            <span>产物 {data?.train.output_count ?? 0}</span>
          </div>
          {data?.train.current ? (
            <div className="module-card-list">
              当前 {data.train.current.output_name || data.train.current.job_id}：
              {data.train.current.steps_done ?? 0}/{data.train.current.steps_total ?? 0}，
              loss {formatNumber(data.train.current.latest_loss)}
            </div>
          ) : <div className="module-card-list">当前没有训练任务</div>}
        </div>
      ),
    },
    {
      key: 'preset_assets',
      score: (data?.preset_assets.ready_count || 0) + (data?.preset_assets.running_count || 0) + (data?.preset_assets.failed_count || 0),
      node: (
        <div className="module-card" onClick={() => { uiStore.activeTab = 'presetAssets'; }}>
          <div className="module-card-header"><b>预设工坊</b><Tag>{data?.preset_assets.total ?? 0} 个预设</Tag></div>
          <div className="module-card-stats">
            <Tag color="green">正式 {data?.preset_assets.formal_count ?? 0}</Tag>
            <Tag color="blue">仅候选 {data?.preset_assets.candidate_only_count ?? 0}</Tag>
            <Tag color="red">缺失 {data?.preset_assets.missing_count ?? 0}</Tag>
          </div>
          <div className="module-card-footer">
            <span>正式覆盖 {data?.preset_assets.formal_percent ?? 0}%</span>
            <span>含候选 {data?.preset_assets.with_candidates_percent ?? 0}%</span>
          </div>
          <div className="module-card-list">
            待采纳 {data?.preset_assets.ready_count ?? 0}，运行中 {data?.preset_assets.running_count ?? 0}，失败 {data?.preset_assets.failed_count ?? 0}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="summary-box">
      <div className="module-system-bar">
        <b>系统状态</b>
        <Tag color={data?.system.busy ? 'orange' : 'green'}>{data?.system.busy ? '有任务运行' : '空闲'}</Tag>
        <Tag>GPU {data?.system.gpu.memory_used_mb ?? 0} / {data?.system.gpu.memory_total_mb ?? 0} MB</Tag>
        {(data?.system.gpu.active_models || []).map((model) => <Tag key={model.name} color="blue">{model.name}</Tag>)}
        <span>{data?.range.date_from || '-'} 至 {data?.range.date_to || '-'}</span>
      </div>

      <div className="module-card-grid">
        {primary.sort((a, b) => (sort === 'recent' ? b.score - a.score : 0)).map((item) => (
          <div key={item.key}>{item.node}</div>
        ))}
      </div>

      <div className="chart-box">
        <div className="chart-title">AI 绘画每日数量</div>
        <Column data={data?.draw.daily || []} xField="date" yField="count" height={220} label={{ position: 'top' }} />
      </div>

      <div className="chart-box">
        <div className="chart-title">LoRA 训练每日任务</div>
        {(data?.train.daily?.length || 0) > 1 ? (
          <Column data={data?.train.daily || []} xField="date" yField="count" height={180} />
        ) : (
          <div className="train-status-text">暂无足够趋势数据</div>
        )}
      </div>

      <div className="module-card-grid">
        <div className="module-card">
          <div className="module-card-header"><b>预设覆盖</b><Tag>{data?.preset_assets.total ?? 0} 个</Tag></div>
          <div className="module-card-list">
            {(data?.preset_assets.by_kind || []).filter((item) => item.total > 0).slice(0, 8).map((item) => (
              <span key={item.kind}>{item.label}：{item.formal_count}/{item.total}；仅候选 {item.candidate_only_count}</span>
            ))}
          </div>
        </div>
        <div className="module-card">
          <div className="module-card-header"><b>版本追溯</b><Tag>{data?.preset_assets.version_missing_count ?? 0} 缺失</Tag></div>
          <div className="module-card-stats">
            <Tag>预设版本缺失 {data?.preset_assets.preset_version_counts?.missing ?? 0}</Tag>
            <Tag>模板版本缺失 {data?.preset_assets.template_missing_count ?? 0}</Tag>
            <Tag color="red">格式异常 {data?.preset_assets.preset_version_counts?.malformed ?? 0}</Tag>
          </div>
          <div className="module-card-list">
            采纳 {data?.preset_assets.adopted_count ?? 0}，回滚 {data?.preset_assets.rolled_back_count ?? 0}
          </div>
        </div>
        <div className="module-card">
          <div className="module-card-header"><b>后台任务</b><Tag>{data?.system.jobs.count ?? 0} 个</Tag></div>
          <div className="module-card-stats">{renderStatusTags(data?.system.jobs.status)}</div>
          <div className="module-card-footer"><span>失败率 {Math.round((data?.system.jobs.error_rate ?? 0) * 100)}%</span></div>
          {data?.system.jobs.recent_errors?.length ? <div className="module-error-text">最近错误：{data.system.jobs.recent_errors[0]}</div> : null}
        </div>
      </div>

      <details className="chart-box">
        <summary>其他模块</summary>
        <div className="stats-summary">
          <Tag>提示词 Agent {data?.secondary.prompt_agent ?? 0}</Tag>
          <Tag>招聘 Agent {data?.secondary.recruitment_agent ?? 0}</Tag>
          <Tag>AI 动画 {data?.secondary.video ?? 0}</Tag>
          <Tag>陪伴消息 {(data?.secondary.companion as { messages?: number } | undefined)?.messages ?? 0}</Tag>
        </div>
      </details>
    </div>
  );
}
