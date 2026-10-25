import { InfoCircleOutlined } from '@ant-design/icons';
import {
  Collapse,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tooltip,
} from 'antd';
import type { MenuProps } from 'antd';
import type { LoraItem, ModelItem } from '../api';
import DrawLoraSelector from './DrawLoraSelector';
import TagCompareTable from './TagCompareTable';

interface DrawGenerationSettingsPanelProps {
  negativePrompt: string;
  negTagMap: Record<string, string>;
  onNegativePromptChange: (value: string) => void;
  model: string;
  models: ModelItem[];
  onModelChange: (value: string) => void;
  width: number;
  height: number;
  sizeOptions: { label: string; value: string }[];
  onSizeChange: (width: number, height: number) => void;
  steps: number | null;
  cfg: number;
  limits: {
    stepsMin: number;
    stepsMax: number;
    cfgMin: number;
    cfgMax: number;
    cfgStep: number;
    defaultCfg: number;
  };
  onStepsChange: (value: number | null) => void;
  onCfgChange: (value: number) => void;
  loras: LoraItem[];
  selectedLoras: string[];
  loraStrengths: Record<string, { model: number; clip: number }>;
  loraDefaults: {
    model: number;
    clip: number;
    min: number;
    max: number;
    step: number;
  };
  lorasLoading: boolean;
  comboMenuItems: MenuProps['items'];
  onComboMenu: MenuProps['onClick'];
  onLoraToggle: (item: LoraItem, checked: boolean) => void;
  onLoraRemove: (name: string) => void;
  onLoraClear: () => void;
  onLoraStrengthChange: (name: string, key: 'model' | 'clip', value: number) => void;
  onLorasRefresh: () => void;
  onLoraDelete: (item: LoraItem) => void;
  visualReview: boolean;
  onVisualReviewChange: (checked: boolean) => void;
  validationText: string;
}

export default function DrawGenerationSettingsPanel({
  negativePrompt,
  negTagMap,
  onNegativePromptChange,
  model,
  models,
  onModelChange,
  width,
  height,
  sizeOptions,
  onSizeChange,
  steps,
  cfg,
  limits,
  onStepsChange,
  onCfgChange,
  loras,
  selectedLoras,
  loraStrengths,
  loraDefaults,
  lorasLoading,
  comboMenuItems,
  onComboMenu,
  onLoraToggle,
  onLoraRemove,
  onLoraClear,
  onLoraStrengthChange,
  onLorasRefresh,
  onLoraDelete,
  visualReview,
  onVisualReviewChange,
  validationText,
}: DrawGenerationSettingsPanelProps) {
  return (
    <div className="draw-generation-settings">
      <section className="draw-settings-section">
        <div className="train-section-title">基础参数</div>
        <div className="settings-grid">
          <div className="setting-field setting-wide">
            <Tooltip title="绘画底模；Anima 系模型均可出图，建议与训练底模保持一致。">
              <span className="setting-label">模型</span>
            </Tooltip>
            <Select
              style={{ width: '100%' }}
              value={model}
              options={models.map((item) => ({
                label: `${item.name} (${item.size_mb}MB)`,
                value: item.name,
              }))}
              onChange={onModelChange}
            />
          </div>
          <div className="setting-field setting-wide">
            <Tooltip title="生成图片的宽高，竖版适合人物立绘，横版适合场景">
              <span className="setting-label">尺寸</span>
            </Tooltip>
            <Select
              style={{ width: '100%' }}
              value={`${width}x${height}`}
              options={sizeOptions}
              onChange={(value) => {
                const [nextWidth, nextHeight] = value.split('x').map(Number);
                onSizeChange(nextWidth, nextHeight);
              }}
            />
          </div>
          <div className="setting-field">
            <span className="setting-label">步数</span>
            <InputNumber
              min={limits.stepsMin}
              max={limits.stepsMax}
              value={steps ?? null}
              onChange={onStepsChange}
              placeholder={`${limits.stepsMin}-${limits.stepsMax}`}
              style={{ width: '100%' }}
            />
          </div>
          <div className="setting-field">
            <span className="setting-label">CFG</span>
            <InputNumber
              min={limits.cfgMin}
              max={limits.cfgMax}
              step={limits.cfgStep}
              value={cfg}
              onChange={(value) => onCfgChange(value ?? limits.defaultCfg)}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </section>

      <section className="draw-settings-section">
        <div className="train-section-title">负面提示词</div>
        <Input.TextArea
          value={negativePrompt}
          onChange={(event) => onNegativePromptChange(event.target.value)}
          rows={4}
        />
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: 'neg-tags',
              label: '标签对照',
              children: (
                <TagCompareTable
                  rows={negativePrompt
                    .split(',')
                    .map((tag) => tag.trim())
                    .filter(Boolean)
                    .map((tag) => ({ tag, translation: negTagMap[tag] || '' }))}
                  originalText={negativePrompt}
                />
              ),
            },
          ]}
        />
      </section>

      <section className="draw-settings-section">
        <DrawLoraSelector
          items={loras}
          selected={selectedLoras}
          strengths={loraStrengths}
          defaults={loraDefaults}
          loading={lorasLoading}
          comboMenuItems={comboMenuItems}
          onComboMenu={onComboMenu}
          onToggle={onLoraToggle}
          onRemove={onLoraRemove}
          onClear={onLoraClear}
          onStrengthChange={onLoraStrengthChange}
          onRefresh={onLorasRefresh}
          onDelete={onLoraDelete}
        />
      </section>

      <section className="draw-settings-section draw-settings-review">
        <div>
          <span className="setting-label">视觉复核</span>
          <div className="help">
            <InfoCircleOutlined /> 多人画面会复核人数与身体关系；其他 GPU 任务运行时自动跳过。
          </div>
        </div>
        <Switch checked={visualReview} onChange={onVisualReviewChange} />
      </section>

      {validationText ? (
        <div
          className="draw-validation-line"
          data-tone={validationText === '校验通过' ? 'ok' : 'warning'}
        >
          {validationText}
        </div>
      ) : null}
    </div>
  );
}
