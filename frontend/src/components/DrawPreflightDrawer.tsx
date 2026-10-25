import { Alert, Drawer, Empty, Space, Statistic, Tag } from 'antd';
import type { DrawGroup } from '../stores/draw';
import { isPromptDocumentEmpty } from '../promptDocument';

interface PreflightPreview {
  loading?: boolean;
  prompt: string;
  negativePrompt?: string;
  errors: string[];
  warnings: string[];
}

export default function DrawPreflightDrawer({
  open,
  onClose,
  groups,
  previews,
  model,
  width,
  height,
  steps,
  cfg,
  loras,
  negativePrompt,
}: {
  open: boolean;
  onClose: () => void;
  groups: DrawGroup[];
  previews: Record<string, PreflightPreview>;
  model: string;
  width: number;
  height: number;
  steps: number | null;
  cfg: number;
  loras: string[];
  negativePrompt: string;
}) {
  const enabledGroups = groups.filter((group) => group.enabled !== false);
  const readyGroups = enabledGroups.filter((group) =>
    group.mode === 'structured'
      ? !isPromptDocumentEmpty(group.prompt_document)
      : Boolean(group.prompt.trim()),
  );
  const requestedCount = readyGroups.reduce(
    (total, group) => total + Math.max(0, Number(group.count) || 0),
    0,
  );
  const promptIssues = readyGroups.flatMap((group, index) =>
    [
      ...(previews[group.id]?.errors || []).map((message) => ({
        group: index + 1,
        level: 'error',
        message,
      })),
      ...(previews[group.id]?.warnings || []).map((message) => ({
        group: index + 1,
        level: 'warning',
        message,
      })),
    ],
  );
  const negativeLayers = readyGroups.flatMap((group) => {
    if (group.mode !== 'structured' || !group.prompt_document) return [];
    const blocks = group.prompt_document.negative;
    const globalLayers = Object.entries(blocks)
      .filter(([, block]) => block.tags.length > 0)
      .map(([kind, block]) => ({
        kind,
        count: block.tags.length,
      }));
    const characterLayers = group.prompt_document.characters.flatMap(
      (character) =>
        character.negative.tags.length > 0
          ? [
              {
                kind: `${character.role_id}:角色负向`,
                count: character.negative.tags.length,
              },
            ]
          : [],
    );
    return [...globalLayers, ...characterLayers];
  });

  return (
    <Drawer
      title="生成前摘要"
      open={open}
      onClose={onClose}
      width="min(680px, 96vw)"
      className="draw-preflight-drawer"
    >
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message="这里只汇总即将提交的信息，不执行准确性校验，也不会自动修改提示词。"
        />
        <div className="draw-preflight-stats">
          <Statistic title="启用组" value={enabledGroups.length} />
          <Statistic title="可提交组" value={readyGroups.length} />
          <Statistic title="计划张数" value={requestedCount} />
        </div>
        <div className="draw-preflight-section">
          <strong>生成参数</strong>
          <Space size={[4, 6]} wrap>
            <Tag>{model || '未选择模型'}</Tag>
            <Tag>
              {width} × {height}
            </Tag>
            <Tag>{steps ?? '默认'} steps</Tag>
            <Tag>CFG {cfg}</Tag>
            <Tag>{loras.length} 个批次 LoRA</Tag>
            <Tag>{negativePrompt.trim() ? '含全局负向提示词' : '无全局负向提示词'}</Tag>
          </Space>
        </div>
        <div className="draw-preflight-section">
          <strong>提示词组</strong>
          {readyGroups.length ? (
            <div className="draw-preflight-groups">
              {readyGroups.map((group, index) => {
                const preview = previews[group.id];
                const prompt =
                  preview?.prompt || group.prompt || '结构化内容待解析';
                return (
                  <article key={group.id} className="draw-preflight-group">
                    <div>
                      <strong>第 {index + 1} 组</strong>
                      <Tag>{group.mode === 'structured' ? '结构化' : '原始文本'}</Tag>
                      <Tag>{group.count} 张</Tag>
                      {preview?.loading ? <Tag color="blue">解析中</Tag> : null}
                    </div>
                    <div className="draw-preflight-prompt">{prompt}</div>
                    <div className="help">
                      正向 {prompt.length} 字符
                      {preview?.negativePrompt
                        ? ` · 负向 ${preview.negativePrompt.length} 字符`
                        : ''}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="没有可提交的提示词组"
            />
          )}
        </div>
        <div className="draw-preflight-section">
          <strong>负向分层</strong>
          {negativeLayers.length ? (
            <Space size={[4, 6]} wrap>
              {negativeLayers.map((item) => (
                <Tag key={item.kind}>
                  {item.kind}: {item.count}
                </Tag>
              ))}
            </Space>
          ) : (
            <span className="help">无结构化负向块</span>
          )}
        </div>
        <div className="draw-preflight-section">
          <strong>已知问题</strong>
          {promptIssues.length ? (
            <div className="draw-preflight-issues">
              {promptIssues.map((issue, index) => (
                <Alert
                  key={`${issue.group}-${index}`}
                  type={issue.level === 'error' ? 'error' : 'warning'}
                  showIcon
                  message={`第 ${issue.group} 组：${issue.message}`}
                />
              ))}
            </div>
          ) : (
            <span className="help">当前预览没有返回 error 或 warning。</span>
          )}
        </div>
      </Space>
    </Drawer>
  );
}
