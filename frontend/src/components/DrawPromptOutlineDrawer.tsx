import { AimOutlined } from '@ant-design/icons';
import { Button, Collapse, Drawer, Empty, Space, Tag } from 'antd';
import type { PromptBlock, PromptDocumentV1 } from '../api';
import { createPromptBlock, promptBlockDetailTags } from '../promptDocument';
import type { DrawGroup } from '../stores/draw';

interface StructuredPreviewLike {
  prompt: string;
}

const CHARACTER_LABELS: Record<string, string> = {
  appearance: '外貌',
  clothing: '服装',
  body_modifications: '身体改造',
  pose_or_action: '动作',
  expression: '表情',
  state: '状态',
};
const CHARACTER_BLOCK_ENTRIES = [
  { key: 'appearance', label: '外貌' },
  { key: 'clothing', label: '服装' },
  { key: 'body_modifications', label: '身体改造' },
  { key: 'pose_or_action', label: '动作' },
  { key: 'expression', label: '表情' },
  { key: 'state', label: '状态' },
] as const;

const GLOBAL_LABELS: Record<string, string> = {
  quality: '质量',
  style: '风格',
  scene: '场景',
  camera: '镜头',
  lighting: '光照',
  constraints: '约束',
};

function sourceLabel(source?: string): string {
  if (!source || source === 'manual') return '手动';
  if (source.includes('preset')) return '预设';
  if (source.includes('appearance') || source.includes('character')) return '角色卡';
  if (source.includes('composition')) return '组合';
  return source;
}

function BlockOutline({
  label,
  block,
}: {
  label: string;
  block: PromptBlock;
}) {
  const detailTags = promptBlockDetailTags(block);
  return (
    <div className="draw-outline-block">
      <div className="draw-outline-block-title">
        <strong>{label}</strong>
        <Space size={4} wrap>
          <Tag color={block.enabled === false ? 'default' : 'blue'}>
            {block.enabled === false ? '停用' : '启用'}
          </Tag>
          <Tag>{sourceLabel(block.source)}</Tag>
          {block.preset_refs.length > 0 ? (
            <Tag color="purple">{block.preset_refs.length} 引用</Tag>
          ) : null}
        </Space>
      </div>
      <div className="draw-outline-tags">
        {detailTags.length === 0 ? (
          <span className="help">空</span>
        ) : (
          detailTags.map((tag, index) => (
            <Tag key={`${tag}-${index}`}>{tag}</Tag>
          ))
        )}
        {block.kind === 'expression' ? (
          <Tag color="gold">强度 {block.intensity ?? 0.7}</Tag>
        ) : null}
      </div>
    </div>
  );
}

function StructuredOutline({
  document,
  negativePrompt,
}: {
  document: PromptDocumentV1;
  negativePrompt: string;
}) {
  return (
    <div className="draw-outline-structured">
      {document.characters.map((character) => (
        <section key={character.id} className="draw-outline-section">
          <div className="draw-outline-section-title">
            <strong>{character.display_name}</strong>
            <Tag>{character.role_id}</Tag>
            {character.enabled === false ? <Tag>停用角色</Tag> : null}
          </div>
          <div className="draw-outline-grid">
            {CHARACTER_BLOCK_ENTRIES.map(({ key, label }) => (
              <BlockOutline
                key={key}
                label={label}
                block={character[key]}
              />
            ))}
            <BlockOutline
              label="角色道具"
              block={
                document.props.characters[character.role_id] ||
                createPromptBlock('props')
              }
            />
          </div>
        </section>
      ))}

      <section className="draw-outline-section">
        <div className="draw-outline-section-title">
          <strong>全局</strong>
        </div>
        <div className="draw-outline-grid">
          {(Object.keys(GLOBAL_LABELS) as Array<keyof PromptDocumentV1['global']>).map(
            (key) => (
              <BlockOutline
                key={key}
                label={GLOBAL_LABELS[key]}
                block={document.global[key]}
              />
            ),
          )}
          <BlockOutline label="场景道具" block={document.props.global} />
        </div>
      </section>

      <section className="draw-outline-section">
        <div className="draw-outline-section-title">
          <strong>互动</strong>
        </div>
        <div className="draw-outline-grid">
          {[
            { label: '动作', tags: document.interaction.action_tags },
            { label: '接触', tags: document.interaction.contact_tags },
            { label: '关系', tags: document.interaction.relationship_tags },
            { label: '构图', tags: document.interaction.composition_constraints },
          ].map((item) => (
            <BlockOutline
              key={item.label}
              label={item.label}
              block={{
                tags: item.tags,
                preset_refs: [],
                source: 'manual',
              }}
            />
          ))}
        </div>
      </section>

      <section className="draw-outline-section">
        <div className="draw-outline-section-title">
          <strong>负面提示词</strong>
        </div>
        <div className="draw-outline-tags">
          {negativePrompt
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean)
            .map((tag, index) => (
              <Tag key={`${tag}-${index}`}>{tag}</Tag>
            ))}
        </div>
      </section>
    </div>
  );
}

export default function DrawPromptOutlineDrawer({
  open,
  onClose,
  groups,
  previews,
  activeGroupId,
  negativePrompt,
  onSelectGroup,
}: {
  open: boolean;
  onClose: () => void;
  groups: DrawGroup[];
  previews: Record<string, StructuredPreviewLike>;
  activeGroupId: string;
  negativePrompt: string;
  onSelectGroup: (id: string) => void;
}) {
  return (
    <Drawer
      title="提示词大纲"
      open={open}
      onClose={onClose}
      width="min(760px, 96vw)"
      className="draw-outline-drawer"
    >
      {groups.length === 0 ? (
        <Empty description="暂无提示词组" />
      ) : (
        <Collapse
          defaultActiveKey={activeGroupId ? [activeGroupId] : []}
          items={groups.map((group, index) => ({
            key: group.id,
            label: (
              <div className="draw-outline-group-label">
                <strong>第 {index + 1} 组</strong>
                <Tag>{group.mode === 'structured' ? '结构化' : '原始文本'}</Tag>
                <Tag>{group.count} 张</Tag>
                {group.enabled === false ? <Tag>未启用</Tag> : null}
              </div>
            ),
            extra: (
              <Button
                size="small"
                type="text"
                icon={<AimOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectGroup(group.id);
                  onClose();
                }}
              >
                定位
              </Button>
            ),
            children:
              group.mode === 'structured' && group.prompt_document ? (
                <StructuredOutline
                  document={group.prompt_document}
                  negativePrompt={negativePrompt}
                />
              ) : (
                <div className="draw-outline-structured">
                  <section className="draw-outline-section">
                    <div className="draw-outline-section-title">
                      <strong>原始文本</strong>
                      <Tag>手动</Tag>
                    </div>
                    <div className="draw-outline-tags">
                      {previews[group.id]?.prompt || group.prompt ? (
                        (previews[group.id]?.prompt || group.prompt)
                          .split(',')
                          .map((tag) => tag.trim())
                          .filter(Boolean)
                          .map((tag, tagIndex) => (
                            <Tag key={`${tag}-${tagIndex}`}>{tag}</Tag>
                          ))
                      ) : (
                        <span className="help">空</span>
                      )}
                    </div>
                  </section>
                </div>
              ),
          }))}
        />
      )}
    </Drawer>
  );
}
