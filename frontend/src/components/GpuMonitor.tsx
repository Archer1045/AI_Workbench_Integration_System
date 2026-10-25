// GPU 实时监控：顶部按钮 + 弹窗图表 + 当前驻留模型
import { Line } from '@ant-design/charts';
import { DesktopOutlined } from '@ant-design/icons';
import { Button, Popover, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import { api, type GpuInfo } from '../api';

const MAX_POINTS = 60;

interface GpuPoint {
  time: string;
  value: number;
}

function formatGb(mb: number): string {
  return `${(mb / 1024).toFixed(1)}GB`;
}

export default function GpuMonitor() {
  const [info, setInfo] = useState<GpuInfo | null>(null);
  const [utilHistory, setUtilHistory] = useState<GpuPoint[]>([]);
  const [memHistory, setMemHistory] = useState<GpuPoint[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const { data } = await api.get<GpuInfo>('/system/gpu');
        if (cancelled) return;
        setInfo(data);
        const time = new Date().toLocaleTimeString();
        setUtilHistory((prev) => [...prev.slice(-(MAX_POINTS - 1)), { time, value: data.util }]);
        setMemHistory((prev) => [...prev.slice(-(MAX_POINTS - 1)), { time, value: data.memory_used_mb }]);
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const memRatio = info && info.memory_total_mb > 0 ? info.memory_used_mb / info.memory_total_mb : 0;
  const memWarning = memRatio >= 0.9;

  const content = (
    <div className="gpu-monitor-popover">
      <div className="gpu-monitor-cards">
        <div className={`gpu-card${memWarning ? ' warning' : ''}`}>
          <span>显存</span>
          <b>
            {info ? `${formatGb(info.memory_used_mb)} / ${formatGb(info.memory_total_mb)}` : '--'}
          </b>
        </div>
        <div className="gpu-card">
          <span>利用率</span>
          <b>{info ? `${info.util}%` : '--'}</b>
        </div>
        <div className="gpu-card">
          <span>温度</span>
          <b>{info ? `${info.temperature_c}°C` : '--'}</b>
        </div>
        <div className="gpu-card">
          <span>功耗</span>
          <b>{info ? `${info.power_w}W` : '--'}</b>
        </div>
      </div>
      <div className="gpu-monitor-models">
        <span>当前模型</span>
        {info && info.active_models.length > 0 ? (
          info.active_models.map((model) => (
            <Tag key={model.name} color="blue">
              {model.name} · {formatGb(model.size_mb)}
            </Tag>
          ))
        ) : (
          <Tag>无模型驻留</Tag>
        )}
      </div>
      <div className="gpu-chart-title">GPU 利用率</div>
      <Line
        data={utilHistory}
        xField="time"
        yField="value"
        height={140}
        smooth
        point={{ size: 2 }}
        yAxis={{ title: { text: 'GPU 利用率 %' } }}
      />
      <div className="gpu-chart-title">显存占用</div>
      <Line
        data={memHistory}
        xField="time"
        yField="value"
        height={140}
        smooth
        point={{ size: 2 }}
        yAxis={{ title: { text: '显存 MB' } }}
      />
      {error ? <div className="gpu-monitor-error">GPU 数据获取失败</div> : null}
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <Tooltip title="实时 GPU 利用率、显存与当前驻留模型">
        <Button size="small" icon={<DesktopOutlined />} className={memWarning ? 'gpu-button-warning' : undefined}>
          {info ? `GPU ${info.util}% · ${formatGb(info.memory_used_mb)}` : 'GPU --'}
        </Button>
      </Tooltip>
    </Popover>
  );
}
