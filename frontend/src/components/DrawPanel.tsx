// AI 绘画工作区：多组提示词批量生成 + 标签中英对照
import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined, CloudOutlined, CopyOutlined, DatabaseOutlined, DeleteOutlined, DownOutlined, HolderOutlined, InfoCircleOutlined, InteractionOutlined, LeftOutlined, PictureOutlined, PlusOutlined, RedoOutlined, RightOutlined, SaveOutlined, SettingOutlined, SmileOutlined, StarFilled, StarOutlined, StopOutlined, UndoOutlined, UnorderedListOutlined, UpOutlined } from '@ant-design/icons';
import { Button, Checkbox, Collapse, Drawer, Image, Input, InputNumber, message, Modal, Popconfirm, Segmented, Select, Space, Switch, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import { useEffect, useRef, useState } from 'react';
import {
  api,
    type DrawResult,
    type LoraItem,
    type ModelItem,
    type ExpressionPreset,
    type PoseCatalogItem,
    type PresetComposition,
  type PresetCatalog,
  type PresetCompositionResult,
  type PresetScope,
  type PromptBlock,
  type PromptCharacter,
  type PromptDocumentResolveResult,
  type PromptDocumentV1,
  type ScenePreset,
  type TagTranslation,
    type WaterPreset,
} from '../api';
import PromptSetsDrawer from './PromptSetsDrawer';
import ImageLibraryDrawer from './ImageLibraryDrawer';
import CharacterAppearanceModal, { type CharacterAppearanceResult } from './CharacterAppearanceModal';
import ClothingPresetsModal from './ClothingPresetsModal';
import ExpressionPresetsModal from './ExpressionPresetsModal';
import PresetCompositionDrawer, { type PresetCompositionApplyMode } from './PresetCompositionDrawer';
import PresetCenterDrawer from './PresetCenterDrawer';
import type { PresetLibraryItem } from './PresetLibraryPanel';
import ScenePresetsModal from './ScenePresetsModal';
import WaterPresetsModal from './WaterPresetsModal';
import DrawLoraSelector from './DrawLoraSelector';
import DrawGenerationSettingsPanel from './DrawGenerationSettingsPanel';
import DrawPromptOutlineDrawer from './DrawPromptOutlineDrawer';
import { applyPreset, deletePreset, loadPresets, savePreset, type DrawPreset } from '../stores/presets';
import {
  applyLoraCombo,
  deleteLoraCombo,
  loadLoraCombos,
  saveLoraCombo,
  type LoraCombo,
} from '../stores/loraCombos';
import TagCompareTable from './TagCompareTable';
import { settingsStore } from '../stores/settings';
import type { ClothingPreset } from '../api';
import { formatClothingInsert, type ClothingScope } from '../clothingPresets';
import {
  formatPresetInsert,
  formatScenePresetInsert,
  posePromptForInsert,
  scenePromptForPeoplePolicy,
  type PosePromptDetail,
  type ScenePeoplePolicy,
} from '../presetComposition';
import PresetCategoryFilter, {
  matchesPresetCategory,
  presetCategoryGroup,
  presetSubcategory,
  sortPresetItems,
} from './PresetCategoryFilter';
import {
  addCharacter,
  addPresetRefToBlock,
  applyAppearancePresetToCharacter,
  applyExpressionPresetToCharacter,
  clonePromptDocument,
  createEmptyStructuredDocument,
  createPromptCharacter,
  BODY_BUILD_OPTIONS,
  HEIGHT_FRAME_OPTIONS,
  isPromptDocumentEmpty,
  mergeTags,
  moveCharacter,
  normalizePromptDocument,
  removeCharacter,
  resolveCharacterTargets,
  updateCharacter,
  updateCharacterBlock,
  updateCustom,
  updateGlobalBlock,
  updateInteraction,
  updateNegativeBlock,
  updateRawOverride,
} from '../promptDocument';
import {
  addGroup,
  clearDrawResult,
  createDrawGroup,
  duplicateGroup,
  drawStore,
  moveGroupTo,
  removeGroup,
  regenerateCurrent,
  resumeDrawTask,
  restoreDrawLast,
  runDraw,
  saveDrawState,
  setGroupMode,
  stopDraw,
  updateGroupDocument,
  updateGroupEnabled,
  updateLegacyBodyProfile,
  updateGroupCount,
  updateGroupPrompt,
  type DrawGroup,
} from '../stores/draw';
import { getRuntimeConfig } from '../stores/runtimeConfig';
import {
  presetAssetStore,
  setPresetAssetSelection,
  type PresetAssetSelection,
} from '../stores/presetAssetStore';
import { uiStore } from '../stores/ui';

type PosePreset = PoseCatalogItem;

const GLOBAL_BLOCK_LABELS: Record<keyof PromptDocumentV1['global'], string> = {
  quality: '质量',
  style: '风格',
  scene: '场景',
  camera: '镜头',
  lighting: '光照',
  constraints: '约束',
};

const NEGATIVE_BLOCK_LABELS: Record<keyof PromptDocumentV1['negative'], string> = {
  quality: '质量',
  anatomy: '人体结构',
  composition: '构图',
  style: '风格',
  content: '内容',
  custom: '自定义',
};

const CHARACTER_BLOCK_LABELS: Record<
  'appearance' | 'clothing' | 'body_modifications' | 'pose_or_action' | 'expression' | 'state',
  string
> = {
  appearance: '外貌',
  clothing: '服装',
  body_modifications: '身体改造',
  pose_or_action: '角色动作',
  expression: '表情',
  state: '状态',
};
const DRAW_RESULT_FAVORITES_KEY = 'rider-studio:draw-result-favorites-v1';

function loadDrawResultFavorites(): string[] {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(DRAW_RESULT_FAVORITES_KEY) || '[]',
    ) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string')
      : [];
  } catch {
    return [];
  }
}

function cloneDrawHistory<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// 把提示词按逗号拆成单个标签
function tagsOf(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

// 逐标签翻译，返回 tag -> translation 映射
async function translateTags(text: string): Promise<Record<string, string>> {
  if (!text.trim()) return {};
  try {
    const { data } = await api.post<{ items: TagTranslation[] }>('/translate/tags', { text });
    const map: Record<string, string> = {};
    (data.items || []).forEach((item) => {
      map[item.tag] = item.translation;
    });
    return map;
  } catch (e) {
    return {};
  }
}

function duplicateCharacter(document: PromptDocumentV1, characterId: string): PromptDocumentV1 {
  const next = clonePromptDocument(document);
  const sourceIndex = next.characters.findIndex((character) => character.id === characterId);
  if (sourceIndex < 0) return next;
  const suffix = `${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  const source = next.characters[sourceIndex];
  const copy = createPromptCharacter(next.characters.length, {
    ...source,
    id: `character-${suffix}`,
    display_name: `${source.display_name} 副本`,
  });
  next.characters = [
    ...next.characters.slice(0, sourceIndex + 1),
    copy,
    ...next.characters.slice(sourceIndex + 1),
  ].map((character, order) => ({ ...character, order }));
  return next;
}

function PromptBlockEditor({
  label,
  block,
  onChange,
  rows = 2,
}: {
  label: string;
  block: PromptBlock;
  onChange: (block: PromptBlock) => void;
  rows?: number;
}) {
  return (
    <div className="setting-field" style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span className="setting-label" style={{ marginBottom: 0 }}>
          {label}
        </span>
        <Checkbox
          checked={block.enabled !== false}
          onChange={(event) => onChange({ ...block, enabled: event.target.checked })}
        >
          启用
        </Checkbox>
      </div>
      <Input.TextArea
        rows={rows}
        value={block.tags.join(', ')}
        disabled={block.enabled === false}
        onChange={(event) => onChange({ ...block, tags: tagsOf(event.target.value) })}
      />
    </div>
  );
}

interface StructuredPreview {
  loading: boolean;
  prompt: string;
  negativePrompt: string;
  errors: string[];
  warnings: string[];
}

interface DrawHistorySnapshot {
  groups: DrawGroup[];
  negativePrompt: string;
  model: string;
  width: number;
  height: number;
  steps: number | null;
  cfg: number;
  loras: string[];
  loraStrengthModel: number;
  loraStrengthClip: number;
  loraStrengths: Record<string, { model: number; clip: number }>;
}

export interface DrawPanelProps {
  controlledActiveGroupId?: string;
  onActiveGroupIdChange?: (id: string) => void;
  onSendToInpaint?: (source: {
    recordId?: number;
    imageUrl: string;
    width: number;
    height: number;
    label: string;
    prompt: string;
    negativePrompt: string;
    promptDocument?: PromptDocumentV1 | null;
  }) => void;
}

export default function DrawPanel({
  controlledActiveGroupId,
  onActiveGroupIdChange,
  onSendToInpaint,
}: DrawPanelProps = {}) {
  const { restrictionEnabled } = settingsStore;
  const runtimeConfig = getRuntimeConfig();
  const drawConfig = runtimeConfig.draw;
  const {
    model,
    groups,
    negativePrompt,
    width,
    height,
    steps,
    cfg,
    loras,
    loraStrengthModel,
    loraStrengthClip,
    loraStrengths,
    lorasVersion,
    generating,
    status,
    total,
    done,
    results,
    restoreVersion,
  } = drawStore;
  const [lorasList, setLorasList] = useState<LoraItem[]>([]);
  const [lorasLoading, setLorasLoading] = useState(false);
  const [modelsList, setModelsList] = useState<ModelItem[]>([]);
  const [groupTagMaps, setGroupTagMaps] = useState<Record<string, Record<string, string>>>({});
  const [negTagMap, setNegTagMap] = useState<Record<string, string>>({});
  const [elapsed, setElapsed] = useState(0);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [batchCompare, setBatchCompare] = useState(false);
  const [navMode, setNavMode] = useState<'loop' | 'stop'>('loop');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [favoriteResults, setFavoriteResults] = useState<string[]>(loadDrawResultFavorites);
  const makeHistorySnapshot = (): DrawHistorySnapshot =>
    cloneDrawHistory({
      groups,
      negativePrompt,
      model,
      width,
      height,
      steps,
      cfg,
      loras,
      loraStrengthModel,
      loraStrengthClip,
      loraStrengths,
    });
  const historyRef = useRef<{
    entries: DrawHistorySnapshot[];
    index: number;
  }>({
    entries: [makeHistorySnapshot()],
    index: 0,
  });
  const historyKeyRef = useRef(JSON.stringify(makeHistorySnapshot()));
  const [historyStatus, setHistoryStatus] = useState({ canUndo: false, canRedo: false });
  const thumbsRef = useRef<HTMLDivElement>(null);
  const [promptSetsOpen, setPromptSetsOpen] = useState(false);
  const [imageLibraryOpen, setImageLibraryOpen] = useState(false);
  const [poseOpen, setPoseOpen] = useState(false);
  const [posePresets, setPosePresets] = useState<PosePreset[]>([]);
  const [clothingPresetsOpen, setClothingPresetsOpen] = useState(false);
  const [scenePresetsOpen, setScenePresetsOpen] = useState(false);
  const [expressionPresetsOpen, setExpressionPresetsOpen] = useState(false);
  const [waterPresetsOpen, setWaterPresetsOpen] = useState(false);
  const [presetCompositionOpen, setPresetCompositionOpen] = useState(false);
  const [presetCenterOpen, setPresetCenterOpen] = useState(false);
  const [compositionInitialSelection, setCompositionInitialSelection] =
    useState<{
      kind: string;
      id: string;
      label: string;
      token: number;
    } | null>(null);
  const { selection: presetAssetSelection } = presetAssetStore;
  const [clothingSetOpen, setClothingSetOpen] = useState(false);
  const [clothingSetName, setClothingSetName] = useState('');
  const [savingClothingSet, setSavingClothingSet] = useState(false);
  const [poseLoading, setPoseLoading] = useState(false);
  const [poseKeyword, setPoseKeyword] = useState('');
  const [poseCategoryGroup, setPoseCategoryGroup] = useState('');
  const [poseSubcategory, setPoseSubcategory] = useState('');
  const [poseOrientation, setPoseOrientation] = useState('');
  const [posePeople, setPosePeople] = useState('');
  const [posePromptDetail, setPosePromptDetail] = useState<PosePromptDetail>('core');
  const [characterAppearanceOpen, setCharacterAppearanceOpen] = useState(false);
  const [presets, setPresets] = useState<DrawPreset[]>(loadPresets);
  const [presetSelected, setPresetSelected] = useState('');
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [commonCombos, setCommonCombos] = useState<LoraCombo[]>(loadLoraCombos);
  const [comboSaveOpen, setComboSaveOpen] = useState(false);
  const [comboManageOpen, setComboManageOpen] = useState(false);
  const [comboName, setComboName] = useState('');
  const [visualReview, setVisualReview] = useState(true);
  const [validationText, setValidationText] = useState('');
  const [internalActiveGroupId, setInternalActiveGroupId] = useState(
    groups[0]?.id || '',
  );
  const activeGroupId = controlledActiveGroupId || internalActiveGroupId;
  const setActiveGroupId = (id: string) => {
    setInternalActiveGroupId(id);
    onActiveGroupIdChange?.(id);
  };
  const [activeCharacterIds, setActiveCharacterIds] = useState<Record<string, string>>({});
  const [expandedStructuredGroups, setExpandedStructuredGroups] = useState<string[]>([]);
  const [expandedGroupIds, setExpandedGroupIds] = useState<string[]>([]);
  const [draggedGroupId, setDraggedGroupId] = useState('');
  const [structuredPreviews, setStructuredPreviews] = useState<Record<string, StructuredPreview>>({});

  const totalRequested = groups.reduce(
    (sum, group) =>
      sum +
      (group.enabled === false
        ? 0
        : Math.min(Math.max(drawConfig.group_count_min, group.count), drawConfig.max_group_count)),
    0,
  );
  const sizeOptions = drawConfig.allowed_sizes.map(([optionWidth, optionHeight]) => {
    const orientation =
      optionWidth === optionHeight ? '方形' : optionWidth < optionHeight ? '竖版' : '横版';
    return {
      label: `${orientation} ${optionWidth}×${optionHeight}`,
      value: `${optionWidth}x${optionHeight}`,
    };
  });
  if (!sizeOptions.some((item) => item.value === `${width}x${height}`)) {
    sizeOptions.unshift({ label: `当前 ${width}×${height}`, value: `${width}x${height}` });
  }

  const activeGroup = groups.find((group) => group.id === activeGroupId) || groups[0];
  const activeCharacterId =
    (activeGroup ? activeCharacterIds[activeGroup.id] : '') ||
    activeGroup?.prompt_document?.characters.find((character) => character.enabled !== false)?.id ||
    activeGroup?.prompt_document?.characters[0]?.id ||
    '';
  const activeCharacterIdForGroup = (group: (typeof groups)[number]) =>
    activeCharacterIds[group.id] ||
    group.prompt_document?.characters.find((character) => character.enabled !== false)?.id ||
    group.prompt_document?.characters[0]?.id ||
    '';

  const restoreHistorySnapshot = (snapshot: DrawHistorySnapshot) => {
    const restored = cloneDrawHistory(snapshot);
    historyKeyRef.current = JSON.stringify(restored);
    drawStore.groups = restored.groups;
    drawStore.negativePrompt = restored.negativePrompt;
    drawStore.model = restored.model;
    drawStore.width = restored.width;
    drawStore.height = restored.height;
    drawStore.steps = restored.steps;
    drawStore.cfg = restored.cfg;
    drawStore.loras = restored.loras;
    drawStore.loraStrengthModel = restored.loraStrengthModel;
    drawStore.loraStrengthClip = restored.loraStrengthClip;
    drawStore.loraStrengths = restored.loraStrengths;
  };

  const syncHistoryStatus = () => {
    const history = historyRef.current;
    setHistoryStatus({
      canUndo: history.index > 0,
      canRedo: history.index < history.entries.length - 1,
    });
  };

  const undoDrawHistory = () => {
    const history = historyRef.current;
    if (history.index <= 0) return;
    history.index -= 1;
    restoreHistorySnapshot(history.entries[history.index]);
    syncHistoryStatus();
  };

  const redoDrawHistory = () => {
    const history = historyRef.current;
    if (history.index >= history.entries.length - 1) return;
    history.index += 1;
    restoreHistorySnapshot(history.entries[history.index]);
    syncHistoryStatus();
  };

  const updateDocument = (
    groupId: string,
    updater: (document: PromptDocumentV1) => PromptDocumentV1,
  ) => {
    const group = drawStore.groups.find((item) => item.id === groupId);
    if (!group) return;
    const document = normalizePromptDocument(group.prompt_document || createEmptyStructuredDocument());
    updateGroupDocument(groupId, updater(document));
  };

  const withNegativeTags = (document: PromptDocumentV1): PromptDocumentV1 =>
    updateNegativeBlock(document, 'custom', (block) => ({
      ...block,
      tags: mergeTags(block.tags, tagsOf(drawStore.negativePrompt)),
    }));

  useEffect(() => {
    setPreviewIndex(0);
  }, [restoreVersion]);

  useEffect(() => {
    if (groups.length === 0) return;
    if (!groups.some((group) => group.id === activeGroupId)) {
      setActiveGroupId(groups[0].id);
    }
  }, [groups, activeGroupId]);

  useEffect(() => {
    api
      .get<{ enabled: boolean }>('/settings/visual-review')
      .then((res) => setVisualReview(Boolean(res.data.enabled)))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      const first = groups.find((group) => group.prompt.trim());
      if (!first) {
        setValidationText('');
        return;
      }
      try {
        const { data } = await api.post<{ errors: { message: string }[]; warnings: { message: string }[] }>('/prompt/validate', {
          prompt: first.prompt,
          negative_prompt: negativePrompt,
        });
        const issues = [...data.errors, ...data.warnings];
        setValidationText(issues.length ? issues[0].message : '校验通过');
      } catch {
        setValidationText('');
      }
    }, 600);
    return () => window.clearTimeout(timer);
  }, [groups, negativePrompt]);

  const structuredPreviewKey = JSON.stringify(
    groups
      .filter((group) => group.mode === 'structured')
      .map((group) => [group.id, group.prompt_document]),
  );

  useEffect(() => {
    const structuredGroups = groups.filter((group) => group.mode === 'structured');
    if (structuredGroups.length === 0) {
      setStructuredPreviews({});
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const entries = await Promise.all(
        structuredGroups.map(async (group) => {
          try {
            const document = withNegativeTags(
              group.prompt_document || createEmptyStructuredDocument(),
            );
            const { data } = await api.post<PromptDocumentResolveResult>(
              '/prompt-agent/resolve-prompt-document',
              { document },
            );
            return [
              group.id,
              {
                loading: false,
                prompt: data.prompt,
                negativePrompt: data.negative_prompt,
                errors: data.errors || [],
                warnings: data.warnings || [],
              },
            ] as const;
          } catch (error: unknown) {
            const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
            return [
              group.id,
              {
                loading: false,
                prompt: '',
                negativePrompt: '',
                errors: [detail || '结构化文档解析失败'],
                warnings: [],
              },
            ] as const;
          }
        }),
      );
      if (!cancelled) setStructuredPreviews(Object.fromEntries(entries));
    }, 500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [structuredPreviewKey, negativePrompt]);

  // 生成过程中每秒更新按钮上的计时
  useEffect(() => {
    if (generating) {
      setElapsed(0);
      const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
      return () => window.clearInterval(timer);
    }
    setElapsed(0);
  }, [generating]);

  // 自动保存用户绘画配置，刷新或关闭页面后恢复
  useEffect(() => {
    saveDrawState({
      model,
      groups,
      negativePrompt,
      width,
      height,
      steps,
      cfg,
      loras,
      loraStrengthModel,
      loraStrengthClip,
      loraStrengths,
    });
  }, [model, groups, negativePrompt, width, height, steps, cfg, loras, loraStrengthModel, loraStrengthClip, loraStrengths]);

  useEffect(() => {
    try {
      localStorage.setItem(
        DRAW_RESULT_FAVORITES_KEY,
        JSON.stringify(favoriteResults),
      );
    } catch {
      // 隐私模式下不持久化结果收藏
    }
  }, [favoriteResults]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const snapshot = makeHistorySnapshot();
      const key = JSON.stringify(snapshot);
      if (key === historyKeyRef.current) return;
      const history = historyRef.current;
      history.entries = history.entries.slice(0, history.index + 1);
      history.entries.push(snapshot);
      if (history.entries.length > 50) history.entries.shift();
      history.index = history.entries.length - 1;
      historyKeyRef.current = key;
      syncHistoryStatus();
    }, 450);
    return () => window.clearTimeout(timer);
  }, [
    groups,
    negativePrompt,
    model,
    width,
    height,
    steps,
    cfg,
    loras,
    loraStrengthModel,
    loraStrengthClip,
    loraStrengths,
  ]);

  useEffect(() => {
    const handleUndoRedo = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redoDrawHistory();
        else undoDrawHistory();
      } else if (event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redoDrawHistory();
      }
    };
    window.addEventListener('keydown', handleUndoRedo);
    return () => window.removeEventListener('keydown', handleUndoRedo);
  }, []);

  // 新结果出现时自动预览最新一张
  useEffect(() => {
    if (results.length > 0) setPreviewIndex(results.length - 1);
  }, [results.length]);

  // 当前预览变化时自动滚动缩略图条
  useEffect(() => {
    const container = thumbsRef.current;
    if (!container) return;
    const element = container.querySelector<HTMLElement>(`[data-index="${previewIndex}"]`);
    if (element) {
      container.scrollTo({
        left: element.offsetLeft - container.clientWidth / 2 + element.clientWidth / 2,
        behavior: 'smooth',
      });
    }
  }, [previewIndex, results.length]);

  // 页面刷新后：先恢复未完成任务，再恢复上次已完成结果
  useEffect(() => {
    void (async () => {
      const resumed = await resumeDrawTask();
      if (!resumed) await restoreDrawLast();
    })();
  }, []);

  const handleClearResult = () => {
    Modal.confirm({
      title: '确认清空当前结果？',
      content: '只清空当前预览结果，不会删除已生成的图片文件。',
      okText: '清空',
      okButtonProps: { danger: true },
      onOk: () => {
        clearDrawResult();
        setPreviewIndex(0);
        setBatchCompare(false);
      },
    });
  };

  const goPrev = () => {
    if (results.length === 0) return;
    setPreviewIndex(navMode === 'loop' ? (previewIndex - 1 + results.length) % results.length : Math.max(0, previewIndex - 1));
  };

  const goNext = () => {
    if (results.length === 0) return;
    setPreviewIndex(navMode === 'loop' ? (previewIndex + 1) % results.length : Math.min(results.length - 1, previewIndex + 1));
  };

  // 方向键切换上一张/下一张
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) {
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        goPrev();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        goNext();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [previewIndex, results.length, navMode]);

  const loadLoras = () => {
    setLorasLoading(true);
    api
      .get('/loras')
      .then((res) => {
        const list = res.data.loras || [];
        setLorasList(list);
        const valid = drawStore.loras.filter((name) =>
          list.some((item: LoraItem) => item.name === name && item.compatible !== false),
        );
        if (valid.length !== drawStore.loras.length) drawStore.loras = valid;
      })
      .catch(() => setLorasList([]))
      .finally(() => setLorasLoading(false));
  };

  const handleDeleteLora = async (item: LoraItem) => {
    try {
      await api.delete(`/loras/${encodeURIComponent(item.name)}`);
      drawStore.lorasVersion += 1;
      drawStore.loras = drawStore.loras.filter((name) => name !== item.name);
      message.success(`已删除 ${item.name}`);
      loadLoras();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const openPoseTable = () => {
    setPoseOpen(true);
    setPoseLoading(true);
    setPoseKeyword('');
    setPoseCategoryGroup('');
    setPoseSubcategory('');
    setPoseOrientation('');
    setPosePeople('');
    setPosePromptDetail('core');
    api
      .get<{ items: PosePreset[] }>('/prompt-agent/pose-presets')
      .then((res) => setPosePresets(sortPresetItems(res.data.items || [])))
      .catch(() => {
        setPosePresets([]);
        message.error('体位预设加载失败');
      })
      .finally(() => setPoseLoading(false));
  };

  const openPresetAssetWorkshop = (selection: PresetAssetSelection | null = null) => {
    if (selection) {
      setPresetAssetSelection(selection);
    }
    uiStore.activeTab = 'presetAssets';
  };

  const insertPoseTags = (
    preset: PosePreset,
    detail: PosePromptDetail = 'core',
  ) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    const posePrompt = posePromptForInsert(preset, detail);
    const additions = tagsOf(posePrompt);
    if (!target) {
      const group = createDrawGroup('', 'group-pose-insert', 'structured');
      group.prompt_document = updateInteraction(group.prompt_document || createEmptyStructuredDocument(), (interaction) => ({
        ...interaction,
        action_tags: mergeTags(interaction.action_tags, additions),
        pose_preset: { preset_id: preset.id, version: 1 },
      }));
      drawStore.groups = [group];
      setActiveGroupId(group.id);
      message.success(
        `已把「${preset.label}」${detail === 'core' ? '精简版' : '完整版'}写入互动块`,
      );
      return;
    }
    if (target.mode === 'legacy') {
      const text = additions.join(', ');
      updateGroupPrompt(target.id, target.prompt.trim() ? `${target.prompt.trim()}, ${text}` : text);
    } else {
      updateDocument(target.id, (document) =>
        updateInteraction(document, (interaction) => ({
          ...interaction,
          action_tags: mergeTags(interaction.action_tags, additions),
          pose_preset: { preset_id: preset.id, version: 1 },
        })),
      );
    }
    message.success(
      `已把「${preset.label}」${detail === 'core' ? '精简版' : '完整版'}写入当前组互动块`,
    );
  };

  const insertClothingPreset = (preset: ClothingPreset, scope: ClothingScope) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!target) {
      const group = createDrawGroup('', 'group-clothing-insert', 'structured');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
    }
    const resolvedTarget =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!resolvedTarget) return;
    const parts: string[] = [];
    if (scope === 'all') {
      const existingTags = new Set(tagsOf(resolvedTarget.prompt).map((tag) => tag.toLowerCase()));
      const addedTags = preset.tags.filter((tag) => !existingTags.has(tag.toLowerCase()));
      if (addedTags.length > 0) {
        parts.push(addedTags.join(', '));
      }
      if (
        preset.draw_prompt &&
        !resolvedTarget.prompt.toLowerCase().includes(preset.draw_prompt.slice(0, 20).toLowerCase())
      ) {
        parts.push(preset.draw_prompt);
      }
    } else {
      const fragment = formatClothingInsert(preset, scope);
      if (!resolvedTarget.prompt.toLowerCase().includes(fragment.toLowerCase())) {
        parts.push(fragment);
      }
    }
    if (resolvedTarget.mode === 'legacy' && parts.length === 0) {
      message.info(`「${preset.label}」已在当前提示词中`);
      return;
    }
    if (resolvedTarget.mode === 'structured') {
      const additions = mergeTags(
        preset.tags,
        preset.draw_prompt ? tagsOf(preset.draw_prompt) : [],
      );
      updateDocument(resolvedTarget.id, (document) => {
        const targetIds = resolveCharacterTargets(document, activeCharacterId, scope);
        return targetIds.reduce(
          (next, characterId) =>
            updateCharacterBlock(next, characterId, 'clothing', (block) =>
              addPresetRefToBlock(
                { ...block, tags: mergeTags(block.tags, additions), source: 'clothing_preset' },
                preset.id,
                1,
                scope,
              ),
            ),
          document,
        );
      });
    } else {
      const nextPrompt = resolvedTarget.prompt.trim()
        ? `${resolvedTarget.prompt.trim()}, ${parts.join(', ')}`
        : parts.join(', ');
      updateGroupPrompt(resolvedTarget.id, nextPrompt);
    }
    const conflictText =
      resolvedTarget.mode === 'structured'
        ? (resolvedTarget.prompt_document?.characters || [])
            .flatMap((character) => character.clothing.tags)
            .join(', ')
        : resolvedTarget.prompt;
    const conflict = /\b(nude|naked|topless|no clothes)\b/i.test(conflictText);
    if (conflict) {
      message.warning(`已插入「${preset.label}」，但提示词含裸露标签，可能互相冲突`);
    } else {
      message.success(`已把「${preset.label}」写入目标角色服装块`);
    }
  };

  const insertExpressionPreset = (preset: ExpressionPreset, scope: PresetScope) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!target) {
      const group = createDrawGroup('', 'group-expression-insert', 'structured');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
    }
    const resolvedTarget =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!resolvedTarget) return;

    if (resolvedTarget.mode === 'legacy') {
      const fragment = formatPresetInsert(preset, scope);
      if (resolvedTarget.prompt.toLowerCase().includes(fragment.toLowerCase())) {
        message.info(`「${preset.label}」已在当前提示词中`);
        return;
      }
      updateGroupPrompt(
        resolvedTarget.id,
        resolvedTarget.prompt.trim()
          ? `${resolvedTarget.prompt.trim()}, ${fragment}`
          : fragment,
      );
    } else {
      updateDocument(resolvedTarget.id, (document) => {
        const targetIds = resolveCharacterTargets(document, activeCharacterId, scope);
        return targetIds.reduce(
          (next, characterId) =>
            applyExpressionPresetToCharacter(next, characterId, preset, scope),
          document,
        );
      });
    }
    message.success(`已把「${preset.label}」写入目标角色表情块`);
  };

  const insertWaterPreset = (preset: WaterPreset, scope: PresetScope) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!target) {
      const group = createDrawGroup('', 'group-water-insert', 'structured');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
    }
    const resolvedTarget =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!resolvedTarget) return;

    if (resolvedTarget.mode === 'legacy') {
      const fragment =
        preset.target === '环境'
          ? preset.tags.join(', ')
          : formatPresetInsert(preset, scope);
      if (resolvedTarget.prompt.toLowerCase().includes(fragment.toLowerCase())) {
        message.info(`「${preset.label}」已在当前提示词中`);
        return;
      }
      updateGroupPrompt(
        resolvedTarget.id,
        resolvedTarget.prompt.trim()
          ? `${resolvedTarget.prompt.trim()}, ${fragment}`
          : fragment,
      );
    } else if (preset.target === '环境') {
      updateDocument(resolvedTarget.id, (document) =>
        updateGlobalBlock(document, 'scene', (block) =>
          addPresetRefToBlock(
            {
              ...block,
              tags: mergeTags(block.tags, preset.tags),
              source: 'water_preset',
            },
            preset.id,
            1,
          ),
        ),
      );
    } else {
      updateDocument(resolvedTarget.id, (document) => {
        const targetIds = resolveCharacterTargets(document, activeCharacterId, scope);
        return targetIds.reduce(
          (next, characterId) =>
            updateCharacterBlock(next, characterId, 'state', (block) =>
              addPresetRefToBlock(
                {
                  ...block,
                  tags: mergeTags(block.tags, preset.tags),
                  source: 'water_preset',
                },
                preset.id,
                1,
                scope,
              ),
            ),
          document,
        );
      });
    }
    message.success(
      `已把「${preset.label}」写入${preset.target === '环境' ? '场景' : '目标角色状态'}块`,
    );
  };

  const insertScenePreset = (
    preset: ScenePreset,
    scope: PresetScope,
    peoplePolicy: ScenePeoplePolicy = 'occupied',
  ) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!target) {
      const group = createDrawGroup('', 'group-scene-insert', 'structured');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
    }
    const resolvedTarget =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!resolvedTarget) return;
    const scenePrompt = scenePromptForPeoplePolicy(preset, peoplePolicy);
    const fragment = formatScenePresetInsert(preset, scope, peoplePolicy);
    if (resolvedTarget.mode === 'legacy' && resolvedTarget.prompt.toLowerCase().includes(fragment.toLowerCase())) {
      message.info(`「${preset.label}」已在当前提示词中`);
      return;
    }
    if (resolvedTarget.mode === 'structured') {
      const additions = mergeTags(preset.tags, scenePrompt ? tagsOf(scenePrompt) : []);
      updateDocument(resolvedTarget.id, (document) =>
        updateGlobalBlock(document, 'scene', (block) =>
          addPresetRefToBlock(
            { ...block, tags: mergeTags(block.tags, additions), source: 'scene_preset' },
            preset.id,
            1,
            scope,
          ),
        ),
      );
    } else {
      updateGroupPrompt(
        resolvedTarget.id,
        resolvedTarget.prompt.trim() ? `${resolvedTarget.prompt.trim()}, ${fragment}` : fragment,
      );
    }
    message.success(`已把「${preset.label}」写入当前组场景块`);
  };

  const openLibraryComposition = (kind: string, item: PresetLibraryItem) => {
    setCompositionInitialSelection({
      kind,
      id: item.id,
      label: item.label,
      token: Date.now(),
    });
    setPresetCenterOpen(false);
    setPresetCompositionOpen(true);
  };

  const applyLibraryItem = (kind: string, item: PresetLibraryItem) => {
    if (kind === 'pose') {
      insertPoseTags(item as unknown as PosePreset);
      return;
    }
    if (kind === 'clothing') {
      insertClothingPreset(item as unknown as ClothingPreset, 'all');
      return;
    }
    if (kind === 'scene') {
      insertScenePreset(item as unknown as ScenePreset, 'all');
      return;
    }
    if (kind === 'character') {
      setPresetCenterOpen(false);
      setCharacterAppearanceOpen(true);
      message.info('请在角色外貌工具中选择角色槽位后应用');
      return;
    }
    openLibraryComposition(kind, item);
  };

  const applyPresetComposition = async (
    result: PresetCompositionResult,
    composition: PresetComposition,
    mode: PresetCompositionApplyMode,
  ) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!target) {
      const group = createDrawGroup(result.prompt, 'group-preset-composition', 'legacy');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
      message.success('已创建第一组组合提示词');
      return;
    }
    if (target.mode === 'legacy') {
      const nextPrompt =
        mode === 'replace'
          ? result.prompt
          : target.prompt.trim()
            ? `${target.prompt.trim()}, ${result.prompt}`
            : result.prompt;
      updateGroupPrompt(target.id, nextPrompt);
      message.success(mode === 'replace' ? '已替换当前组组合提示词' : '已追加组合提示词');
      return;
    }
    try {
      const { data: catalog } = await api.get<PresetCatalog>('/prompt-agent/preset-catalog');
      let document =
        mode === 'replace'
          ? createEmptyStructuredDocument()
          : normalizePromptDocument(target.prompt_document || createEmptyStructuredDocument());
      const pose = catalog.poses.find((item) => item.id === composition.pose_id);
      if (pose) {
        const additions = tagsOf(posePromptForInsert(pose, 'core'));
        document = updateInteraction(document, (interaction) => ({
          ...interaction,
          action_tags: mergeTags(interaction.action_tags, additions),
          pose_preset: { preset_id: pose.id, version: 1 },
        }));
      }
      const scene = catalog.scenes.find((item) => item.id === composition.scene_id);
      if (scene) {
        const scenePrompt = scenePromptForPeoplePolicy(scene, 'occupied');
        const additions = mergeTags(scene.tags, scenePrompt ? tagsOf(scenePrompt) : []);
        document = updateGlobalBlock(document, 'scene', (block) =>
          addPresetRefToBlock(
            { ...block, tags: mergeTags(block.tags, additions), source: 'preset_composition' },
            scene.id,
            1,
          ),
        );
      }
      for (const selection of composition.clothing) {
        const preset = catalog.clothing.find((item) => item.id === selection.id);
        if (!preset) continue;
        const additions = mergeTags(
          preset.tags,
          preset.draw_prompt ? tagsOf(preset.draw_prompt) : [],
        );
        const targetIds = resolveCharacterTargets(document, activeCharacterId, selection.scope);
        for (const characterId of targetIds) {
          document = updateCharacterBlock(document, characterId, 'clothing', (block) =>
            addPresetRefToBlock(
              { ...block, tags: mergeTags(block.tags, additions), source: 'preset_composition' },
              preset.id,
              1,
              selection.scope,
            ),
          );
        }
      }
      for (const selection of composition.body_modifications) {
        const preset = catalog.body_modifications.find((item) => item.id === selection.id);
        if (!preset) continue;
        const additions = mergeTags(
          preset.tags,
          preset.draw_prompt ? tagsOf(preset.draw_prompt) : [],
        );
        const targetIds = resolveCharacterTargets(document, activeCharacterId, selection.scope);
        for (const characterId of targetIds) {
          document = updateCharacterBlock(document, characterId, 'body_modifications', (block) =>
            addPresetRefToBlock(
              { ...block, tags: mergeTags(block.tags, additions), source: 'preset_composition' },
              preset.id,
              1,
              selection.scope,
            ),
          );
        }
      }
      updateGroupDocument(target.id, document);
      message.success(mode === 'replace' ? '已替换当前组结构化组合' : '已追加到当前组结构化组合');
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '组合写入结构化文档失败');
    }
  };

  const applyCharacterAppearance = (apply: {
    scope: 'current' | 'all';
    result: CharacterAppearanceResult;
  }) => {
    const target =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    const result = apply.result;
    const tags = mergeTags(mergeTags(result.appearance, result.clothing), result.expression);
    if (!target) {
      const group = createDrawGroup('', 'group-character-appearance', 'structured');
      drawStore.groups = [group];
      setActiveGroupId(group.id);
    }
    const resolvedTarget =
      drawStore.groups.find((group) => group.id === activeGroupId) || drawStore.groups[0];
    if (!resolvedTarget) return;
    if (resolvedTarget.mode === 'legacy') {
      updateGroupPrompt(
        resolvedTarget.id,
        resolvedTarget.prompt.trim() ? `${resolvedTarget.prompt.trim()}, ${tags.join(', ')}` : tags.join(', '),
      );
    } else {
      updateDocument(resolvedTarget.id, (document) => {
        const targetIds = resolveCharacterTargets(document, activeCharacterId, apply.scope);
        return targetIds.reduce((next, characterId) => {
          if (result.preset_ref) {
            return applyAppearancePresetToCharacter(next, characterId, result);
          }
          let updated = updateCharacterBlock(next, characterId, 'appearance', (block) => ({
            ...block,
            tags: mergeTags(block.tags, result.appearance),
            source: 'appearance_query',
          }));
          updated = updateCharacterBlock(updated, characterId, 'clothing', (block) => ({
            ...block,
            tags: mergeTags(block.tags, result.clothing),
            source: 'appearance_query',
          }));
          updated = updateCharacterBlock(updated, characterId, 'expression', (block) => ({
            ...block,
            tags: mergeTags(block.tags, result.expression),
            source: 'appearance_query',
          }));
          return updated;
        }, document);
      });
    }
    message.success(apply.scope === 'all' ? '已写入全部角色' : '已写入当前角色');
  };

  const poseOrientationOptions = Array.from(
    new Set(posePresets.map((item) => item.orientation || '').filter(Boolean)),
  );
  const posePeopleOptions = Array.from(new Set(posePresets.map((item) => item.people || '').filter(Boolean)));
  const poseVerifiedCount = posePresets.filter(
    (item) => item.accuracy_status === 'verified',
  ).length;
  const poseNeedsReworkCount = posePresets.filter(
    (item) => item.accuracy_status === 'needs_rework',
  ).length;
  const poseDeprecatedCount = posePresets.filter(
    (item) => item.accuracy_status === 'deprecated',
  ).length;
  const keywordLower = poseKeyword.trim().toLowerCase();
  const filteredPosePresets = posePresets.filter((item) => {
    const haystack = `${item.label} ${item.translation || ''} ${item.category} ${presetCategoryGroup(item)} ${presetSubcategory(item)} ${item.tags.join(' ')}`.toLowerCase();
    return (
      (!keywordLower || haystack.includes(keywordLower)) &&
      matchesPresetCategory(item, poseCategoryGroup, poseSubcategory) &&
      (!poseOrientation || item.orientation === poseOrientation) &&
      (!posePeople || item.people === posePeople)
    );
  });

  const poseColumns: ColumnsType<PosePreset> = [
    {
      title: '示例图',
      dataIndex: 'image',
      key: 'image',
      width: 110,
      render: (value: string | null | undefined, record) =>
        value || record.image ? (
          <Image
            src={value || record.image || undefined}
            alt={record.label}
            width={88}
            height={64}
            style={{ objectFit: 'contain', borderRadius: 4, background: '#f8fafc', cursor: 'zoom-in' }}
          />
        ) : (
          <span className="train-status-text">暂无图</span>
        ),
    },
    {
      title: '分类',
      key: 'category',
      width: 180,
      render: (_, record) => (
        <Space size={4} wrap>
          <Tag color="blue">{presetCategoryGroup(record)}</Tag>
          <Tag>{presetSubcategory(record)}</Tag>
          {record.people_count ? <Tag color="gold">{record.people_count} 人</Tag> : null}
        </Space>
      ),
    },
    {
      title: '验收',
      key: 'accuracy',
      width: 110,
      render: (_, record) => {
        const status = record.accuracy_status || 'verified';
        const label =
          status === 'deprecated'
            ? '已弃用'
            : status === 'needs_rework'
              ? '需返工'
              : '已验收';
        return (
          <Tooltip title={record.accuracy_notes || '五项视觉验收通过'}>
            <Tag color={status === 'deprecated' ? 'red' : status === 'needs_rework' ? 'orange' : 'green'}>
              {label}
            </Tag>
          </Tooltip>
        );
      },
    },
    { title: '体位', dataIndex: 'label', key: 'label', width: 110 },
    {
      title: '中文说明',
      dataIndex: 'translation',
      key: 'translation',
      width: 220,
      render: (value: string) => <span style={{ wordBreak: 'break-word' }}>{value || '-'}</span>,
    },
    {
      title: '英文标签',
      key: 'tags',
      render: (_, record) => {
        const corePrompt = posePromptForInsert(record, 'core');
        const fullPrompt = posePromptForInsert(record, 'full');
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
            <Space size={4} wrap>
              {(record.core_tags?.length ? record.core_tags : record.tags).map((tag) => (
                <Tag key={tag} style={{ wordBreak: 'break-word' }}>
                  {tag}
                </Tag>
              ))}
            </Space>
            <Space size={4} wrap>
              <Tooltip title={corePrompt}>
                <Tag color={posePromptDetail === 'core' ? 'blue' : 'default'}>
                  精简 {corePrompt.length} 字符
                </Tag>
              </Tooltip>
              <Tooltip title={fullPrompt}>
                <Tag color={posePromptDetail === 'full' ? 'purple' : 'default'}>
                  完整 {fullPrompt.length} 字符
                </Tag>
              </Tooltip>
            </Space>
          </div>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="按当前提示词详细度插入到当前组">
            <Button
              size="small"
              icon={<InteractionOutlined />}
              onClick={() => insertPoseTags(record, posePromptDetail)}
            >
              插入{posePromptDetail === 'core' ? '精简版' : '完整版'}
            </Button>
          </Tooltip>
          <Tooltip title="管理缩略图">
            <Button
              size="small"
              icon={<PictureOutlined />}
              onClick={() => {
                setPoseOpen(false);
                openPresetAssetWorkshop({
                  presetType: 'pose',
                  presetId: record.id,
                  label: record.label,
                });
              }}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const confirmSaveCombo = () => {
    if (!comboName.trim()) {
      message.warning('请输入搭配名称');
      return;
    }
    saveLoraCombo(comboName.trim(), [...loras], loraStrengths);
    setCommonCombos(loadLoraCombos());
    setComboSaveOpen(false);
    setComboName('');
    message.success(`已保存常用搭配：${comboName.trim()}`);
  };

  const comboMenuItems: MenuProps['items'] = [
    ...(commonCombos.length > 0
      ? commonCombos.map((combo) => ({ key: `combo:${combo.id}`, label: combo.name }))
      : [{ key: 'combo-empty', disabled: true, label: '暂无常用搭配' }]),
    { type: 'divider' },
    { key: 'save-current', label: '保存当前选择', icon: <SaveOutlined /> },
    { key: 'manage-combos', label: '管理常用搭配', icon: <StarOutlined /> },
  ];

  const handleComboMenu: MenuProps['onClick'] = ({ key }) => {
    if (key === 'save-current') {
      if (loras.length === 0) {
        message.warning('请先勾选要保存的 LoRA');
        return;
      }
      setComboSaveOpen(true);
      return;
    }
    if (key === 'manage-combos') {
      setComboManageOpen(true);
      return;
    }
    if (key.startsWith('combo:')) {
      const combo = commonCombos.find((item) => item.id === key.slice('combo:'.length));
      if (!combo) return;
      const available = combo.loras.filter((name) =>
        lorasList.some((item) => item.name === name && item.compatible !== false),
      );
      if (available.length === 0) {
        message.warning('该常用搭配中的 LoRA 已不存在或不可用，请先刷新列表');
        return;
      }
      applyLoraCombo({ ...combo, loras: available });
      message.success(`已应用常用搭配：${combo.name}`);
    }
  };

  const updateLoraStrength = (name: string, key: 'model' | 'clip', value: number) => {
    const current = drawStore.loraStrengths[name] || {
      model: drawConfig.default_lora_strength_model,
      clip: drawConfig.default_lora_strength_clip,
    };
    drawStore.loraStrengths = { ...drawStore.loraStrengths, [name]: { ...current, [key]: value } };
  };

  const handleApplyPreset = (name: string) => {
    if (!applyPreset(name)) {
      message.warning('预设不存在');
      return;
    }
    setPresetSelected(name);
    message.success('已应用预设');
  };

  const drawingLoras = lorasList.filter((item) => item.compatible !== false);

  const handleSavePreset = () => {
    if (!presetName.trim()) {
      message.warning('请输入预设名称');
      return;
    }
    savePreset(presetName.trim());
    setPresets(loadPresets());
    setPresetSelected(presetName.trim());
    setPresetModalOpen(false);
    setPresetName('');
    message.success('已保存预设');
  };

  const handleSaveClothingSet = async () => {
    const prompt = drawStore.groups[0]?.prompt.trim();
    if (!prompt) {
      message.warning('第一组提示词为空');
      return;
    }
    const name = clothingSetName.trim() || `服装集 ${new Date().toLocaleString('zh-CN', { hour12: false })}`;
    setSavingClothingSet(true);
    try {
      await api.post('/prompt-sets', {
        name,
        type: '服装',
        content: prompt,
        translation: '',
        description: '从 AI 绘画第一组保存',
        tags: '',
      });
      setClothingSetOpen(false);
      setClothingSetName('');
      message.success(`已保存服装集：${name}`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || '保存服装集失败');
    } finally {
      setSavingClothingSet(false);
    }
  };

  const handleDeletePreset = () => {
    if (!presetSelected) return;
    deletePreset(presetSelected);
    setPresets(loadPresets());
    setPresetSelected('');
    message.success('已删除预设');
  };

  const handleDeleteCombo = (id: string) => {
    deleteLoraCombo(id);
    setCommonCombos(loadLoraCombos());
    message.success('已删除常用搭配');
  };

  // 加载 LoRA 列表
  useEffect(() => {
    loadLoras();
  }, [lorasVersion]);

  // 加载可选底模
  useEffect(() => {
    api
      .get('/models')
      .then((res) => {
        const list = res.data.models || [];
        setModelsList(list);
        if (list.length > 0 && !list.some((item: ModelItem) => item.name === drawStore.model)) {
          drawStore.model = res.data.default || list[0].name;
        }
      })
      .catch(() => setModelsList([]));
  }, []);

  // 每组提示词逐标签翻译（防抖）
  const groupPromptKey = groups
    .map((group) =>
      group.mode === 'structured'
        ? `${group.id}:${structuredPreviews[group.id]?.prompt || ''}`
        : `${group.id}:${group.prompt}`,
    )
    .join('|');
  useEffect(() => {
    const timer = setTimeout(async () => {
      const map: Record<string, Record<string, string>> = {};
      for (const group of groups) {
        const text =
          group.mode === 'structured'
            ? structuredPreviews[group.id]?.prompt || ''
            : group.prompt;
        map[group.id] = await translateTags(text);
      }
      setGroupTagMaps(map);
    }, 900);
    return () => clearTimeout(timer);
  }, [groupPromptKey]);

  // 负面提示词逐标签翻译（防抖）
  useEffect(() => {
    const timer = setTimeout(async () => setNegTagMap(await translateTags(negativePrompt)), 900);
    return () => clearTimeout(timer);
  }, [negativePrompt]);

  const handleClearPrompts = () => {
    Modal.confirm({
      title: '确认清空所有提示词？',
      content: '将清空全部组的正向提示词与结构化内容，保留组数与绘画参数。',
      onOk: () => {
        drawStore.groups = drawStore.groups.map((group) => {
          if (group.mode === 'legacy') {
            return { ...group, prompt: '', prompt_document: createDrawGroup('', group.id, 'legacy').prompt_document };
          }
          return {
            ...group,
            prompt: '',
            prompt_document: createEmptyStructuredDocument(),
          };
        });
        message.success('已清空提示词');
      },
    });
  };

  const copyCurrentSeed = async () => {
    const seed = results[previewIndex]?.seed;
    if (seed == null) {
      message.warning('当前图片没有 seed');
      return;
    }
    try {
      await navigator.clipboard.writeText(String(seed));
      message.success(`已复制 seed ${seed}`);
    } catch {
      message.error('复制失败');
    }
  };

  const resultFavoriteKey = (result: DrawResult | undefined): string => {
    if (!result) return '';
    return result.record_id
      ? `record:${result.record_id}`
      : `image:${result.image_url}`;
  };

  const toggleResultFavorite = (result: DrawResult | undefined) => {
    const key = resultFavoriteKey(result);
    if (!key) return;
    setFavoriteResults((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key],
    );
  };

  const currentResultPrompt = (result: DrawResult | undefined) => {
    if (!result) return { prompt: '', negativePrompt };
    const submittedGroups = groups.filter((group) =>
      group.mode === 'structured'
        ? !isPromptDocumentEmpty(group.prompt_document)
        : Boolean(group.prompt.trim()),
    );
    const resultGroup =
      submittedGroups[result.group_index ?? -1] ||
      submittedGroups.find((group) => group.id === activeGroupId) ||
      activeGroup;
    const preview = resultGroup ? structuredPreviews[resultGroup.id] : undefined;
    return {
      prompt: preview?.prompt || resultGroup?.prompt || '',
      negativePrompt: preview?.negativePrompt || negativePrompt,
    };
  };

  const copyCurrentPrompt = async () => {
    const text = currentResultPrompt(results[previewIndex]).prompt;
    if (!text.trim()) {
      message.warning('当前结果没有可复制的提示词');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制当前提示词');
    } catch {
      message.error('复制失败');
    }
  };

  const renderBodyProfileControls = (
    group: (typeof groups)[number],
    currentCharacter: PromptDocumentV1['characters'][number] | undefined,
  ) => {
    if (!currentCharacter || currentCharacter.gender !== '女') return null;

    const updateProfile = (
      field: 'height_frame' | 'body_build',
      value: PromptCharacter['height_frame'] | PromptCharacter['body_build'],
    ) => {
      if (group.mode === 'legacy') {
        updateLegacyBodyProfile(group.id, field, value);
        return;
      }
      const baseDocument = normalizePromptDocument(
        group.prompt_document || createEmptyStructuredDocument(),
      );
      updateGroupDocument(
        group.id,
        updateCharacter(baseDocument, currentCharacter.id, (character) => ({
          ...character,
          [field]: value,
        })),
      );
    };

    return (
      <div className="settings-grid" style={{ marginTop: 0 }}>
        <div className="setting-field">
          <span className="setting-label">身高与骨架</span>
          <Select
            value={currentCharacter.height_frame}
            options={HEIGHT_FRAME_OPTIONS.map((option) => ({ ...option }))}
            onChange={(value) => updateProfile('height_frame', value)}
          />
        </div>
        <div className="setting-field">
          <span className="setting-label">体态与体量</span>
          <Select
            value={currentCharacter.body_build}
            options={BODY_BUILD_OPTIONS.map((option) => ({ ...option }))}
            onChange={(value) => updateProfile('body_build', value)}
          />
        </div>
      </div>
    );
  };

  const renderGroupEditor = (group: (typeof groups)[number]) => {
    if (group.mode === 'legacy') {
      const legacyCharacter = createPromptCharacter(0, group.body_profile);
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
          {renderBodyProfileControls(group, legacyCharacter)}
          <Input.TextArea
            rows={4}
            value={group.prompt}
            onChange={(event) => updateGroupPrompt(group.id, event.target.value)}
          />
        </div>
      );
    }
    const document = normalizePromptDocument(group.prompt_document || createEmptyStructuredDocument());
    const characterId = activeCharacterIdForGroup(group);
    const activeCharacter =
      document.characters.find((character) => character.id === characterId) ||
      document.characters[0];
    const preview = structuredPreviews[group.id];
    const editorKey = `${group.id}:advanced`;
    const editorExpanded = expandedStructuredGroups.includes(editorKey);
    const enabledCharacterCount = document.characters.filter(
      (character) => character.enabled !== false,
    ).length;
    const characterTagCount = document.characters.reduce(
      (total, character) =>
        total +
        (
          [
            character.appearance,
            character.clothing,
            character.body_modifications,
            character.pose_or_action,
            character.expression,
            character.state,
          ] as PromptBlock[]
        ).reduce((count, block) => count + block.tags.length, 0),
      0,
    );
    const globalTagCount =
      Object.values(document.global).reduce(
        (total, block) => total + block.tags.length,
        0,
      ) +
      document.interaction.action_tags.length +
      document.interaction.contact_tags.length +
      document.interaction.relationship_tags.length;
    const previewExcerpt = (preview?.prompt || '').trim();
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        <div className="structured-prompt-summary">
          <div className="structured-prompt-summary-copy">
            <strong>结构化提示词</strong>
            <span>
              {enabledCharacterCount} 个启用角色 · 角色标签 {characterTagCount} · 全局/互动标签{' '}
              {globalTagCount}
            </span>
            <Tooltip title={previewExcerpt || '暂无解析结果'}>
              <span className="structured-prompt-summary-preview">
                {previewExcerpt || '暂无解析结果'}
              </span>
            </Tooltip>
          </div>
          <Tag color={preview?.errors.length ? 'red' : preview?.loading ? 'blue' : 'green'}>
            {preview?.errors.length
              ? `${preview.errors.length} 个错误`
              : preview?.loading
                ? '解析中'
                : previewExcerpt
                  ? '已生成预览'
                  : '待填写'}
          </Tag>
        </div>
        <Collapse
          ghost
          className="structured-editor-collapse"
          activeKey={editorExpanded ? ['advanced'] : []}
          onChange={(keys) => {
            const open = Array.isArray(keys) && keys.includes('advanced');
            setExpandedStructuredGroups((current) =>
              open
                ? [...new Set([...current, editorKey])]
                : current.filter((key) => key !== editorKey),
            );
          }}
          items={[
            {
              key: 'advanced',
              label: (
                <div className="structured-editor-trigger">
                  <div>
                    <strong>高级结构化编辑</strong>
                    <span>角色、服装、动作、表情、全局与负向提示词</span>
                  </div>
                  <Tag>{editorExpanded ? '已展开' : '默认收起'}</Tag>
                </div>
              ),
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        <Space wrap>
          <span className="setting-label" style={{ marginBottom: 0 }}>
            当前角色
          </span>
          <Select
            size="small"
            value={activeCharacter?.id}
            style={{ minWidth: 150 }}
            options={document.characters.map((character) => ({
              label: `${character.display_name}${character.enabled === false ? '（禁用）' : ''}`,
              value: character.id,
            }))}
            onChange={(value) =>
              setActiveCharacterIds((current) => ({ ...current, [group.id]: value }))
            }
          />
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              const next = addCharacter(document);
              const added = next.characters[next.characters.length - 1];
              updateGroupDocument(group.id, next);
              setActiveCharacterIds((current) => ({ ...current, [group.id]: added.id }));
            }}
          >
            角色
          </Button>
          <Button
            size="small"
            icon={<CopyOutlined />}
            disabled={!activeCharacter}
            onClick={() => {
              if (!activeCharacter) return;
              const next = duplicateCharacter(document, activeCharacter.id);
              const copied = next.characters.find(
                (character) => character.id !== activeCharacter.id && character.display_name.endsWith('副本'),
              );
              updateGroupDocument(group.id, next);
              if (copied) setActiveCharacterIds((current) => ({ ...current, [group.id]: copied.id }));
            }}
          >
            复制
          </Button>
          <Button
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={!activeCharacter || activeCharacter.order <= 0}
            onClick={() => {
              if (activeCharacter) updateGroupDocument(group.id, moveCharacter(document, activeCharacter.id, -1));
            }}
          />
          <Button
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={!activeCharacter || activeCharacter.order >= document.characters.length - 1}
            onClick={() => {
              if (activeCharacter) updateGroupDocument(group.id, moveCharacter(document, activeCharacter.id, 1));
            }}
          />
          <Button
            size="small"
            danger
            disabled={!activeCharacter || document.characters.length <= 1}
            onClick={() => {
              if (activeCharacter) updateGroupDocument(group.id, removeCharacter(document, activeCharacter.id));
            }}
          >
            删除
          </Button>
        </Space>
        {activeCharacter ? (
          <>
            {renderBodyProfileControls(group, activeCharacter)}
            <div className="settings-grid" style={{ marginTop: 0 }}>
              <div className="setting-field">
                <span className="setting-label">显示名称</span>
                <Input
                  value={activeCharacter.display_name}
                  onChange={(event) =>
                    updateGroupDocument(
                      group.id,
                      updateCharacter(document, activeCharacter.id, (character) => ({
                        ...character,
                        display_name: event.target.value,
                      })),
                    )
                  }
                />
              </div>
              <div className="setting-field">
                <span className="setting-label">角色槽位 / 性别</span>
                <Space.Compact style={{ width: '100%' }}>
                  <Tag color="blue" style={{ marginInlineEnd: 4, lineHeight: '30px' }}>
                    {activeCharacter.role_id}
                  </Tag>
                  <Select
                    style={{ flex: 1 }}
                    value={activeCharacter.gender}
                    options={['女', '男', '其他'].map((value) => ({ label: value, value }))}
                    onChange={(value) =>
                      updateGroupDocument(
                        group.id,
                        updateCharacter(document, activeCharacter.id, (character) => ({
                          ...character,
                          gender: value,
                        })),
                      )
                    }
                  />
                </Space.Compact>
              </div>
              <div className="setting-field">
                <span className="setting-label">启用角色</span>
                <Switch
                  checked={activeCharacter.enabled !== false}
                  onChange={(checked) =>
                    updateGroupDocument(
                      group.id,
                      updateCharacter(document, activeCharacter.id, (character) => ({
                        ...character,
                        enabled: checked,
                      })),
                    )
                  }
                />
              </div>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 8,
              }}
            >
              {(
                [
                  'appearance',
                  'clothing',
                  'body_modifications',
                  'pose_or_action',
                  'expression',
                  'state',
                ] as const
              ).map((kind) => (
                <PromptBlockEditor
                  key={kind}
                  label={CHARACTER_BLOCK_LABELS[kind]}
                  block={activeCharacter[kind]}
                  onChange={(block) =>
                    updateGroupDocument(
                      group.id,
                      updateCharacterBlock(document, activeCharacter.id, kind, () => block),
                    )
                  }
                />
              ))}
            </div>
          </>
        ) : null}
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: 'global',
              label: '全局提示词',
              children: (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: 8,
                  }}
                >
                  {(Object.keys(GLOBAL_BLOCK_LABELS) as Array<keyof typeof GLOBAL_BLOCK_LABELS>).map(
                    (kind) => (
                      <PromptBlockEditor
                        key={kind}
                        label={GLOBAL_BLOCK_LABELS[kind]}
                        block={document.global[kind]}
                        onChange={(block) =>
                          updateGroupDocument(group.id, updateGlobalBlock(document, kind, () => block))
                        }
                      />
                    ),
                  )}
                </div>
              ),
            },
            {
              key: 'interaction',
              label: '互动提示词',
              children: (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: 8,
                  }}
                >
                  {[
                    ['action_tags', '动作'],
                    ['contact_tags', '接触'],
                    ['relationship_tags', '关系'],
                    ['composition_constraints', '构图约束'],
                  ].map(([field, label]) => (
                    <div className="setting-field" key={field}>
                      <span className="setting-label">{label}</span>
                      <Input.TextArea
                        rows={2}
                        value={document.interaction[field as keyof typeof document.interaction] as string[] | undefined
                          ? (
                              document.interaction[
                                field as keyof typeof document.interaction
                              ] as string[]
                            ).join(', ')
                          : ''}
                        onChange={(event) =>
                          updateGroupDocument(
                            group.id,
                            updateInteraction(document, (interaction) => ({
                              ...interaction,
                              [field]: tagsOf(event.target.value),
                            })),
                          )
                        }
                      />
                    </div>
                  ))}
                </div>
              ),
            },
            {
              key: 'custom',
              label: '自定义与备注',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div className="setting-field">
                    <span className="setting-label">自定义全局标签</span>
                    <Input.TextArea
                      rows={2}
                      value={document.custom.global_tags.join(', ')}
                      onChange={(event) =>
                        updateGroupDocument(
                          group.id,
                          updateCustom(document, (custom) => ({
                            ...custom,
                            global_tags: tagsOf(event.target.value),
                          })),
                        )
                      }
                    />
                  </div>
                  <div className="setting-field">
                    <span className="setting-label">用户备注</span>
                    <Input.TextArea
                      rows={2}
                      value={document.custom.user_notes}
                      onChange={(event) =>
                        updateGroupDocument(
                          group.id,
                          updateCustom(document, (custom) => ({
                            ...custom,
                            user_notes: event.target.value,
                          })),
                        )
                      }
                    />
                  </div>
                </div>
              ),
            },
            {
              key: 'negative',
              label: '结构化负向提示词',
              children: (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: 8,
                  }}
                >
                  {(Object.keys(NEGATIVE_BLOCK_LABELS) as Array<keyof typeof NEGATIVE_BLOCK_LABELS>).map(
                    (kind) => (
                      <PromptBlockEditor
                        key={kind}
                        label={NEGATIVE_BLOCK_LABELS[kind]}
                        block={document.negative[kind]}
                        onChange={(block) =>
                          updateGroupDocument(group.id, updateNegativeBlock(document, kind, () => block))
                        }
                      />
                    ),
                  )}
                </div>
              ),
            },
            {
              key: 'raw',
              label: '原文覆盖（结构化解析时忽略）',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Input.TextArea
                    rows={3}
                    value={document.raw_override.prompt}
                    placeholder="保留导入或迁移时的原始正向提示词"
                    onChange={(event) =>
                      updateGroupDocument(
                        group.id,
                        updateRawOverride(document, (raw) => ({
                          ...raw,
                          prompt: event.target.value,
                        })),
                      )
                    }
                  />
                  <Input.TextArea
                    rows={2}
                    value={document.raw_override.negative_prompt}
                    placeholder="保留导入或迁移时的原始负向提示词"
                    onChange={(event) =>
                      updateGroupDocument(
                        group.id,
                        updateRawOverride(document, (raw) => ({
                          ...raw,
                          negative_prompt: event.target.value,
                        })),
                      )
                    }
                  />
                </div>
              ),
            },
          ]}
        />
        <div className="setting-field" style={{ marginBottom: 0 }}>
          <span className="setting-label">后端解析预览</span>
          {preview?.errors.length ? (
            <div style={{ color: '#dc2626', fontSize: 12 }}>{preview.errors.join('；')}</div>
          ) : null}
          {preview?.warnings.length ? (
            <div style={{ color: '#d97706', fontSize: 12 }}>{preview.warnings.join('；')}</div>
          ) : null}
          <Input.TextArea
            rows={3}
            readOnly
            value={preview?.prompt || ''}
            placeholder={preview?.loading === false && !preview.prompt ? '等待填写结构化内容' : '解析中'}
          />
        </div>
                </div>
              ),
            },
          ]}
        />
      </div>
    );
  };

  return (
    <div className="draw-workspace">
      {presetAssetSelection ? (
        <div className="draw-context-bar">
          <div>
            <strong>当前预设：</strong>
            {presetAssetSelection.label || presetAssetSelection.presetId}
            <span className="help">
              {presetAssetSelection.presetType} /{' '}
              {presetAssetSelection.presetId}
            </span>
          </div>
          <Space wrap>
            <Button
              size="small"
              onClick={() =>
                openPresetAssetWorkshop(presetAssetSelection)
              }
            >
              查看候选
            </Button>
            <Button
              size="small"
              icon={<PictureOutlined />}
              onClick={() =>
                openPresetAssetWorkshop(presetAssetSelection)
              }
            >
              管理缩略图
            </Button>
          </Space>
        </div>
      ) : null}
      <div className="draw-grid">
      <div className="controls panel-box">
        <div className="controls-scroll">
        <Button icon={<DatabaseOutlined />} block onClick={() => setPromptSetsOpen(true)} style={{ marginBottom: 8 }}>
          提示词集
        </Button>
        <Button icon={<PictureOutlined />} block onClick={() => setImageLibraryOpen(true)} style={{ marginBottom: 8 }}>
          图片库
        </Button>
        <Button
          icon={<AppstoreOutlined />}
          block
          type="primary"
          onClick={() => setPresetCenterOpen(true)}
          style={{ marginBottom: 8 }}
        >
          预设
        </Button>
        <Button
          icon={<SmileOutlined />}
          block
          onClick={() => setExpressionPresetsOpen(true)}
          style={{ marginBottom: 8 }}
        >
          表情预设
        </Button>
        <Button
          icon={<InteractionOutlined />}
          block
          onClick={openPoseTable}
          style={{ marginBottom: 8 }}
        >
          体位预设
        </Button>
        <Button
          icon={<CloudOutlined />}
          block
          onClick={() => setWaterPresetsOpen(true)}
          style={{ marginBottom: 8 }}
        >
          水中玩法
        </Button>
        <Button block onClick={() => setClothingSetOpen(true)} style={{ marginBottom: 8 }}>
          保存服装集
        </Button>
        <Button icon={<DeleteOutlined />} block onClick={handleClearPrompts} style={{ marginBottom: 8 }}>
          清空提示词
        </Button>
        <Space style={{ width: '100%', marginBottom: 8 }}>
          <Select
            placeholder="应用参数预设"
            style={{ flex: 1 }}
            value={presetSelected || undefined}
            options={presets.map((item) => ({ label: item.name, value: item.name }))}
            onChange={handleApplyPreset}
          />
          <Button size="small" icon={<SaveOutlined />} onClick={() => setPresetModalOpen(true)}>
            保存
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />} disabled={!presetSelected} onClick={handleDeletePreset} />
        </Space>
        <div className="group-list-heading">
          <label>提示词组</label>
          <Space size={4} wrap>
            <Tag color="green">草稿自动保存</Tag>
            <Tooltip title="撤销提示词/参数修改（Ctrl+Z）">
              <Button
                size="small"
                type="text"
                icon={<UndoOutlined />}
                aria-label="撤销提示词修改"
                disabled={!historyStatus.canUndo}
                onClick={undoDrawHistory}
              />
            </Tooltip>
            <Tooltip title="重做（Ctrl+Shift+Z / Ctrl+Y）">
              <Button
                size="small"
                type="text"
                icon={<RedoOutlined />}
                aria-label="重做提示词修改"
                disabled={!historyStatus.canRedo}
                onClick={redoDrawHistory}
              />
            </Tooltip>
            <Button
              size="small"
              type="text"
              icon={<UnorderedListOutlined />}
              onClick={() => setOutlineOpen(true)}
            >
              提示词大纲
            </Button>
          </Space>
        </div>
        <div className="group-list">
          {groups.map((group, index) => {
            const tagMap = groupTagMaps[group.id] || {};
            const expanded = expandedGroupIds.includes(group.id);
            const previewText =
              (group.mode === 'structured'
                ? structuredPreviews[group.id]?.prompt || ''
                : group.prompt
              ).trim();
            const tagCount = tagsOf(previewText).length;
            return (
              <div
                className={`group-card${expanded ? ' expanded' : ''}${
                  activeGroup?.id === group.id ? ' active' : ''
                }${group.enabled === false ? ' disabled' : ''}`}
                key={group.id}
                onDragOver={(event) => {
                  if (!draggedGroupId) return;
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'move';
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  if (draggedGroupId) moveGroupTo(draggedGroupId, group.id);
                  setDraggedGroupId('');
                }}
              >
                <div className="group-header">
                  <div
                    className="group-summary-main"
                    onClick={() => setActiveGroupId(group.id)}
                  >
                    <Tooltip title="拖拽调整提示词组顺序">
                      <span
                        className="group-drag-handle"
                        draggable
                        role="button"
                        tabIndex={0}
                        aria-label={`拖拽第 ${index + 1} 组`}
                        onDragStart={(event) => {
                          setDraggedGroupId(group.id);
                          event.dataTransfer.effectAllowed = 'move';
                          event.dataTransfer.setData('text/plain', group.id);
                        }}
                        onDragEnd={() => setDraggedGroupId('')}
                      >
                        <HolderOutlined />
                      </span>
                    </Tooltip>
                    <strong>第 {index + 1} 组</strong>
                    <Tag color={group.mode === 'structured' ? 'blue' : 'default'}>
                      {group.mode === 'structured' ? '结构化' : '原始文本'}
                    </Tag>
                    <Tag color={group.enabled === false ? 'default' : 'green'}>
                      {group.enabled === false ? '未启用' : '启用'}
                    </Tag>
                    <Tag>{group.count} 张</Tag>
                    <Tag>{tagCount} 个标签</Tag>
                    {loras.length > 0 ? <Tag color="purple">{loras.length} LoRA</Tag> : null}
                  </div>
                  <Space size={4}>
                    <Tooltip title={group.enabled === false ? '启用此提示词组' : '暂停此提示词组'}>
                      <Switch
                        size="small"
                        aria-label={`${group.enabled === false ? '启用' : '停用'}第 ${index + 1} 组`}
                        checked={group.enabled !== false}
                        onChange={(checked) => updateGroupEnabled(group.id, checked)}
                      />
                    </Tooltip>
                    <Button
                      size="small"
                      icon={expanded ? <UpOutlined /> : <DownOutlined />}
                      onClick={() => {
                        setActiveGroupId(group.id);
                        setExpandedGroupIds((current) =>
                          current.includes(group.id)
                            ? current.filter((id) => id !== group.id)
                            : [...current, group.id],
                        );
                      }}
                    >
                      {expanded ? '收起' : '展开'}
                    </Button>
                    <Tooltip title="复制提示词组">
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        aria-label={`复制第 ${index + 1} 组`}
                        onClick={() => {
                          const copy = duplicateGroup(group.id);
                          if (!copy) return;
                          setActiveGroupId(copy.id);
                          setExpandedGroupIds((current) => [...new Set([...current, copy.id])]);
                        }}
                      />
                    </Tooltip>
                    <Button
                      size="small"
                      danger
                      disabled={groups.length <= 1}
                      onClick={() => removeGroup(group.id)}
                    >
                      删除
                    </Button>
                  </Space>
                </div>
                <div className="group-summary-prompt" onClick={() => setActiveGroupId(group.id)}>
                  {previewText || '尚未填写提示词'}
                </div>
                {expanded ? (
                  <>
                    <div className="group-card-controls">
                      <Segmented
                        size="small"
                        value={group.mode}
                        options={[
                          { label: '结构化', value: 'structured' },
                          { label: '原始文本', value: 'legacy' },
                        ]}
                        onChange={(value) =>
                          setGroupMode(group.id, value as 'structured' | 'legacy')
                        }
                      />
                      <span>张数</span>
                      <InputNumber
                        min={drawConfig.group_count_min}
                        max={drawConfig.max_group_count}
                        value={group.count}
                        onChange={(value) =>
                          updateGroupCount(group.id, value ?? drawConfig.group_count_min)
                        }
                      />
                    </div>
                    {renderGroupEditor(group)}
                    <Collapse
                      ghost
                      size="small"
                      items={[
                        {
                          key: 'tags',
                          label: '标签对照',
                          children: (
                            <TagCompareTable
                              rows={tagsOf(previewText).map((tag) => ({
                                tag,
                                translation: tagMap[tag] || '',
                              }))}
                              originalText={previewText}
                            />
                          ),
                        },
                      ]}
                    />
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
        <Button
          block
          onClick={() => {
            const group = addGroup();
            setActiveGroupId(group.id);
          }}
          style={{ marginTop: 8 }}
        >
          添加一组
        </Button>
        {totalRequested > 0 ? (
          <div
            style={{
              marginTop: 6,
              fontSize: 12,
              lineHeight: '18px',
              color: totalRequested >= drawConfig.max_total_count * 0.8 ? '#d97706' : '#6b7280',
            }}
          >
            本批共 {totalRequested} 张（每组最多 {drawConfig.max_group_count} 张，总张数上限{' '}
            {drawConfig.max_total_count} 张）。
            {totalRequested >= drawConfig.max_total_count * 0.6
              ? '张数较多，预计耗时较长，提交前请确认不需要其他改动。'
              : ''}
          </div>
        ) : null}

        <div className="draw-settings-summary">
          <div>
            <strong>生成设置</strong>
            <span>
              {model || '未选模型'} · {width}×{height} · {steps ?? '自动'} 步 · {loras.length} LoRA
            </span>
          </div>
          <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
            打开设置
          </Button>
        </div>
      </div>
      </div>
      <div className="result panel-box">
        <div className="status">{status}</div>
        <Segmented
          size="small"
          value={batchCompare ? 'compare' : 'single'}
          options={[
            { label: '单图预览', value: 'single' },
            { label: '批次对比', value: 'compare' },
          ]}
          onChange={(value) => setBatchCompare(value === 'compare')}
          style={{ marginBottom: 8 }}
        />
        {batchCompare && results.length > 0 ? (
          <div className="batch-compare-grid">
            {results.map((item, index) => (
              <div
                key={`${item.image_url}-${index}`}
                className={`batch-compare-card${index === previewIndex ? ' active' : ''}`}
                onClick={() => {
                  setPreviewIndex(index);
                  setBatchCompare(false);
                }}
              >
                <Image src={item.image_url} alt="" width="100%" style={{ borderRadius: 6 }} preview={false} />
                <div className="batch-compare-meta">
                  <span>第{(item.group_index ?? 0) + 1}组-{(item.image_index ?? 0) + 1}张</span>
                  {item.seed != null ? <span>seed {item.seed}</span> : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="preview-stage">
            {results.length > 0 ? (
              <Button
                className="preview-nav-button"
                icon={<LeftOutlined />}
                disabled={navMode === 'stop' && previewIndex === 0}
                onClick={goPrev}
              />
            ) : null}
            <div className="preview-main">
              {results[previewIndex] ? (
                <Image
                  src={results[previewIndex].image_url}
                  alt={`第${(results[previewIndex].group_index ?? 0) + 1}组-第${(results[previewIndex].image_index ?? 0) + 1}张`}
                  className="preview-image"
                  style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                  preview={{ mask: false }}
                />
              ) : (
                <div className="preview-empty">暂无预览</div>
              )}
            </div>
            {results.length > 0 ? (
              <Button
                className="preview-nav-button"
                icon={<RightOutlined />}
                disabled={navMode === 'stop' && previewIndex === results.length - 1}
                onClick={goNext}
              />
            ) : null}
          </div>
        )}
        {results[previewIndex]?.guard?.retries ? (
          <Tag
            color={results[previewIndex]?.guard?.passed ? 'green' : 'red'}
            style={{ marginTop: 6 }}
          >
            构图守门：重试 {results[previewIndex]?.guard?.retries} 次后
            {results[previewIndex]?.guard?.passed ? '构图通过' : '仍未通过'}
            {results[previewIndex]?.guard?.passed
              ? results[previewIndex]?.review?.ok === false
                ? `；${results[previewIndex]?.review?.message}`
                : ''
              : `：${
                  results[previewIndex]?.review?.message ||
                  results[previewIndex]?.guard?.retry_error ||
                  '检测结果未通过'
                }`}
          </Tag>
        ) : results[previewIndex]?.review?.ok === false ? (
          <Tag color="red" style={{ marginTop: 6 }}>
            视觉复核：{results[previewIndex]?.review?.message}
          </Tag>
        ) : results[previewIndex]?.review?.skipped ? (
          <Tag color="orange" style={{ marginTop: 6 }}>
            视觉复核已跳过：{results[previewIndex]?.review?.message}
          </Tag>
        ) : null}
        {results.length > 0 ? (
          <div className="preview-controls">
            <Segmented
              size="small"
              value={navMode}
              options={[
                { label: '循环', value: 'loop' },
                { label: '首尾停止', value: 'stop' },
              ]}
              onChange={(value) => setNavMode(value as 'loop' | 'stop')}
            />
          </div>
        ) : null}
        {results[previewIndex] ? (
          <div className="result-quick-actions">
            <div>
              <strong>
                第 {(results[previewIndex].group_index ?? 0) + 1} 组 · 第{' '}
                {(results[previewIndex].image_index ?? 0) + 1} 张
              </strong>
              {results[previewIndex].record_id ? (
                <span>已保存到图片库 #{results[previewIndex].record_id}</span>
              ) : null}
            </div>
            <Space wrap size={4}>
              <Button
                size="small"
                icon={
                  favoriteResults.includes(resultFavoriteKey(results[previewIndex])) ? (
                    <StarFilled />
                  ) : (
                    <StarOutlined />
                  )
                }
                onClick={() => toggleResultFavorite(results[previewIndex])}
              >
                {favoriteResults.includes(resultFavoriteKey(results[previewIndex]))
                  ? '取消收藏'
                  : '收藏'}
              </Button>
              <Button size="small" onClick={() => void copyCurrentPrompt()}>
                复制提示词
              </Button>
              <Button
                size="small"
                onClick={() => setBatchCompare((current) => !current)}
              >
                {batchCompare ? '单图预览' : '批次对比'}
              </Button>
              <Button size="small" onClick={() => setImageLibraryOpen(true)}>
                图片库
              </Button>
            </Space>
          </div>
        ) : null}
        {results.length > 1 ? (
          <div className="preview-thumbs" ref={thumbsRef}>
            {results.map((item, index) => (
              <img
                key={index}
                className={`preview-thumb${index === previewIndex ? ' active' : ''}`}
                src={item.image_url}
                alt={`第${(item.group_index ?? 0) + 1}组-第${(item.image_index ?? 0) + 1}张`}
                data-index={index}
                onClick={() => setPreviewIndex(index)}
              />
            ))}
          </div>
        ) : null}
        <div className="result-footer">
          <Space>
            {results[previewIndex]?.seed != null ? (
              <Button icon={<CopyOutlined />} onClick={() => void copyCurrentSeed()}>
                seed {results[previewIndex]?.seed}
              </Button>
            ) : null}
            <Button
              icon={<PictureOutlined />}
              disabled={!results[previewIndex]?.image_url || !results[previewIndex]?.record_id}
              onClick={() => {
                const result = results[previewIndex];
                if (!result?.image_url || !result.record_id) return;
                const submittedGroups = groups.filter((group) =>
                  group.mode === 'structured'
                    ? !isPromptDocumentEmpty(group.prompt_document)
                    : Boolean(group.prompt.trim()),
                );
                const resultGroup =
                  submittedGroups[result.group_index ?? -1] ||
                  submittedGroups.find((group) => group.id === activeGroupId) ||
                  activeGroup;
                const resultDocument =
                  resultGroup?.mode === 'structured' && resultGroup.prompt_document
                    ? withNegativeTags(normalizePromptDocument(resultGroup.prompt_document))
                    : null;
                const resultPreview = resultGroup
                  ? structuredPreviews[resultGroup.id]
                  : undefined;
                onSendToInpaint?.({
                  recordId: result.record_id,
                  imageUrl: result.image_url,
                  width,
                  height,
                  label: `绘画结果 #${result.record_id}`,
                  prompt: resultPreview?.prompt || resultGroup?.prompt || '',
                  negativePrompt: resultPreview?.negativePrompt || negativePrompt,
                  promptDocument: resultDocument,
                });
              }}
            >
              局部重绘
            </Button>
            <Button disabled={results.length === 0} onClick={() => void regenerateCurrent(results[previewIndex]?.seed)}>
              相同 seed 重绘
            </Button>
            <Button disabled={results.length === 0} onClick={() => void regenerateCurrent()}>
              重新生成
            </Button>
            <Button danger icon={<DeleteOutlined />} disabled={results.length === 0} onClick={handleClearResult}>
              清空结果
            </Button>
            <Button onClick={() => window.open(runtimeConfig.services.comfyui.base_url, '_blank')}>
              打开 ComfyUI 面板
            </Button>
          </Space>
        </div>
      </div>
      </div>
      <div className="draw-sticky-actions">
        <div className="draw-sticky-summary">
          <strong>
            {generating ? `生成中 ${done}/${total}` : `${groups.length} 组 · ${totalRequested} 张`}
          </strong>
          <span>{generating ? `${elapsed}s · ${status}` : `${model || '未选模型'} · ${width}×${height}`}</span>
        </div>
        <Space wrap>
          <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
            生成设置
          </Button>
          <Button type="primary" loading={generating} onClick={() => void runDraw()}>
            {generating ? '生成中' : '生成图片'}
          </Button>
          {generating ? (
            <Button danger icon={<StopOutlined />} onClick={() => void stopDraw()}>
              停止
            </Button>
          ) : null}
        </Space>
      </div>
      <Drawer
        title="生成设置"
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        width="min(560px, 96vw)"
        className="draw-settings-drawer"
      >
        <DrawGenerationSettingsPanel
          negativePrompt={negativePrompt}
          negTagMap={negTagMap}
          onNegativePromptChange={(value) => {
            drawStore.negativePrompt = value;
          }}
          model={model}
          models={modelsList}
          onModelChange={(value) => {
            drawStore.model = value;
          }}
          width={width}
          height={height}
          sizeOptions={sizeOptions}
          onSizeChange={(nextWidth, nextHeight) => {
            drawStore.width = nextWidth;
            drawStore.height = nextHeight;
          }}
          steps={steps}
          cfg={cfg}
          limits={{
            stepsMin: drawConfig.steps_min,
            stepsMax: drawConfig.steps_max,
            cfgMin: drawConfig.cfg_min,
            cfgMax: drawConfig.cfg_max,
            cfgStep: drawConfig.cfg_step,
            defaultCfg: drawConfig.default_cfg,
          }}
          onStepsChange={(value) => {
            drawStore.steps = value;
          }}
          onCfgChange={(value) => {
            drawStore.cfg = value;
          }}
          loras={lorasList}
          selectedLoras={loras}
          loraStrengths={loraStrengths}
          loraDefaults={{
            model: drawConfig.default_lora_strength_model,
            clip: drawConfig.default_lora_strength_clip,
            min: drawConfig.lora_strength_min,
            max: drawConfig.lora_strength_max,
            step: drawConfig.lora_strength_step,
          }}
          lorasLoading={lorasLoading}
          comboMenuItems={comboMenuItems}
          onComboMenu={handleComboMenu}
          onLoraToggle={(item, checked) => {
            if (checked && !drawStore.loraStrengths[item.name]) {
              drawStore.loraStrengths = {
                ...drawStore.loraStrengths,
                [item.name]: {
                  model: drawStore.loraStrengthModel,
                  clip: drawStore.loraStrengthClip,
                },
              };
            }
            drawStore.loras = checked
              ? [...loras, item.name]
              : loras.filter((name) => name !== item.name);
          }}
          onLoraRemove={(name) => {
            drawStore.loras = loras.filter((itemName) => itemName !== name);
          }}
          onLoraClear={() => {
            drawStore.loras = [];
          }}
          onLoraStrengthChange={updateLoraStrength}
          onLorasRefresh={loadLoras}
          onLoraDelete={(item) => void handleDeleteLora(item)}
          visualReview={visualReview}
          onVisualReviewChange={(checked) => {
            setVisualReview(checked);
            void api.post('/settings/visual-review', { enabled: checked }).catch(() => undefined);
          }}
          validationText={validationText}
        />
      </Drawer>
      <DrawPromptOutlineDrawer
        open={outlineOpen}
        onClose={() => setOutlineOpen(false)}
        groups={groups}
        previews={structuredPreviews}
        activeGroupId={activeGroupId}
        negativePrompt={negativePrompt}
        onSelectGroup={setActiveGroupId}
      />
      <Modal
        title="体位预设提示词"
        open={poseOpen}
        onCancel={() => setPoseOpen(false)}
        footer={null}
        width={1100}
      >
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 8,
            marginBottom: 10,
            minWidth: 0,
          }}
        >
          <Input.Search
            allowClear
            value={poseKeyword}
            onChange={(e) => setPoseKeyword(e.target.value)}
            placeholder="搜索体位/标签"
            style={{ width: 220 }}
          />
          <Tooltip title="默认只插入核心体位标签和确定性人数前缀；完整模式额外加入 draw_prompt 长句与构图细节。">
            <Segmented
              value={posePromptDetail}
              options={[
                { label: '精简插入', value: 'core' },
                { label: '完整长句', value: 'full' },
              ]}
              onChange={(value) => setPosePromptDetail(value as PosePromptDetail)}
            />
          </Tooltip>
          <PresetCategoryFilter
            items={posePresets}
            categoryGroup={poseCategoryGroup}
            subcategory={poseSubcategory}
            onCategoryGroupChange={(value) => {
              setPoseCategoryGroup(value);
              setPoseSubcategory('');
            }}
            onSubcategoryChange={setPoseSubcategory}
            groupWidth={130}
            subcategoryWidth={130}
          />
          <Select
            allowClear
            placeholder="取向"
            style={{ width: 120 }}
            value={poseOrientation || undefined}
            options={poseOrientationOptions.map((value) => ({ label: value, value }))}
            onChange={(value) => setPoseOrientation(value || '')}
          />
          <Select
            allowClear
            placeholder="人数"
            style={{ width: 120 }}
            value={posePeople || undefined}
            options={posePeopleOptions.map((value) => ({ label: value, value }))}
            onChange={(value) => setPosePeople(value || '')}
          />
          <Tag color="blue">
            当前 {filteredPosePresets.length} / {posePresets.length}
          </Tag>
          <Tag color="green">已验收 {poseVerifiedCount}</Tag>
          <Tag color="orange">需返工 {poseNeedsReworkCount}</Tag>
          {poseDeprecatedCount > 0 ? (
            <Tag color="red">已弃用 {poseDeprecatedCount}</Tag>
          ) : null}
          <Button
            size="small"
            onClick={() => {
              setPoseKeyword('');
              setPoseCategoryGroup('');
              setPoseSubcategory('');
              setPoseOrientation('');
              setPosePeople('');
            }}
            disabled={!poseKeyword && !poseCategoryGroup && !poseSubcategory && !poseOrientation && !posePeople}
          >
            清空筛选
          </Button>
        </div>
        <Table
          rowKey="id"
          columns={poseColumns}
          dataSource={filteredPosePresets}
          loading={poseLoading}
          size="small"
          pagination={false}
          tableLayout="fixed"
          scroll={{ y: 420 }}
        />
      </Modal>
      <PresetCenterDrawer
        open={presetCenterOpen}
        onClose={() => setPresetCenterOpen(false)}
        onApply={applyLibraryItem}
        onAddToComposition={openLibraryComposition}
        onManageThumbnail={(kind, item) => {
          setPresetCenterOpen(false);
          openPresetAssetWorkshop({
            presetType: kind as PresetAssetSelection['presetType'],
            presetId: item.id,
            label: item.label,
          });
        }}
        onOpenComposition={() => {
          setCompositionInitialSelection(null);
          setPresetCenterOpen(false);
          setPresetCompositionOpen(true);
        }}
        onOpenWorkshop={() => {
          setPresetCenterOpen(false);
          openPresetAssetWorkshop();
        }}
        onOpenCharacter={() => {
          setPresetCenterOpen(false);
          setCharacterAppearanceOpen(true);
        }}
      />
      <PromptSetsDrawer
        open={promptSetsOpen}
        onClose={() => setPromptSetsOpen(false)}
        activeGroupId={activeGroupId}
      />
      <ImageLibraryDrawer open={imageLibraryOpen} onClose={() => setImageLibraryOpen(false)} />
      <ClothingPresetsModal
        open={clothingPresetsOpen}
        onClose={() => setClothingPresetsOpen(false)}
        onInsert={insertClothingPreset}
        onManageThumbnail={(selection) => openPresetAssetWorkshop(selection)}
      />
      <ExpressionPresetsModal
        open={expressionPresetsOpen}
        onClose={() => setExpressionPresetsOpen(false)}
        onInsert={insertExpressionPreset}
      />
      <WaterPresetsModal
        open={waterPresetsOpen}
        onClose={() => setWaterPresetsOpen(false)}
        onInsert={insertWaterPreset}
      />
      <ScenePresetsModal
        open={scenePresetsOpen}
        onClose={() => setScenePresetsOpen(false)}
        onInsert={insertScenePreset}
        onManageThumbnail={(selection) => openPresetAssetWorkshop(selection)}
      />
      <PresetCompositionDrawer
        open={presetCompositionOpen}
        onClose={() => setPresetCompositionOpen(false)}
        onApply={applyPresetComposition}
        initialSelection={compositionInitialSelection}
        onManageThumbnail={(selection) => {
          setPresetCompositionOpen(false);
          openPresetAssetWorkshop(selection);
        }}
      />
      <CharacterAppearanceModal
        open={characterAppearanceOpen}
        onClose={() => setCharacterAppearanceOpen(false)}
        onApply={applyCharacterAppearance}
        onManageThumbnail={(selection) => {
          setCharacterAppearanceOpen(false);
          openPresetAssetWorkshop(selection);
        }}
        title="填入角色外貌/默认服装"
      />
      <Modal
        title="保存服装集"
        open={clothingSetOpen}
        onOk={() => void handleSaveClothingSet()}
        onCancel={() => setClothingSetOpen(false)}
        confirmLoading={savingClothingSet}
        okText="保存"
      >
        <Input
          value={clothingSetName}
          onChange={(e) => setClothingSetName(e.target.value)}
          placeholder="例如：白裙 + 过膝袜组合"
          onPressEnter={() => void handleSaveClothingSet()}
        />
      </Modal>
      <Modal
        title="保存参数预设"
        open={presetModalOpen}
        onOk={handleSavePreset}
        onCancel={() => setPresetModalOpen(false)}
      >
        <Input
          value={presetName}
          onChange={(e) => setPresetName(e.target.value)}
          placeholder="例如：推荐搭配 1024"
          onPressEnter={handleSavePreset}
        />
      </Modal>
      <Modal
        title="保存当前选择为常用搭配"
        open={comboSaveOpen}
        onOk={confirmSaveCombo}
        onCancel={() => setComboSaveOpen(false)}
        okText="保存"
      >
        <Input
          value={comboName}
          onChange={(e) => setComboName(e.target.value)}
          placeholder="例如：常用角色画风 + anima-turbo"
          onPressEnter={confirmSaveCombo}
        />
      </Modal>
      <Modal
        title="管理常用搭配"
        open={comboManageOpen}
        onCancel={() => setComboManageOpen(false)}
        footer={null}
      >
        {commonCombos.length === 0 ? (
          <div className="train-status-text">暂无常用搭配</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {commonCombos.map((combo) => (
              <div
                key={combo.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  border: '1px solid #e5e7eb',
                  borderRadius: 6,
                  padding: '6px 8px',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ wordBreak: 'break-word', minWidth: 0, flex: 1 }}>
                  <b>{combo.name}</b>（{combo.loras.length} 个）
                </span>
                <Space>
                  <Button
                    size="small"
                    onClick={() => {
                      const available = combo.loras.filter((name) =>
                        drawingLoras.some((item) => item.name === name),
                      );
                      if (available.length === 0) {
                        message.warning('该搭配中的 LoRA 已不可用');
                        return;
                      }
                      applyLoraCombo({ ...combo, loras: available });
                      message.success(`已应用常用搭配：${combo.name}`);
                    }}
                  >
                    应用
                  </Button>
                  <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteCombo(combo.id)}>
                    删除
                  </Button>
                </Space>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
