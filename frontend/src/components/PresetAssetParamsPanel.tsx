import {
  DeleteOutlined,
  ReloadOutlined,
  SaveOutlined,
  ScissorOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Collapse,
  Image,
  Input,
  InputNumber,
  message,
  Popconfirm,
  Segmented,
  Select,
  Slider,
  Space,
  Tag,
  Upload,
} from 'antd';
import { useEffect, useState } from 'react';
import { api } from '../api';
import type {
  LoraItem,
  PresetAssetKind,
  PresetAssetSettings,
} from '../api';
import {
  apiErrorMessage,
  createPresetAssetAi,
  createPresetAssetCrop,
  importPresetAsset,
  presetAssetStore,
  savePresetAssetDefaults,
} from '../stores/presetAssetStore';
import {
  clearPresetAssetSettingsDraft,
  deletePresetAssetSettingsScheme,
  loadPresetAssetSettingsDraft,
  loadPresetAssetSettingsSchemes,
  mergePresetAssetSettingsWithDefaults,
  savePresetAssetSettingsDraft,
  savePresetAssetSettingsScheme,
  type PresetAssetSettingsScheme,
} from '../presetAssetSettingsPersistence';
import {
  firstPresetAssetSettingsError,
  type PresetAssetSettingsErrors,
  type PresetAssetSettingsField,
  validatePresetAssetSettings,
} from '../presetAssetSettingsValidation';

type SettingsOrigin = 'backend' | 'draft' | 'scheme';
type LoraStrengthKind = 'model' | 'clip';

function cloneSettings(settings: PresetAssetSettings): PresetAssetSettings {
  return {
    ...settings,
    loras: [...settings.loras],
    lora_strengths: Object.fromEntries(
      Object.entries(settings.lora_strengths).map(([name, values]) => [
        name,
        { ...values },
      ]),
    ),
  };
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取图片失败'));
    reader.readAsDataURL(file);
  });
}

function originLabel(origin: SettingsOrigin): string {
  if (origin === 'draft') return '浏览器草稿';
  if (origin === 'scheme') return '命名方案';
  return '后端默认值';
}

export default function PresetAssetParamsPanel({
  presetType: explicitPresetType,
  batchMode = false,
}: {
  presetType?: PresetAssetKind;
  batchMode?: boolean;
}) {
  const { detail, settings: settingsPayload, submitting } = presetAssetStore;
  const [values, setValues] = useState<PresetAssetSettings | null>(null);
  const [errors, setErrors] = useState<PresetAssetSettingsErrors>({});
  const [loras, setLoras] = useState<LoraItem[]>([]);
  const [lorasLoading, setLorasLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [origin, setOrigin] = useState<SettingsOrigin>('backend');
  const [schemes, setSchemes] = useState<PresetAssetSettingsScheme[]>([]);
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>();
  const [schemeName, setSchemeName] = useState('');

  const presetType = explicitPresetType || detail?.summary.preset_type;

  useEffect(() => {
    setLorasLoading(true);
    api
      .get<{ loras: LoraItem[] }>('/loras')
      .then((res) => {
        setLoras((res.data.loras || []).filter((item) => item.compatible !== false));
      })
      .catch(() => setLoras([]))
      .finally(() => setLorasLoading(false));
  }, []);

  useEffect(() => {
    if (!settingsPayload || !presetType) return;
    const draft = loadPresetAssetSettingsDraft(presetType);
    setValues(
      draft
        ? mergePresetAssetSettingsWithDefaults(settingsPayload.defaults, draft)
        : cloneSettings(settingsPayload.defaults),
    );
    setOrigin(draft ? 'draft' : 'backend');
    setSchemes(loadPresetAssetSettingsSchemes(presetType));
    setSelectedSchemeId(undefined);
    setSchemeName('');
    setErrors({});
  }, [presetType, settingsPayload]);

  if (
    !values ||
    !settingsPayload ||
    !presetType ||
    (!batchMode && !detail)
  ) {
    return (
      <Alert
        type="info"
        showIcon
        message={batchMode ? '批量参数正在加载' : '选择预设后可编辑生成参数'}
      />
    );
  }

  const limits = settingsPayload.limits;
  const target = settingsPayload.targets[presetType];
  const source = detail?.summary.source;
  const selectedScheme = schemes.find((item) => item.id === selectedSchemeId);

  const persistDraft = (next: PresetAssetSettings) => {
    savePresetAssetSettingsDraft(next, presetType);
  };

  const update = <K extends keyof PresetAssetSettings>(
    key: K,
    value: PresetAssetSettings[K],
    field?: PresetAssetSettingsField,
  ) => {
    setValues((current) => {
      if (!current) return current;
      const next = { ...current, [key]: value };
      persistDraft(next);
      return next;
    });
    setOrigin('draft');
    const errorField = field || (key as PresetAssetSettingsField);
    if (errors[errorField]) {
      setErrors((current) => ({ ...current, [errorField]: undefined }));
    }
  };

  const run = async (action: () => Promise<unknown>, success: string) => {
    setWorking(true);
    try {
      await action();
      message.success(success);
    } catch (error) {
      message.error(apiErrorMessage(error, '操作失败'));
    } finally {
      setWorking(false);
    }
  };

  const validate = (
    requireModel = true,
    requireTarget = true,
  ): PresetAssetSettings | null => {
    const nextErrors = validatePresetAssetSettings(
      values,
      limits,
      target,
      { requireModel, requireTarget },
    );
    setErrors(nextErrors);
    const firstError = firstPresetAssetSettingsError(nextErrors);
    if (firstError) {
      message.error(firstError);
      return null;
    }
    return cloneSettings(values);
  };

  const importFile = async (file: File) => {
    if (file.size > limits.upload_max_bytes) {
      message.error('图片超过上传大小限制');
      return false;
    }
    await run(
      async () => {
        const dataUrl = await fileToDataUrl(file);
        await importPresetAsset(dataUrl, file.type);
      },
      '源图已导入',
    );
    return false;
  };

  const updateLoraStrength = (
    name: string,
    kind: LoraStrengthKind,
    value: number | null,
  ) => {
    setValues((current) => {
      if (!current) return current;
      const currentStrength = { ...(current.lora_strengths[name] || {}) };
      if (value == null || !Number.isFinite(value)) {
        delete currentStrength[kind];
      } else {
        currentStrength[kind] = value;
      }
      const nextStrengths = { ...current.lora_strengths };
      if (Object.keys(currentStrength).length > 0) {
        nextStrengths[name] = currentStrength;
      } else {
        delete nextStrengths[name];
      }
      const next = {
        ...current,
        loras: [...current.loras],
        lora_strengths: nextStrengths,
      };
      persistDraft(next);
      return next;
    });
    setOrigin('draft');
    setErrors((current) => ({ ...current, lora_strengths: undefined }));
  };

  const updateLoras = (nextLoras: string[]) => {
    const selected = [...new Set(nextLoras.map((item) => item.trim()).filter(Boolean))];
    const selectedSet = new Set(selected);
    const nextStrengths = Object.fromEntries(
      Object.entries(values.lora_strengths).filter(([name]) =>
        selectedSet.has(name),
      ),
    );
    const next = {
      ...values,
      loras: selected,
      lora_strengths: nextStrengths,
    };
    setValues(next);
    persistDraft(next);
    setOrigin('draft');
  };

  const saveScheme = () => {
    const name = schemeName.trim();
    if (!name) {
      message.error('请输入参数方案名称');
      return;
    }
    const scheme = savePresetAssetSettingsScheme(presetType, name, values);
    if (!scheme) {
      message.error('参数方案保存失败');
      return;
    }
    setSchemes(loadPresetAssetSettingsSchemes(presetType));
    setSelectedSchemeId(scheme.id);
    setSchemeName('');
    message.success('参数方案已保存');
  };

  const applyScheme = () => {
    if (!selectedScheme) {
      message.error('请先选择参数方案');
      return;
    }
    const next = mergePresetAssetSettingsWithDefaults(
      settingsPayload.defaults,
      selectedScheme.settings,
    );
    setValues(next);
    persistDraft(next);
    setOrigin('scheme');
    setErrors({});
    message.success('参数方案已应用');
  };

  const deleteScheme = () => {
    if (!selectedScheme) return;
    deletePresetAssetSettingsScheme(selectedScheme.id);
    setSchemes(loadPresetAssetSettingsSchemes(presetType));
    setSelectedSchemeId(undefined);
    message.success('参数方案已删除');
  };

  const restoreBackendDefaults = () => {
    const next = cloneSettings(settingsPayload.defaults);
    setValues(next);
    persistDraft(next);
    setOrigin('draft');
    setSelectedSchemeId(undefined);
    setErrors({});
    message.success('已恢复后端默认值并保存为当前类型草稿');
  };

  const clearLocalDraft = () => {
    clearPresetAssetSettingsDraft(presetType);
    setValues(cloneSettings(settingsPayload.defaults));
    setOrigin('backend');
    setSelectedSchemeId(undefined);
    setErrors({});
    message.success('本地草稿已清除');
  };

  const fieldError = (field: PresetAssetSettingsField) =>
    errors[field] ? (
      <span className="preset-asset-field-error" role="alert">
        {errors[field]}
      </span>
    ) : null;

  const cropPayload = {
    mode: values.crop_mode,
    focus_x: values.focus_x,
    focus_y: values.focus_y,
    zoom: values.zoom,
  };

  return (
    <div className="preset-asset-params">
      {batchMode ? (
        <div className="preset-asset-params-summary">
          <div className="train-section-title">批量生成参数</div>
          <Space size={4} wrap>
            {target ? (
              <Tag color={errors.target ? 'red' : 'blue'}>
                {target.output_size[0]}×{target.output_size[1]} {target.format}
              </Tag>
            ) : null}
          </Space>
          {fieldError('target')}
        </div>
      ) : (
        <div className="preset-asset-current-image">
          {detail?.summary.image ? (
            <Image
              src={detail.summary.image}
              alt={detail.summary.label}
              width={108}
              height={presetType === 'scene' ? 61 : 162}
              style={{ objectFit: 'contain', borderRadius: 4, background: '#f8fafc' }}
            />
          ) : (
            <div className="preset-asset-empty-image">暂无正式图</div>
          )}
          <div>
            <div className="train-section-title">{detail?.summary.label}</div>
            <Space size={4} wrap>
              <Tag>{detail?.summary.preset_id}</Tag>
              {detail?.summary.rating === 'R18' ? <Tag color="red">R18</Tag> : null}
              {target ? (
                <Tag color={errors.target ? 'red' : 'blue'}>
                  {target.output_size[0]}×{target.output_size[1]} {target.format}
                </Tag>
              ) : null}
            </Space>
            <div className="help">
              源图 {source ? `${source.width}×${source.height} / 版本 ${source.revision}` : '未导入'}
            </div>
            {fieldError('target')}
          </div>
        </div>
      )}

      <Alert
        type="info"
        showIcon
        message={`当前参数来源：${originLabel(origin)}`}
        description={
          batchMode
            ? '批量任务统一使用当前类型草稿，草稿只保存在当前浏览器。'
            : '浏览器草稿和命名方案只保存在当前浏览器，不会改写后端默认值。'
        }
      />

      <div className="preset-asset-toolbar">
        {!batchMode ? (
          <>
            <Upload
              accept="image/png,image/jpeg,image/webp"
              showUploadList={false}
              beforeUpload={(file) => void importFile(file)}
            >
              <Button icon={<UploadOutlined />} loading={submitting || working}>
                导入源图
              </Button>
            </Upload>
            <Button
              icon={<ScissorOutlined />}
              disabled={!source}
              loading={working}
              onClick={() => {
                const validated = validate(false, false);
                if (validated) {
                  void run(() => createPresetAssetCrop(cropPayload), 'CPU 候选已生成');
                }
              }}
            >
              CPU 裁剪候选
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={working}
              onClick={() => {
                const validated = validate(true, true);
                if (validated) {
                  void run(() => createPresetAssetAi(validated), 'AI 候选任务已进入队列');
                }
              }}
            >
              AI 生成候选
            </Button>
          </>
        ) : null}
        <Button
          icon={<SaveOutlined />}
          loading={working}
          onClick={() => {
            const validated = validate(true, true);
            if (!validated) return;
            persistDraft(validated);
            void run(
              () => savePresetAssetDefaults(validated),
              '默认参数已保存到后端',
            );
          }}
        >
          保存为后端默认
        </Button>
        <Button icon={<ReloadOutlined />} onClick={restoreBackendDefaults}>
          恢复后端默认值
        </Button>
        <Button danger onClick={clearLocalDraft}>
          清除本地草稿
        </Button>
      </div>

      <Collapse
        size="small"
        defaultActiveKey={['scheme', 'crop']}
        items={[
          {
            key: 'scheme',
            label: '参数来源与方案',
            children: (
              <div className="preset-asset-scheme-editor">
                <div className="preset-asset-scheme-row">
                  <Select
                    allowClear
                    value={selectedSchemeId}
                    placeholder="选择命名方案"
                    options={schemes.map((scheme) => ({
                      label: scheme.name,
                      value: scheme.id,
                    }))}
                    onChange={setSelectedSchemeId}
                  />
                  <Button onClick={applyScheme} disabled={!selectedScheme}>
                    应用方案
                  </Button>
                  <Popconfirm
                    title="删除这个参数方案？"
                    description="已应用的当前参数不会被清空。"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={deleteScheme}
                    disabled={!selectedScheme}
                  >
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!selectedScheme}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </div>
                <div className="preset-asset-scheme-row">
                  <Input
                    value={schemeName}
                    maxLength={40}
                    placeholder="保存当前参数为方案"
                    onChange={(event) => setSchemeName(event.target.value)}
                    onPressEnter={saveScheme}
                  />
                  <Button type="primary" onClick={saveScheme}>
                    保存方案
                  </Button>
                </div>
              </div>
            ),
          },
          {
            key: 'crop',
            label: '裁剪与候选',
            children: (
              <div className="preset-asset-form-grid">
                <label>
                  裁剪模式
                  <Segmented
                    block
                    value={values.crop_mode}
                    options={[
                      { label: '覆盖', value: 'cover' },
                      { label: '完整', value: 'contain' },
                    ]}
                    onChange={(value) =>
                      update('crop_mode', value as PresetAssetSettings['crop_mode'])
                    }
                  />
                </label>
                <label>
                  候选数量
                  <InputNumber
                    aria-label="候选数量"
                    min={limits.candidate_min}
                    max={limits.candidate_max}
                    value={values.candidate_count}
                    status={errors.candidate_count ? 'error' : undefined}
                    onChange={(value) =>
                      update(
                        'candidate_count',
                        value == null ? Number.NaN : Number(value),
                        'candidate_count',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('candidate_count')}
                </label>
                <label>
                  横向焦点
                  <Slider
                    min={limits.focus_min}
                    max={limits.focus_max}
                    step={limits.focus_step}
                    value={values.focus_x}
                    onChange={(value) => update('focus_x', value)}
                  />
                  {fieldError('focus_x')}
                </label>
                <label>
                  纵向焦点
                  <Slider
                    min={limits.focus_min}
                    max={limits.focus_max}
                    step={limits.focus_step}
                    value={values.focus_y}
                    onChange={(value) => update('focus_y', value)}
                  />
                  {fieldError('focus_y')}
                </label>
                <label>
                  缩放
                  <Slider
                    min={limits.zoom_min}
                    max={limits.zoom_max}
                    step={limits.zoom_step}
                    value={values.zoom}
                    onChange={(value) => update('zoom', value)}
                  />
                  {fieldError('zoom')}
                </label>
              </div>
            ),
          },
          {
            key: 'sampling',
            label: '模型与采样',
            children: (
              <div className="preset-asset-form-grid">
                <label className="preset-asset-field-wide">
                  模型
                  <Input
                    aria-label="模型"
                    value={values.model}
                    status={errors.model ? 'error' : undefined}
                    onChange={(event) => update('model', event.target.value)}
                  />
                  {fieldError('model')}
                </label>
                <label className="preset-asset-field-wide">
                  LoRA
                  <Select
                    mode="tags"
                    loading={lorasLoading}
                    options={loras.map((item) => ({
                      label: item.name,
                      value: item.name,
                    }))}
                    value={values.loras}
                    onChange={updateLoras}
                    placeholder="选择或输入 LoRA 名称"
                    tokenSeparators={[',']}
                  />
                  {fieldError('lora_strengths')}
                </label>
                <label>
                  默认模型强度
                  <InputNumber
                    aria-label="默认模型强度"
                    min={limits.lora_strength_min}
                    max={limits.lora_strength_max}
                    step={limits.lora_strength_step}
                    value={values.lora_strength_model}
                    status={errors.lora_strength_model ? 'error' : undefined}
                    onChange={(value) =>
                      update(
                        'lora_strength_model',
                        value == null ? Number.NaN : Number(value),
                        'lora_strength_model',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('lora_strength_model')}
                </label>
                <label>
                  默认 CLIP 强度
                  <InputNumber
                    aria-label="默认 CLIP 强度"
                    min={limits.lora_strength_min}
                    max={limits.lora_strength_max}
                    step={limits.lora_strength_step}
                    value={values.lora_strength_clip}
                    status={errors.lora_strength_clip ? 'error' : undefined}
                    onChange={(value) =>
                      update(
                        'lora_strength_clip',
                        value == null ? Number.NaN : Number(value),
                        'lora_strength_clip',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('lora_strength_clip')}
                </label>
                {values.loras.length > 0 ? (
                  <div className="preset-asset-lora-strengths preset-asset-field-wide">
                    <div className="train-section-title">已选 LoRA 独立强度</div>
                    {values.loras.map((name) => {
                      const strength = values.lora_strengths[name] || {};
                      return (
                        <div className="preset-asset-lora-strength-row" key={name}>
                          <div className="preset-asset-lora-name" title={name}>
                            {name}
                            {!strength.model && !strength.clip ? (
                              <Tag>使用默认</Tag>
                            ) : null}
                          </div>
                          <InputNumber
                            aria-label={`${name} 模型强度`}
                            min={limits.lora_strength_min}
                            max={limits.lora_strength_max}
                            step={limits.lora_strength_step}
                            value={strength.model ?? values.lora_strength_model}
                            onChange={(value) =>
                              updateLoraStrength(
                                name,
                                'model',
                                value == null ? null : Number(value),
                              )
                            }
                          />
                          <InputNumber
                            aria-label={`${name} CLIP 强度`}
                            min={limits.lora_strength_min}
                            max={limits.lora_strength_max}
                            step={limits.lora_strength_step}
                            value={strength.clip ?? values.lora_strength_clip}
                            onChange={(value) =>
                              updateLoraStrength(
                                name,
                                'clip',
                                value == null ? null : Number(value),
                              )
                            }
                          />
                          <Button
                            size="small"
                            onClick={() => {
                              updateLoraStrength(name, 'model', null);
                              updateLoraStrength(name, 'clip', null);
                            }}
                          >
                            使用默认
                          </Button>
                        </div>
                      );
                    })}
                    {fieldError('lora_strengths')}
                  </div>
                ) : null}
                <label>
                  步数
                  <InputNumber
                    aria-label="步数"
                    min={limits.steps_min}
                    max={limits.steps_max}
                    value={values.steps}
                    status={errors.steps ? 'error' : undefined}
                    onChange={(value) =>
                      update(
                        'steps',
                        value == null ? Number.NaN : Number(value),
                        'steps',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('steps')}
                </label>
                <label>
                  CFG
                  <InputNumber
                    aria-label="CFG"
                    min={limits.cfg_min}
                    max={limits.cfg_max}
                    step={limits.cfg_step}
                    value={values.cfg}
                    status={errors.cfg ? 'error' : undefined}
                    onChange={(value) =>
                      update(
                        'cfg',
                        value == null ? Number.NaN : Number(value),
                        'cfg',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('cfg')}
                </label>
                <label>
                  Seed 策略
                  <Select
                    value={values.seed_strategy}
                    onChange={(value) => update('seed_strategy', value)}
                    options={[
                      { label: '随机', value: 'random' },
                      { label: '固定', value: 'fixed' },
                      { label: '递增', value: 'derive' },
                    ]}
                  />
                </label>
                <label>
                  Seed
                  <InputNumber
                    aria-label="Seed"
                    min={limits.seed_min}
                    max={limits.seed_max}
                    value={values.seed ?? undefined}
                    status={errors.seed ? 'error' : undefined}
                    disabled={values.seed_strategy === 'random'}
                    onChange={(value) =>
                      update(
                        'seed',
                        value == null ? null : Number(value),
                        'seed',
                      )
                    }
                    style={{ width: '100%' }}
                  />
                  {fieldError('seed')}
                </label>
              </div>
            ),
          },
          {
            key: 'prompt',
            label: '提示词',
            children: (
              <div className="preset-asset-prompt-grid">
                <label>
                  风格正向
                  <Input.TextArea
                    rows={3}
                    value={values.style_positive}
                    onChange={(event) => update('style_positive', event.target.value)}
                  />
                </label>
                <label>
                  用户正向
                  <Input.TextArea
                    rows={3}
                    value={values.user_positive}
                    onChange={(event) => update('user_positive', event.target.value)}
                  />
                </label>
                <label>
                  风格负向
                  <Input.TextArea
                    rows={3}
                    value={values.style_negative}
                    onChange={(event) => update('style_negative', event.target.value)}
                  />
                </label>
                <label>
                  用户负向
                  <Input.TextArea
                    rows={3}
                    value={values.user_negative}
                    onChange={(event) => update('user_negative', event.target.value)}
                  />
                </label>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
