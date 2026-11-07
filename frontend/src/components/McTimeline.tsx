import { useEffect, useState } from 'react';
import { Button, Spin, Tag, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { api } from '../api';

type Update = {
  name: string;
  version: string;
  date: string;
  highlights: string[];
  major?: boolean;
  entity_count?: number;
};

type Props = {
  onBack: () => void;
};

/** 版本跨越时间线 */
export default function McTimeline({ onBack }: Props) {
  const [loading, setLoading] = useState(true);
  const [updates, setUpdates] = useState<Update[]>([]);

  useEffect(() => {
    api
      .get('/mc/timeline')
      .then((r) => setUpdates(r.data.updates || []))
      .catch(() => message.error('加载版本时间线失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="mc-timeline-loading">
        <Spin />
        <span>正在读取版本时间线…</span>
      </div>
    );
  }

  return (
    <div className="mc-timeline">
      <div className="mc-timeline-head">
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
          返回对话
        </Button>
        <div>
          <h2>版本跨越视图</h2>
          <p>从 2010 年的万圣节更新到 2024 年的棘巧试炼，共 {updates.length} 次主要更新</p>
        </div>
      </div>

      <div className="mc-timeline-list">
        {updates.map((u, index) => (
          <div key={`${u.version}-${index}`} className={`mc-tl-item ${u.major ? 'major' : ''}`}>
            <div className="mc-tl-axis">
              <span className="mc-tl-dot" />
              {index < updates.length - 1 ? <span className="mc-tl-line" /> : null}
            </div>
            <div className="mc-tl-card">
              <div className="mc-tl-head">
                <span className="mc-tl-date">{u.date}</span>
                <Tag color={u.major ? 'volcano' : 'default'}>{u.version}</Tag>
                {u.major ? <Tag color="red">大改</Tag> : null}
                {u.entity_count ? (
                  <span className="mc-tl-count">{u.entity_count} 个条目</span>
                ) : null}
              </div>
              <h3 className="mc-tl-name">{u.name}</h3>
              {u.highlights.length ? (
                <ul className="mc-tl-highlights">
                  {u.highlights.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      <div className="mc-timeline-hint">
        提示：标记「大改」的版本改动量最大，建议优先了解。
      </div>
    </div>
  );
}
