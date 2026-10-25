// 提示词 Agent 工作区：图片反推 + 自然语言生成 + 智能拆分
import { Button, Checkbox, Input, InputNumber, message, Modal, Radio, Segmented, Select, Space, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import {
  api,
  type ClothingPreset,
  type PoseCatalogItem,
  type PresetComposition,
  type PresetCompositionResult,
  type PresetScope,
  type PromptGroup,
  type PromptValidation,
  type PromptValidationIssue,
  type ScenePreset,
} from '../api';
import { busyBlockMessage, showBusyWarning } from '../stores/busy';
import { promptStore, fromImage, fromText, sendToDraw, setReverseOptions } from '../stores/prompt';
import { settingsStore } from '../stores/settings';
import { CLOTHING_SCOPE_OPTIONS, formatClothingInsert, type ClothingScope } from '../clothingPresets';
import {
  formatScenePresetInsert,
  posePromptForInsert,
  type ScenePeoplePolicy,
} from '../presetComposition';
import { setPresetAssetSelection } from '../stores/presetAssetStore';
import {
  clearPresetCompositionRequest,
  presetLibraryStore,
} from '../stores/presetLibrary';
import { uiStore } from '../stores/ui';
import CharacterAppearanceModal, { type CharacterAppearanceResult } from './CharacterAppearanceModal';
import PublicSettingLookupModal from './PublicSettingLookupModal';
import {
  presetCategoryGroup,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';
import PresetCompositionDrawer, {
  type PresetCompositionApplyMode,
  type PresetCompositionInitialSelection,
} from './PresetCompositionDrawer';
import ScenePresetsModal from './ScenePresetsModal';

const CATEGORY_META = [
  { key: 'character', label: '人物', type: '角色' },
  { key: 'action', label: '动作', type: '动作' },
  { key: 'background', label: '背景环境', type: '场景' },
  { key: 'style', label: '画风', type: '画风' },
  { key: 'other', label: '其他', type: '其他' },
] as const;

type SplitGroups = Record<string, string[]>;

type PosePreset = PoseCatalogItem;

function promptHasTags(prompt: string, tags: string[]): boolean {
  const existing = new Set(prompt.toLowerCase().split(',').map((part) => part.trim()).filter(Boolean));
  return tags.length > 0 && tags.every((tag) => existing.has(tag.toLowerCase()));
}

function appendUniqueTags(prompt: string, tags: string[]): string {
  const existing = new Set(prompt.toLowerCase().split(',').map((part) => part.trim()).filter(Boolean));
  const added = tags.filter((tag) => tag && !existing.has(tag.toLowerCase()));
  return added.length ? `${prompt}, ${added.join(', ')}` : prompt;
}

function todayLabel(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export default function PromptAgent() {
  const { restrictionEnabled } = settingsStore;
  // 注意：resso store 的每次属性读取都会注册一次 hook，必须在组件顶部无条件读取，
  // 否则条件读取会导致 "Rendered fewer hooks than expected" 崩溃（2026-10-11 事故）。
  const {
    mode,
    imageBase64,
    imageName,
    text,
    result,
    status,
    autoDraw,
    reverseMode,
    reverseThreshold,
  } = promptStore;
  const [splitText, setSplitText] = useState('');
  const [splitResult, setSplitResult] = useState<SplitGroups | null>(null);
  const [splitLoading, setSplitLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [newTags, setNewTags] = useState<Record<string, string>>({});
  const [posePresets, setPosePresets] = useState<PosePreset[]>([]);
  const [selectedPoseId, setSelectedPoseId] = useState('');
  const [clothingPresets, setClothingPresets] = useState<ClothingPreset[]>([]);
  const [selectedClothingId, setSelectedClothingId] = useState('');
  const [clothingScope, setClothingScope] = useState<ClothingScope>('all');
  const [refineRequirements, setRefineRequirements] = useState('');
  const [refining, setRefining] = useState(false);
  const [refined, setRefined] = useState<{ prompt: string; translation: string; groups: PromptGroup[] } | null>(null);
  const [tagTranslations, setTagTranslations] = useState<Record<string, string>>({});
  const [validationIssues, setValidationIssues] = useState<PromptValidationIssue[]>([]);
  const [vlmModel, setVlmModel] = useState('');
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifySessionId, setClarifySessionId] = useState('');
  const [clarifyMessages, setClarifyMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([]);
  const [clarifyInput, setClarifyInput] = useState('');
  const [clarifyLoading, setClarifyLoading] = useState(false);
  const [characterAppearanceOpen, setCharacterAppearanceOpen] = useState(false);
  const [publicSettingOpen, setPublicSettingOpen] = useState(false);
  const [scenePresetsOpen, setScenePresetsOpen] = useState(false);
  const [presetCompositionOpen, setPresetCompositionOpen] = useState(false);
  const [presetCompositionInitialSelection, setPresetCompositionInitialSelection] =
    useState<PresetCompositionInitialSelection | null>(null);
  const { selection: librarySelection, requestToken: libraryRequestToken } =
    presetLibraryStore;

  useEffect(() => {
    api
      .get<{ items: PosePreset[] }>('/prompt-agent/pose-presets')
      .then((res) => setPosePresets(sortPresetItems(res.data.items || [])))
      .catch(() => undefined);
    api
      .get<{ items: ClothingPreset[] }>('/prompt-agent/clothing-presets')
      .then((res) => setClothingPresets(sortPresetItems(res.data.items || [])))
      .catch(() => undefined);
    api
      .get<{ model: string }>('/settings/vlm-model')
      .then((res) => setVlmModel(res.data.model || ''))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!librarySelection) return;
    setPresetCompositionInitialSelection({
      ...librarySelection,
      token: libraryRequestToken,
    });
    setPresetCompositionOpen(true);
    clearPresetCompositionRequest();
  }, [libraryRequestToken, librarySelection]);

  useEffect(() => {
    if (!result?.prompt) {
      setValidationIssues([]);
      return;
    }
    let cancelled = false;
    api
      .post<PromptValidation>('/prompt/validate', { prompt: result.prompt })
      .then((res) => {
        if (!cancelled) setValidationIssues([...res.data.errors, ...res.data.warnings, ...res.data.suggestions]);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [result]);

  const handleSplit = async () => {
    if (!splitText.trim()) {
      message.warning('请输入提示词集');
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setSplitLoading(true);
    try {
      const { data } = await api.post<{ groups: SplitGroups }>('/prompt-agent/split', { text: splitText });
      setSplitResult(data.groups || {});
      const nextNames: Record<string, string> = {};
      CATEGORY_META.forEach((meta) => {
        nextNames[meta.key] = `${meta.label} - ${todayLabel()}`;
      });
      setNames(nextNames);
      setNewTags({});
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '拆分失败');
    } finally {
      setSplitLoading(false);
    }
  };

  const removeTag = (key: string, tag: string) => {
    if (!splitResult) return;
    setSplitResult({ ...splitResult, [key]: splitResult[key].filter((item) => item !== tag) });
  };

  const addTag = (key: string) => {
    const value = (newTags[key] || '').trim();
    if (!value || !splitResult) return;
    setSplitResult({ ...splitResult, [key]: [...(splitResult[key] || []), value] });
    setNewTags({ ...newTags, [key]: '' });
  };

  const handleSave = async () => {
    if (!splitResult) return;
    setSaving(true);
    let ok = 0;
    let failed = 0;
    for (const meta of CATEGORY_META) {
      const tags = splitResult[meta.key] || [];
      if (tags.length === 0) continue;
      const name = (names[meta.key] || `${meta.label} - ${todayLabel()}`).trim();
      try {
        await api.post('/prompt-sets', { name, type: meta.type, content: tags.join(', '), translation: '' });
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    message.success(`已添加 ${ok} 组提示词集${failed ? `，失败 ${failed}` : ''}`);
    setSaving(false);
  };

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      promptStore.imageBase64 = String(reader.result);
      promptStore.imageName = file.name;
    };
    reader.readAsDataURL(file);
  };

  const handleRefine = async () => {
    if (!result?.prompt) {
      message.warning('请先生成提示词');
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setRefining(true);
    try {
      const selectedPose = posePresets.find((item) => item.id === selectedPoseId);
      const poseAlreadyInPrompt = selectedPose ? promptHasTags(result.prompt, selectedPose.tags) : false;
      const { data } = await api.post<{ prompt: string; prompt_translation: string; groups: PromptGroup[] }>('/prompt-agent/refine', {
        description: result.description || '',
        prompt: result.prompt,
        requirements: refineRequirements,
        pose_preset_id: selectedPoseId && !poseAlreadyInPrompt ? selectedPoseId : undefined,
      });
      setRefined({ prompt: data.prompt, translation: data.prompt_translation, groups: data.groups });
      void loadTranslations(data.groups.flatMap((group) => group.items));
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '细化失败');
    } finally {
      setRefining(false);
    }
  };

  const handleRoleSplit = async () => {
    if (!result?.prompt) {
      message.warning('请先生成提示词');
      return;
    }
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setRefining(true);
    try {
      const { data } = await api.post<{ groups: PromptGroup[] }>('/prompt-agent/split', {
        text: result.prompt,
        description: result.description || '',
        role_aware: true,
      });
      setRefined({ prompt: result.prompt, translation: result.prompt_translation || '', groups: data.groups });
      void loadTranslations(data.groups.flatMap((group) => group.items));
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '拆分失败');
    } finally {
      setRefining(false);
    }
  };

  const handlePoseToggle = (preset: PosePreset) => {
    if (selectedPoseId === preset.id) {
      setSelectedPoseId('');
      return;
    }
    setSelectedPoseId(preset.id);
    if (result?.prompt) {
      const poseTags = posePromptForInsert(preset)
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean);
      const nextPrompt = appendUniqueTags(result.prompt, poseTags);
      if (nextPrompt !== result.prompt) {
        promptStore.result = {
          ...promptStore.result,
          prompt: nextPrompt,
          prompt_translation: promptStore.result?.prompt_translation || '',
        };
      }
    }
    message.success(`已加入体位：${preset.label}`);
  };

  const handleClothingToggle = (preset: ClothingPreset) => {
    if (restrictionEnabled && preset.nsfw) {
      return;
    }
    if (selectedClothingId === preset.id) {
      setSelectedClothingId('');
      return;
    }
    setSelectedClothingId(preset.id);
    if (!result?.prompt) return;
    const fragment = formatClothingInsert(preset, clothingScope);
    const nextPrompt = result.prompt.toLowerCase().includes(fragment.toLowerCase())
      ? result.prompt
      : `${result.prompt}, ${fragment}`;
    if (nextPrompt !== result.prompt) {
      promptStore.result = {
        ...promptStore.result,
        prompt: nextPrompt,
        prompt_translation: promptStore.result?.prompt_translation || '',
      };
      message.success(`已加入服装：${preset.label}`);
    }
  };

  const insertScenePreset = (
    preset: ScenePreset,
    scope: PresetScope,
    peoplePolicy: ScenePeoplePolicy = 'occupied',
  ) => {
    const fragment = formatScenePresetInsert(preset, scope, peoplePolicy);
    const current = promptStore.result?.prompt || '';
    if (current.toLowerCase().includes(fragment.toLowerCase())) {
      message.info(`「${preset.label}」已在当前提示词中`);
      return;
    }
    const nextPrompt = current ? `${current}, ${fragment}` : fragment;
    promptStore.result = {
      ...(promptStore.result || {}),
      prompt: nextPrompt,
      prompt_translation: promptStore.result?.prompt_translation || '',
      description: promptStore.result?.description || '',
    };
    promptStore.status = `已加入场景预设：${preset.label}`;
    message.success(`已加入场景：${preset.label}`);
  };

  const applyPresetComposition = (
    result: PresetCompositionResult,
    _composition: PresetComposition,
    mode: PresetCompositionApplyMode,
  ) => {
    if (result.blocked || (restrictionEnabled && result.rating === 'R18')) {
      message.error('内容限制已开启，已阻止 R18 组合');
      return;
    }
    const current = promptStore.result?.prompt || '';
    const nextPrompt =
      mode === 'replace'
        ? result.prompt
        : current
          ? `${current}, ${result.prompt}`
          : result.prompt;
    promptStore.result = {
      ...(promptStore.result || {}),
      prompt: nextPrompt,
      prompt_translation: promptStore.result?.prompt_translation || '',
      description: promptStore.result?.description || '',
    };
    promptStore.status = mode === 'replace' ? '已替换为预设组合' : '已追加预设组合';
    message.success(mode === 'replace' ? '已替换当前提示词' : '已追加到当前提示词');
  };

  const openClarify = () => {
    const sessionId =
      typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    setClarifySessionId(sessionId);
    setClarifyMessages([]);
    setClarifyInput('');
    setClarifyOpen(true);
  };

  const sendClarify = async () => {
    const messageText = clarifyInput.trim();
    if (!messageText || clarifyLoading) return;
    const block = await busyBlockMessage();
    if (block) {
      showBusyWarning(block);
      return;
    }
    setClarifyMessages((prev) => [...prev, { role: 'user', content: messageText }]);
    setClarifyInput('');
    setClarifyLoading(true);
    try {
      const { data } = await api.post<{
        done: boolean;
        reply: string;
        prompt: string;
        prompt_translation: string;
        groups: PromptGroup[];
      }>('/prompt-agent/clarify', {
        session_id: clarifySessionId,
        message: messageText,
        initial: result?.description || result?.prompt || promptStore.text,
      });
      if (data.done) {
        if (data.prompt) {
          promptStore.result = {
            ...(promptStore.result || {}),
            prompt: data.prompt,
            prompt_translation: data.prompt_translation,
          };
          setRefined({ prompt: data.prompt, translation: data.prompt_translation, groups: data.groups || [] });
          void loadTranslations((data.groups || []).flatMap((group) => group.items));
        }
        setClarifyOpen(false);
        message.success('提示词生成完成');
      } else {
        setClarifyMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '澄清失败');
    } finally {
      setClarifyLoading(false);
    }
  };

  const loadTranslations = async (tags: string[]) => {
    if (tags.length === 0) return;
    try {
      const res = await api.post<{ items: { tag: string; translation: string }[] }>('/translate/tags', {
        text: tags.join(', '),
      });
      const map: Record<string, string> = {};
      for (const item of res.data.items || []) map[item.tag] = item.translation;
      setTagTranslations(map);
    } catch {
      // 翻译失败不影响标签展示
    }
  };

  const copyTag = async (tag: string) => {
    try {
      await navigator.clipboard.writeText(tag);
      message.success(`已复制 ${tag}`);
    } catch {
      message.error('复制失败');
    }
  };

  const handleVlmChange = (value: string) => {
    setVlmModel(value);
    void api
      .post('/settings/vlm-model', { model: value })
      .then(() => message.success(`视觉模型已切换：${value}`))
      .catch(() => message.error('切换失败'));
  };

  const applyCharacterAppearance = (apply: { scope: 'current' | 'all'; result: CharacterAppearanceResult }) => {
    const tags = [
      ...apply.result.appearance,
      ...apply.result.clothing,
      ...apply.result.expression,
    ];
    const current = promptStore.result?.prompt || '';
    const nextPrompt = current ? appendUniqueTags(current, tags) : tags.join(', ');
    promptStore.result = {
      ...promptStore.result,
      prompt: nextPrompt,
      prompt_translation: promptStore.result?.prompt_translation || '',
      description: promptStore.result?.description || '',
    };
    promptStore.status = '已填入角色外貌/默认服装';
  };

  const applyPublicSettings = (reference: string) => {
    const current = promptStore.text.trim();
    promptStore.text = current
      ? `${current}\n参考公开设定（需自行确认）：\n${reference}`
      : `参考公开设定（需自行确认）：\n${reference}`;
    promptStore.status = '已填入公开设定参考，请确认后重新生成';
    message.success('已填入描述框；不会覆盖现有提示词或角色预设');
  };

  const availableClothingPresets = clothingPresets.filter(
    (item) => !(restrictionEnabled && item.nsfw),
  );
  const poseCategoryGroups = Array.from(new Set(posePresets.map(presetCategoryGroup)));
  const clothingCategoryGroups = Array.from(
    new Set(availableClothingPresets.map(presetCategoryGroup)),
  );

  return (
    <div className="prompt-layout">
      <Radio.Group
        value={mode}
        onChange={(e) => (promptStore.mode = e.target.value)}
        optionType="button"
        style={{ marginBottom: 12 }}
      >
        <Radio.Button value="image">图片反推</Radio.Button>
        <Radio.Button value="text">文字生成</Radio.Button>
      </Radio.Group>
      <div className="draw-grid">
        <div className="controls panel-box">
          {mode === 'image' ? (
            <>
              <Space style={{ marginBottom: 8 }}>
                <span>视觉模型</span>
                <Select
                  style={{ width: 200 }}
                  value={vlmModel || undefined}
                  placeholder="选择模型"
                  options={['huihui_ai/qwen2.5-vl-abliterated:7b', 'qwen2.5vl:7b', 'qwen2.5vl:3b'].map((value) => ({ label: value, value }))}
                  onChange={handleVlmChange}
                />
              </Space>
              <Space wrap style={{ marginTop: 8 }}>
                <span>反推模式</span>
                <Segmented
                  value={reverseMode}
                  onChange={(value) =>
                    setReverseOptions(
                      value as 'hybrid' | 'wd14' | 'vlm',
                      reverseThreshold,
                    )
                  }
                  options={[
                    { label: '混合（推荐）', value: 'hybrid' },
                    { label: 'WD14 标签', value: 'wd14' },
                    { label: '视觉模型', value: 'vlm' },
                  ]}
                />
                {reverseMode !== 'vlm' ? (
                  <>
                    <Tooltip title="与数据集打标同一个模型、同一套阈值口径。调低更全、调高更准。">
                      <span>WD14 阈值</span>
                    </Tooltip>
                    <InputNumber
                      min={0.1}
                      max={0.9}
                      step={0.05}
                      value={reverseThreshold}
                      onChange={(value) =>
                        setReverseOptions(
                          reverseMode,
                          Number(value ?? reverseThreshold),
                        )
                      }
                    />
                  </>
                ) : null}
              </Space>
              <label>选择图片</label>
              <input type="file" accept="image/*" onChange={(e) => handleFile(e.target.files?.[0])} />
              {imageBase64 ? <img className="preview" src={imageBase64} alt="预览" /> : null}
              <Button type="primary" block onClick={() => void fromImage()} style={{ marginTop: 12 }}>
                识别图片
              </Button>
            </>
          ) : (
            <>
              <label>描述你的画面</label>
              <Input.TextArea
                value={text}
                onChange={(e) => (promptStore.text = e.target.value)}
                rows={5}
                placeholder="例如：一个蓝发少女，穿校服，在樱花树下微笑"
              />
              <Button type="primary" block onClick={() => void fromText()} style={{ marginTop: 12 }}>
                生成提示词
              </Button>
            </>
          )}
        </div>
        <div className="result-col">
          <div className="result panel-box">
            <div className="status">{status}</div>
            {result?.description ? <div className="result-block">原始描述：{result.description}</div> : null}
            {result?.prompt ? <div className="result-block">英文提示词：{result.prompt}</div> : null}
            {result?.prompt_translation ? <div className="result-block">中文翻译：{result.prompt_translation}</div> : null}
            {validationIssues.length > 0 ? (
              <div style={{ marginTop: 8 }}>
                <div className="setting-label">提示词校验</div>
                {validationIssues.map((item, index) => (
                  <div
                    key={index}
                    style={{
                      color: item.type === 'error' ? '#dc2626' : item.type === 'warning' ? '#d97706' : '#6b7280',
                      fontSize: 12,
                    }}
                  >
                    {item.type === 'error' ? '错误' : item.type === 'warning' ? '提醒' : '建议'}：{item.message}
                  </div>
                ))}
              </div>
            ) : null}
            {!restrictionEnabled && result?.prompt ? (
              <div style={{ marginTop: 8 }}>
                <div className="setting-label">体位预设</div>
                {poseCategoryGroups.map((categoryGroup) => {
                  const groupItems = posePresets.filter(
                    (item) => presetCategoryGroup(item) === categoryGroup,
                  );
                  const subcategories = Array.from(new Set(groupItems.map(presetSubcategory)));
                  return (
                    <div key={categoryGroup} style={{ marginTop: 6 }}>
                      <Tag color="blue">{categoryGroup}</Tag>
                      {subcategories.map((subcategory) => {
                        const items = groupItems.filter(
                          (item) => presetSubcategory(item) === subcategory,
                        );
                        return (
                          <Space
                            key={`${categoryGroup}-${subcategory}`}
                            wrap
                            style={{ marginTop: 4, marginBottom: 4 }}
                          >
                            <Tag>{subcategory}</Tag>
                            {items.map((item) => (
                              <Tooltip
                                key={item.id}
                                title={
                                  <div style={{ maxWidth: 260 }}>
                                    <div>{item.label}：{item.translation || '暂无说明'}</div>
                                    {item.image ? (
                                      <img
                                        src={item.image}
                                        alt={item.label}
                                        style={{ width: 200, marginTop: 4, borderRadius: 6, display: 'block' }}
                                      />
                                    ) : null}
                                  </div>
                                }
                              >
                                <Tag.CheckableTag
                                  checked={selectedPoseId === item.id}
                                  onChange={() => handlePoseToggle(item)}
                                >
                                  {item.label}
                                </Tag.CheckableTag>
                              </Tooltip>
                            ))}
                          </Space>
                        );
                      })}
                    </div>
                  );
                })}
                <Input.TextArea
                  rows={2}
                  value={refineRequirements}
                  onChange={(e) => setRefineRequirements(e.target.value)}
                  placeholder="调整要求，例如：体位改为背后位，去掉内衣"
                  style={{ marginTop: 8 }}
                />
                <Space style={{ marginTop: 8 }}>
                  <Tooltip title="根据你的调整要求和体位预设重新生成提示词，并按角色/动作/服装/场景/画风拆分。">
                    <Button type="primary" loading={refining} onClick={() => void handleRefine()}>
                      细化并拆分
                    </Button>
                  </Tooltip>
                  <Tooltip title="不改变提示词内容，只把当前提示词按角色（男A/女B…）和类别重新分组。">
                    <Button loading={refining} onClick={() => void handleRoleSplit()}>
                      角色感知拆分
                    </Button>
                  </Tooltip>
                  <Tooltip title="通过多轮问答补全画面细节，逐步生成最终提示词。">
                    <Button onClick={openClarify}>多轮澄清</Button>
                  </Tooltip>
                </Space>
              </div>
            ) : null}
            {result?.prompt && availableClothingPresets.length > 0 ? (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <div className="setting-label" style={{ marginBottom: 0 }}>
                    服装预设
                  </div>
                  <Select
                    size="small"
                    value={clothingScope}
                    options={CLOTHING_SCOPE_OPTIONS}
                    onChange={setClothingScope}
                    style={{ width: 110 }}
                  />
                </div>
                {clothingCategoryGroups.map((categoryGroup) => {
                  const groupItems = availableClothingPresets.filter(
                    (item) => presetCategoryGroup(item) === categoryGroup,
                  );
                  const subcategories = Array.from(new Set(groupItems.map(presetSubcategory)));
                  return (
                    <div key={categoryGroup} style={{ marginTop: 6 }}>
                      <Tag color="blue">{categoryGroup}</Tag>
                      {subcategories.map((subcategory) => {
                        const items = groupItems.filter(
                          (item) => presetSubcategory(item) === subcategory,
                        );
                        return (
                          <Space
                            key={`${categoryGroup}-${subcategory}`}
                            wrap
                            style={{ marginTop: 4, marginBottom: 4 }}
                          >
                            <Tag>{subcategory}</Tag>
                            {items.map((item) => (
                              <Tooltip
                                key={item.id}
                                title={
                                  <div style={{ maxWidth: 220 }}>
                                    <div>
                                      {item.label}：{item.translation}
                                    </div>
                                    {item.image ? (
                                      <img
                                        src={item.image}
                                        alt={item.label}
                                        style={{ width: 150, marginTop: 4, borderRadius: 6, display: 'block' }}
                                      />
                                    ) : null}
                                  </div>
                                }
                              >
                                <Tag.CheckableTag
                                  checked={selectedClothingId === item.id}
                                  onChange={() => handleClothingToggle(item)}
                                >
                                  {item.label}
                                  {item.nsfw ? ' R18' : ''}
                                </Tag.CheckableTag>
                              </Tooltip>
                            ))}
                          </Space>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            ) : null}
            {refined ? (
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="result-block">细化提示词：{refined.prompt}</div>
                {refined.translation ? <div className="result-block">中文翻译：{refined.translation}</div> : null}
                {refined.groups.map((group) => (
                  <div key={group.label} className="group-card">
                    <div className="group-header">
                      <span className="setting-label">{group.label}</span>
                    </div>
                    <Space wrap>
                      {Array.from(new Set(group.items)).map((tag, index) => (
                        <Tooltip key={`${tag}-${index}`} title={tagTranslations[tag] || '暂无翻译'}>
                          <Tag style={{ cursor: 'pointer' }} onClick={() => void copyTag(tag)}>
                            {tag}
                          </Tag>
                        </Tooltip>
                      ))}
                    </Space>
                  </div>
                ))}
              </div>
            ) : null}
            <Space direction="vertical" style={{ marginTop: 12 }}>
              <Checkbox checked={autoDraw} onChange={(e) => (promptStore.autoDraw = e.target.checked)}>
                发送到绘画区后自动开始生成
              </Checkbox>
              <Button onClick={sendToDraw}>发送到绘画区</Button>
              <Button onClick={() => setScenePresetsOpen(true)}>场景预设</Button>
              <Button onClick={() => setPresetCompositionOpen(true)}>预设组合</Button>
              <Button onClick={() => setCharacterAppearanceOpen(true)}>查询并填入角色外貌</Button>
              <Button onClick={() => setPublicSettingOpen(true)}>查询公开设定</Button>
            </Space>
          </div>
          <div className="panel-box" style={{ marginTop: 12 }}>
        <div className="train-section-title">智能拆分提示词集</div>
        <Input.TextArea
          rows={4}
          value={splitText}
          onChange={(e) => setSplitText(e.target.value)}
          placeholder="粘贴逗号或换行分隔的提示词集"
          style={{ marginTop: 8 }}
        />
        <Space style={{ marginTop: 8 }}>
          <Button type="primary" loading={splitLoading} onClick={() => void handleSplit()}>
            智能拆分
          </Button>
          {splitResult ? (
            <Button loading={splitLoading} onClick={() => void handleSplit()}>
              重新拆分
            </Button>
          ) : null}
        </Space>
        {splitResult ? (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {CATEGORY_META.map((meta) => {
              const tags = splitResult[meta.key] || [];
              if (tags.length === 0) return null;
              return (
                <div
                  key={meta.key}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    border: '1px solid #e5e7eb',
                    borderRadius: 6,
                    padding: 8,
                  }}
                >
                  <Space>
                    <span className="setting-label">{meta.label}</span>
                    <Input
                      size="small"
                      value={names[meta.key] || ''}
                      onChange={(e) => setNames({ ...names, [meta.key]: e.target.value })}
                      style={{ width: 220 }}
                    />
                    <Tag>{meta.type}</Tag>
                  </Space>
                  <Space wrap>
                    {tags.map((tag) => (
                      <Tag key={tag} closable onClose={() => removeTag(meta.key, tag)}>
                        {tag}
                      </Tag>
                    ))}
                    <Input
                      size="small"
                      value={newTags[meta.key] || ''}
                      onChange={(e) => setNewTags({ ...newTags, [meta.key]: e.target.value })}
                      onPressEnter={() => addTag(meta.key)}
                      placeholder="添加标签"
                      style={{ width: 140 }}
                    />
                    <Button size="small" onClick={() => addTag(meta.key)}>
                      添加
                    </Button>
                  </Space>
                </div>
              );
            })}
            <Button type="primary" loading={saving} onClick={() => void handleSave()} style={{ alignSelf: 'flex-start' }}>
              确认添加
            </Button>
          </div>
          ) : null}
          </div>
        </div>
      </div>
      <Modal
        title="多轮澄清"
        open={clarifyOpen}
        onCancel={() => setClarifyOpen(false)}
        footer={null}
        width={560}
      >
        <div className="clarify-chat">
          {clarifyMessages.map((item, index) => (
            <div key={index} className={`bubble ${item.role === 'user' ? 'user' : 'agent'}`}>
              {item.content}
            </div>
          ))}
          {clarifyLoading ? <div className="bubble agent">正在思考…</div> : null}
        </div>
        <div className="companion-composer" style={{ marginTop: 10 }}>
          <Input
            value={clarifyInput}
            onChange={(e) => setClarifyInput(e.target.value)}
            onPressEnter={() => void sendClarify()}
            disabled={clarifyLoading}
            placeholder="回答澄清问题…"
          />
          <Button type="primary" loading={clarifyLoading} onClick={() => void sendClarify()}>
            发送
          </Button>
        </div>
      </Modal>
      <CharacterAppearanceModal
        open={characterAppearanceOpen}
        onClose={() => setCharacterAppearanceOpen(false)}
        onApply={applyCharacterAppearance}
        onManageThumbnail={(selection) => {
          setCharacterAppearanceOpen(false);
          setPresetAssetSelection(selection);
          uiStore.activeTab = 'presetAssets';
        }}
        title="角色外观查询与填入"
      />
      <PublicSettingLookupModal
        open={publicSettingOpen}
        onClose={() => setPublicSettingOpen(false)}
        onUse={applyPublicSettings}
      />
      <ScenePresetsModal
        open={scenePresetsOpen}
        onClose={() => setScenePresetsOpen(false)}
        onInsert={insertScenePreset}
      />
      <PresetCompositionDrawer
        open={presetCompositionOpen}
        onClose={() => setPresetCompositionOpen(false)}
        onApply={applyPresetComposition}
        initialSelection={presetCompositionInitialSelection}
      />
    </div>
  );
}
