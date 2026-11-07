import { Button, Drawer, Empty, List, Space, Tag } from 'antd';
import { useMemo, useState } from 'react';
import type { DrawPromptVersion } from '../drawPromptHistory';
import { diffPromptTags } from '../drawPromptHistory';
import type { DrawGroup } from '../stores/draw';

export default function DrawPromptHistoryDrawer({
  open,
  onClose,
  group,
  versions,
  currentPrompt,
  onRestore,
}: {
  open: boolean;
  onClose: () => void;
  group: DrawGroup | null;
  versions: DrawPromptVersion[];
  currentPrompt: string;
  onRestore: (version: DrawPromptVersion) => void;
}) {
  const [selectedId, setSelectedId] = useState('');
  const selected =
    versions.find((item) => item.id === selectedId) || versions[0] || null;
  const diff = useMemo(
    () =>
      selected
        ? diffPromptTags(selected.prompt, currentPrompt)
        : { added: [], removed: [] },
    [currentPrompt, selected],
  );

  return (
    <Drawer
      title="提示词组版本历史"
      open={open}
      onClose={onClose}
      width="min(760px, 96vw)"
      className="draw-prompt-history-drawer"
    >
      {!group || versions.length === 0 ? (
        <Empty description="当前提示词组还没有本地版本" />
      ) : (
        <div className="draw-history-layout">
          <List
            className="draw-history-list"
            dataSource={versions}
            renderItem={(version, index) => {
              const active = selected?.id === version.id;
              return (
                <List.Item
                  className={`draw-history-item${active ? ' active' : ''}`}
                  onClick={() => setSelectedId(version.id)}
                >
                  <div className="draw-history-copy">
                    <div>
                      <strong>版本 {versions.length - index}</strong>
                      <Tag>{version.mode === 'structured' ? '结构化' : '原始文本'}</Tag>
                    </div>
                    <span>{new Date(version.createdAt).toLocaleString('zh-CN')}</span>
                    <p>{version.prompt || '仅结构化内容'}</p>
                  </div>
                </List.Item>
              );
            }}
          />
          <section className="draw-history-detail">
            <strong>与当前版本对比</strong>
            {selected ? (
              <>
                <div className="draw-history-diff">
                  <span>新增</span>
                  <Space size={[4, 4]} wrap>
                    {diff.added.length ? (
                      diff.added.map((tag) => (
                        <Tag color="green" key={tag}>
                          {tag}
                        </Tag>
                      ))
                    ) : (
                      <span className="help">无</span>
                    )}
                  </Space>
                </div>
                <div className="draw-history-diff">
                  <span>移除</span>
                  <Space size={[4, 4]} wrap>
                    {diff.removed.length ? (
                      diff.removed.map((tag) => (
                        <Tag color="red" key={tag}>
                          {tag}
                        </Tag>
                      ))
                    ) : (
                      <span className="help">无</span>
                    )}
                  </Space>
                </div>
                <Button type="primary" onClick={() => onRestore(selected)}>
                  恢复此版本
                </Button>
              </>
            ) : null}
          </section>
        </div>
      )}
    </Drawer>
  );
}
