import { RollbackOutlined } from '@ant-design/icons';
import {
  Button,
  Empty,
  Image,
  Popconfirm,
  Space,
  Tag,
  Timeline,
  message,
} from 'antd';
import { useEffect, useState } from 'react';
import { fetchPresetAssetHistory, type PresetAssetVersion } from '../api';
import {
  apiErrorMessage,
  presetAssetStore,
  rollbackPresetAsset,
} from '../stores/presetAssetStore';

const EVENT_LABELS: Record<string, string> = {
  source_imported: '导入源图',
  crop_candidate_created: '生成裁剪候选',
  ai_candidate_ready: 'AI 候选完成',
  candidate_adopted: '采纳候选',
  candidate_discarded: '丢弃候选',
  version_rolled_back: '回滚版本',
  settings_updated: '更新默认参数',
};

function formatTime(value: string | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

export default function PresetAssetHistory() {
  const { detail, selection } = presetAssetStore;
  const [versions, setVersions] = useState<PresetAssetVersion[]>([]);
  const [audit, setAudit] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [workingVersion, setWorkingVersion] = useState<number | null>(null);

  useEffect(() => {
    if (!selection || !detail) {
      setVersions([]);
      setAudit([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchPresetAssetHistory(selection.presetType, selection.presetId)
      .then((result) => {
        if (cancelled) return;
        setVersions(result.versions || []);
        setAudit(result.audit || []);
      })
      .catch(() => {
        if (cancelled) return;
        setVersions(detail.versions || []);
        setAudit([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    detail?.summary.active_version?.id,
    detail?.summary.preset_id,
    selection?.presetId,
    selection?.presetType,
  ]);

  if (!detail) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择预设后查看版本历史" />;
  }

  const rollback = async (version: number) => {
    setWorkingVersion(version);
    try {
      await rollbackPresetAsset(version);
      message.success(`已回滚到版本 ${version}`);
    } catch (error) {
      message.error(apiErrorMessage(error, '回滚失败'));
    } finally {
      setWorkingVersion(null);
    }
  };

  return (
    <div className="preset-asset-history">
      <div className="preset-asset-history-section">
        <div className="train-section-title">正式图版本</div>
        {versions.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无正式图版本" />
        ) : (
          <div className="preset-asset-version-list">
            {versions.map((version) => (
              <div className="preset-asset-version-row" key={version.id}>
                <Image
                  src={version.url}
                  alt={`版本 ${version.version}`}
                  width={72}
                  height={54}
                  style={{ objectFit: 'cover', borderRadius: 4, background: '#f8fafc' }}
                  preview={{ mask: false }}
                />
                <div className="preset-asset-version-copy">
                  <Space size={4} wrap>
                    <Tag color={version.active ? 'green' : 'default'}>
                      {version.active ? '当前版本' : `版本 ${version.version}`}
                    </Tag>
                    <span className="help">
                      {version.width}×{version.height} · {version.mime_type}
                    </span>
                  </Space>
                  <div className="help">{formatTime(version.created_at)}</div>
                  <div className="preset-asset-hash">{version.sha256.slice(0, 16)}</div>
                </div>
                {!version.active ? (
                  <Popconfirm
                    title={`回滚到版本 ${version.version}？`}
                    description="正式图和 public/dist 缩略图会同步恢复。"
                    onConfirm={() => void rollback(version.version)}
                  >
                    <Button
                      size="small"
                      icon={<RollbackOutlined />}
                      loading={workingVersion === version.version}
                    >
                      回滚
                    </Button>
                  </Popconfirm>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="preset-asset-history-section">
        <div className="train-section-title">审计记录</div>
        <Button
          type="link"
          size="small"
          loading={loading}
          onClick={() => {
            if (!selection) return;
            setLoading(true);
            fetchPresetAssetHistory(selection.presetType, selection.presetId)
              .then((result) => {
                setVersions(result.versions || []);
                setAudit(result.audit || []);
              })
              .catch((error) => message.error(apiErrorMessage(error, '审计记录加载失败')))
              .finally(() => setLoading(false));
          }}
        >
          刷新记录
        </Button>
        {audit.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计记录" />
        ) : (
          <Timeline
            items={audit.map((item) => {
              const event = String(item.event || '');
              const detailValue = item.detail as Record<string, unknown> | undefined;
              const version = detailValue?.version;
              const candidateId = item.candidate_id;
              return {
                color: event.includes('rollback') ? 'orange' : 'blue',
                children: (
                  <div>
                    <Space size={4} wrap>
                      <Tag>{EVENT_LABELS[event] || event || '事件'}</Tag>
                      {version != null ? <span>版本 {String(version)}</span> : null}
                      {candidateId != null ? <span>候选 #{String(candidateId)}</span> : null}
                    </Space>
                    <div className="help">{formatTime(String(item.created_at || ''))}</div>
                  </div>
                ),
              };
            })}
          />
        )}
      </div>
    </div>
  );
}
