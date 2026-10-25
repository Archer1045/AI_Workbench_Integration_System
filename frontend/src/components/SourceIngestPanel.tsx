import { Alert, Button, Empty, Input, Modal, Select, Space, Tag, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import {
  analyzeSourceImages,
  discoverSources,
  extractSource,
  ingestDiscoveredSource,
  ingestSource,
  listSources,
  prepareSourceImages,
  publishSource,
  type GuideProvider,
  type ProviderStatus,
  type SourceDiscoverItem,
  type SourceDiscoverResult,
  type SourceRecord,
} from '../stores/gameAssistant';

interface Props {
  eventId: string;
  revision: number;
  providers: ProviderStatus[];
  onPublished: () => void;
  onOpenSettings: () => void;
}

function sourceErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  if (detail) return detail;
  return error instanceof Error ? error.message : fallback;
}

const sourceTypeOptions = [
  { value: 'official', label: '官方公告' },
  { value: 'wiki', label: 'Wiki / Mooncell' },
  { value: 'guide', label: '攻略文章' },
  { value: 'user_note', label: '手动笔记' },
];

export default function SourceIngestPanel({
  eventId,
  revision,
  providers,
  onPublished,
  onOpenSettings,
}: Props) {
  const [messageApi, contextHolder] = message.useMessage();
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [sourceType, setSourceType] = useState('guide');
  const [provider, setProvider] = useState<Exclude<GuideProvider, 'template'>>('deepseek');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);
  const [discoverQuery, setDiscoverQuery] = useState('');
  const [discoverDays, setDiscoverDays] = useState(60);
  const [discoverResults, setDiscoverResults] = useState<SourceDiscoverItem[]>([]);
  const [discoverInfo, setDiscoverInfo] = useState<SourceDiscoverResult | null>(null);
  const [discoverSelected, setDiscoverSelected] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const items = await listSources(30);
      setSources(items);
      if (!selectedId && items[0]) setSelectedId(items[0].source_id);
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '来源列表读取失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const selected = sources.find((item) => item.source_id === selectedId) || null;
  const modelProviders = useMemo(
    () => providers.filter((item) => ['local', 'deepseek', 'openai_compatible'].includes(item.provider)),
    [providers],
  );
  const providerOptions = modelProviders
    .filter((item) => ['local', 'deepseek', 'openai_compatible'].includes(item.provider))
    .map((item) => ({
      value: item.provider,
      label: `${item.provider} · ${item.model || '未配置'}`,
      disabled: !item.available,
    }));

  const selectedProviderReady = modelProviders.some((item) => item.provider === provider && item.available);
  const selectedHasText = Boolean(selected && selected.text_length > 0);
  const selectedHasAnalyzedImages = Boolean(selected?.image_assets.some((item) => item.analysis_status === 'completed' && item.analysis_text));
  const selectedCanExtract = selectedHasText || selectedHasAnalyzedImages;
  const discoverCandidate = discoverResults.find((item) => item.url === discoverSelected) || null;

  const discover = async () => {
    const query = discoverQuery.trim();
    if (!query) {
      messageApi.warning('请输入要搜索的活动或攻略关键词');
      return;
    }
    setBusy('discover');
    try {
      const result = await discoverSources({ query, count: 8, days: discoverDays });
      setDiscoverResults(result.results);
      setDiscoverInfo(result);
      setDiscoverSelected(result.results[0]?.url || '');
      if (!result.results.length) {
        messageApi.warning('白名单域名内没有找到候选来源');
      }
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '来源搜索失败'));
    } finally {
      setBusy('');
    }
  };

  const ingestDiscovered = async () => {
    if (!discoverCandidate) return;
    setBusy('discover-ingest');
    try {
      const item = await ingestDiscoveredSource({
        url: discoverCandidate.url,
        source_type: discoverCandidate.source_type,
        title: discoverCandidate.title,
        event_id: eventId,
        revision,
      });
      setSources((previous) => [item, ...previous.filter((source) => source.source_id !== item.source_id)]);
      setSelectedId(item.source_id);
      messageApi.success('已保存来源快照；请检查正文后生成 revision 预览');
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '来源抓取失败'));
    } finally {
      setBusy('');
    }
  };

  const ingest = async () => {
    if (!url.trim() && !text.trim()) {
      messageApi.warning('请输入 URL 或粘贴正文');
      return;
    }
    setBusy('ingest');
    try {
      const item = await ingestSource({
        url: url.trim() || undefined,
        text: text.trim() || undefined,
        title: title.trim() || undefined,
        source_type: sourceType,
        event_id: eventId,
        revision,
      });
      setSources((previous) => [item, ...previous.filter((source) => source.source_id !== item.source_id)]);
      setSelectedId(item.source_id);
      setUrl('');
      setTitle('');
      setText('');
      messageApi.success('来源快照已保存');
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '来源抓取失败'));
    } finally {
      setBusy('');
    }
  };

  const prepareImages = async () => {
    if (!selected) return;
    setBusy('images');
    try {
      const result = await prepareSourceImages(selected.source_id);
      const updated = { ...selected, images: result.images.map((item) => item.url), image_assets: result.images };
      setSources((items) => items.map((item) => item.source_id === selected.source_id ? updated : item));
      messageApi.success('图片准备完成：成功 ' + result.downloaded + '，失败 ' + result.failed);
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '图片下载失败'));
    } finally {
      setBusy('');
    }
  };

  const analyzeImages = async () => {
    if (!selected) return;
    setBusy('vision');
    try {
      const result = await analyzeSourceImages(selected.source_id);
      const updated = { ...selected, image_assets: result.images };
      setSources((items) => items.map((item) => item.source_id === selected.source_id ? updated : item));
      messageApi.success('图片识别完成：成功 ' + result.completed + '，失败 ' + result.failed);
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '图片识别失败'));
    } finally {
      setBusy('');
    }
  };

  const extract = async () => {
    if (!selected) return;
    setBusy('extract');
    try {
      const result = await extractSource(selected.source_id, provider);
      const updated = { ...selected, extraction: result };
      setSources((items) => items.map((item) => (item.source_id === selected.source_id ? updated : item)));
      messageApi.success('已生成结构化 revision 预览');
    } catch (error) {
      messageApi.error(sourceErrorMessage(error, '来源解析失败'));
    } finally {
      setBusy('');
    }
  };

  const publish = () => {
    if (!selected?.extraction) return;
    Modal.confirm({
      title: '发布新的活动 revision？',
      content: '只会应用当前解析预览中的结构化字段，并保留来源引用。发布后当前活动事实会更新。',
      okText: '确认发布',
      cancelText: '取消',
      onOk: async () => {
        setBusy('publish');
        try {
          const result = await publishSource(selected.source_id, true);
          messageApi.success(`活动已发布为 revision ${result.revision}`);
          onPublished();
          await load();
        } catch (error) {
          messageApi.error(sourceErrorMessage(error, '发布失败'));
        } finally {
          setBusy('');
        }
      },
    });
  };

  const diff = selected?.extraction?.diff;

  return (
    <div className="ga-card ga-source-manager">
      {contextHolder}
      <div className="ga-row ga-between">
        <div>
          <h3>攻略来源输入</h3>
          <p className="ga-small ga-muted">支持 URL 抓取和正文粘贴；提取结果只生成预览，确认后才会发布 revision。</p>
        </div>
        <Tag color="blue">手动确认</Tag>
      </div>

      <div className="ga-source-discover">
        <div className="ga-row ga-between">
          <strong>搜索官方 / Mooncell</strong>
          <Tag>候选来源</Tag>
        </div>
        <div className="ga-source-discover-form">
          <Input
            value={discoverQuery}
            onChange={(event) => setDiscoverQuery(event.target.value)}
            onPressEnter={() => void discover()}
            placeholder="例如：FGO 国服 万圣节 2026 活动"
          />
          <Select
            value={discoverDays}
            onChange={setDiscoverDays}
            options={[
              { value: 30, label: '近 30 天' },
              { value: 60, label: '近 60 天' },
              { value: 180, label: '近半年' },
              { value: 0, label: '不限时间' },
            ]}
          />
          <Button type="primary" loading={busy === 'discover'} onClick={() => void discover()}>
            搜索来源
          </Button>
        </div>
        <p className="ga-small ga-muted">
          只保留官方公告与 Mooncell 域名；搜索结果是候选，抓取后仍需解析预览并人工确认才会发布。
        </p>
        {discoverInfo && (
          <div className="ga-small ga-muted">
            {discoverInfo.provider} · 候选 {discoverResults.length} 条 · 已过滤 {discoverInfo.filtered_out} 条
            {discoverInfo.cached ? ' · 命中缓存' : ''}
          </div>
        )}
        {discoverResults.length > 0 && (
          <div className="ga-source-discover-results">
            <Select
              value={discoverSelected || undefined}
              onChange={setDiscoverSelected}
              options={discoverResults.map((item) => ({
                value: item.url,
                label: `${item.source_type === 'wiki' ? 'Mooncell' : '官方'} · ${item.title}`,
              }))}
              style={{ width: '100%' }}
            />
            {discoverCandidate && (
              <div className="ga-source-discover-candidate">
                <a href={discoverCandidate.url} target="_blank" rel="noreferrer">
                  {discoverCandidate.url}
                </a>
                <div className="ga-small ga-muted">
                  日期 {discoverCandidate.date || '未知'} · 权威度{' '}
                  {discoverCandidate.authority == null ? '未知' : discoverCandidate.authority}
                </div>
                <p>{discoverCandidate.summary || '搜索服务没有返回摘要。'}</p>
                <Button loading={busy === 'discover-ingest'} onClick={() => void ingestDiscovered()}>
                  抓取并保存为来源
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="ga-source-form">
        <Input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://... 攻略 URL，可留空并直接粘贴正文"
        />
        <Select value={sourceType} onChange={setSourceType} options={sourceTypeOptions} />
        <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="来源标题，可自动识别" />
        <Input.TextArea
          value={text}
          onChange={(event) => setText(event.target.value)}
          autoSize={{ minRows: 4, maxRows: 10 }}
          placeholder="动态网页抓取失败时，可直接粘贴正文；填写正文后将优先使用正文并保留 URL 元数据。"
        />
        <Button type="primary" loading={busy === 'ingest'} onClick={() => void ingest()}>
          抓取并保存来源
        </Button>
      </div>

      {sources.length === 0 ? (
        <Empty description="还没有保存过攻略来源" />
      ) : (
        <div className="ga-source-workspace">
          <div className="ga-source-list-column">
            <Select
              value={selectedId || undefined}
              onChange={setSelectedId}
              loading={loading}
              options={sources.map((item) => ({
                value: item.source_id,
                label: `${item.title} · ${item.fetched_via === 'url' ? 'URL' : '正文'}`,
              }))}
              style={{ width: '100%' }}
            />
            <div className="ga-small ga-muted">{sources.length} 个最近来源</div>
          </div>

          {selected && (
            <div className="ga-source-preview">
              <div className="ga-row ga-between">
                <div>
                  <strong>{selected.title}</strong>
                  <p className="ga-small ga-muted">
                    {selected.final_url || selected.url || '手动正文'} · {selected.text_length} 字符 ·{' '}
                    {new Date(selected.fetched_at).toLocaleString()}
                  </p>
                </div>
                {selected.published_revision && <Tag color="green">已发布 revision {selected.published_revision}</Tag>}
              </div>
              {selected.warnings.length > 0 && (
                <Alert type="warning" showIcon message={selected.warnings.join('；')} />
              )}
              <div className="ga-source-excerpt">{selected.excerpt || '未提取到文字正文'}</div>
              {selected.images.length > 0 && (
                <div className="ga-image-review">
                  <Alert
                    type="info"
                    showIcon
                    message={'检测到 ' + selected.images.length + ' 张图片'}
                    description="可先下载到本地，再使用本地 VLM 提取图片文字和结构化事实。所有结果仍需人工确认。"
                  />
                  <Space wrap>
                    <Button loading={busy === 'images'} onClick={() => void prepareImages()}>准备图片</Button>
                    <Button loading={busy === 'vision'} disabled={!selected.image_assets.some((item) => item.status === 'downloaded')} onClick={() => void analyzeImages()}>识别图片</Button>
                  </Space>
                  <div className="ga-image-grid">
                    {selected.image_assets.map((asset) => (
                      <div key={asset.image_id} className="ga-image-card">
                        {asset.status === 'downloaded' ? (
                          <img src={'/api/game-assistant/fgo/sources/' + selected.source_id + '/images/' + asset.image_id} alt={asset.image_id} />
                        ) : (
                          <div className="ga-image-placeholder">{asset.status === 'failed' ? '下载失败' : '待下载'}</div>
                        )}
                        <strong>{asset.image_id}</strong>
                        {asset.error && <span className="ga-small">{asset.error}</span>}
                        {asset.analysis_status === 'completed' && <div className="ga-image-ocr">{asset.analysis_text}</div>}
                        {asset.analysis_error && <span className="ga-small">{asset.analysis_error}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <Space wrap>
                <Select
                  value={provider}
                  onChange={(value) => setProvider(value as Exclude<GuideProvider, 'template'>)}
                  options={providerOptions}
                  placeholder="选择解析模型"
                  style={{ minWidth: 220 }}
                />
                <Button loading={busy === 'extract'} onClick={() => void extract()}>
                  解析为 revision 预览
                </Button>
                <Button onClick={onOpenSettings}>模型设置</Button>
                {selected.extraction && (
                  <Button type="primary" loading={busy === 'publish'} onClick={publish}>
                    发布 revision
                  </Button>
                )}
              </Space>
              {selected.extraction ? (
                <div className="ga-revision-preview">
                  <Alert
                    type={diff?.conflicts.length ? 'warning' : 'success'}
                    showIcon
                    message={diff?.summary || '已生成解析预览'}
                    description={
                      diff?.conflicts.length
                        ? `${diff.conflicts.length} 项与当前 revision 不同，发布时会以新解析结果覆盖对应 ID。`
                        : '解析结果与当前活动的变更预览已生成。'
                    }
                  />
                  <div className="ga-chips">
                    {Object.entries(diff?.added || {}).map(([key, count]) => (
                      <Tag key={`add-${key}`} color="green">
                        新增 {key}: {count}
                      </Tag>
                    ))}
                    {Object.entries(diff?.updated || {}).map(([key, count]) => (
                      <Tag key={`update-${key}`} color="orange">
                        更新 {key}: {count}
                      </Tag>
                    ))}
                    {selected.extraction.patch.notes.map((note) => (
                      <Tag key={note}>{note}</Tag>
                    ))}
                  </div>
                </div>
              ) : (
                <Alert
                  type={selectedCanExtract && selectedProviderReady ? 'info' : 'warning'}
                  showIcon
                  message={
                    !selectedCanExtract
                      ? selected.images.length > 0
                        ? '请先执行图片识别，或粘贴文字正文后再解析。'
                        : '该来源没有可解析内容，请粘贴文字正文或使用浏览器截图。'
                      : !selectedProviderReady
                        ? '所选模型尚未配置或不可用，请先在模型设置中保存并测试连接。'
                        : '模型已就绪，可以生成结构化预览。'
                  }
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
