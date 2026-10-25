import {
  ArrowDownOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Input,
  Popover,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { api } from '../api';
import {
  createEmptyStructuredDocument,
  createPromptCharacter,
  normalizePromptDocument,
  updateCharacter,
  updateInteraction,
} from '../promptDocument';
import { drawStore, updateGroupDocument } from '../stores/draw';

type RoleSlot = 'A' | 'B';
type Gender = 'female' | 'male';
type ComposerMode = 'simple' | 'advanced';

interface CatalogOption {
  id: string;
  label: string;
  tag: string;
  owner_gender?: Gender | null;
}

interface ActionCatalog {
  base_states: CatalogOption[];
  pelvis_states: CatalogOption[];
  near_leg_states: CatalogOption[];
  far_leg_states: CatalogOption[];
  arm_states: CatalogOption[];
  head_states: CatalogOption[];
  expressions: CatalogOption[];
  gazes: CatalogOption[];
  source_parts: CatalogOption[];
  actions: CatalogOption[];
  target_parts: CatalogOption[];
  primary_actions: CatalogOption[];
  phases: CatalogOption[];
  direction_profiles: CatalogOption[];
}

interface RoleRecipe {
  slot: RoleSlot;
  gender: Gender;
  base: string;
  pelvis: string;
  near_leg: string;
  far_leg: string;
  arms: string;
  head: string;
  expression: string;
  gaze: string;
}

interface InteractionRecipe {
  id: string;
  source_role: RoleSlot;
  source_part: string;
  action: string;
  target_role: RoleSlot;
  target_part: string;
}

interface ActionRecipe {
  name: string;
  direction_profile: string;
  dominant_role: RoleSlot;
  receiving_role: RoleSlot;
  roles: RoleRecipe[];
  interactions: InteractionRecipe[];
  primary_action: string;
  phase: string;
}

interface CompileResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  role_tags: Record<string, string[]>;
  expression_tags: Record<string, string[]>;
  interaction_tags: Record<string, string[]>;
  preview_tags: string[];
}

const RECIPE_KEY = 'rider-studio:action-recipes-v1';
const COMPOSER_MODE_KEY = 'rider-studio:action-composer-mode-v1';

const EMPTY_CATALOG: ActionCatalog = {
  base_states: [],
  pelvis_states: [],
  near_leg_states: [],
  far_leg_states: [],
  arm_states: [],
  head_states: [],
  expressions: [],
  gazes: [],
  source_parts: [],
  actions: [],
  target_parts: [],
  primary_actions: [],
  phases: [],
  direction_profiles: [],
};

function role(
  slot: RoleSlot,
  gender: Gender,
  overrides: Partial<RoleRecipe> = {},
): RoleRecipe {
  return {
    slot,
    gender,
    base: gender === 'female' ? 'side_lying' : 'sitting',
    pelvis: 'toward_partner',
    near_leg: gender === 'female' ? 'extended' : 'bent',
    far_leg: gender === 'female' ? 'raised' : 'bent',
    arms: gender === 'female' ? 'support' : 'hold_partner_leg',
    head: gender === 'female' ? 'look_back' : 'lowered',
    expression: 'tense',
    gaze: 'look_partner',
    ...overrides,
  };
}

function defaultRecipe(): ActionRecipe {
  return {
    name: '侧卧抬腿 · 对方坐姿支撑',
    direction_profile: 'male_dominant',
    dominant_role: 'B',
    receiving_role: 'A',
    roles: [role('A', 'female'), role('B', 'male')],
    interactions: [
      {
        id: 'interaction-1',
        source_role: 'B',
        source_part: 'hands',
        action: 'support',
        target_role: 'A',
        target_part: 'far_leg',
      },
      {
        id: 'interaction-2',
        source_role: 'B',
        source_part: 'hands',
        action: 'grab',
        target_role: 'A',
        target_part: 'breast',
      },
    ],
    primary_action: 'vaginal_insertion',
    phase: 'ongoing',
  };
}

function cloneRecipe(recipe: ActionRecipe): ActionRecipe {
  return JSON.parse(JSON.stringify(recipe)) as ActionRecipe;
}

function loadRecipes(): Record<string, ActionRecipe> {
  try {
    const raw = localStorage.getItem(RECIPE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, ActionRecipe>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function optionLabel(options: CatalogOption[], id: string): string {
  return options.find((item) => item.id === id)?.label || id;
}

function RoleOptions({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: CatalogOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="action-role-field">
      <span>{label}</span>
      <div className="action-option-pills">
        {options.map((item) => (
          <button
            type="button"
            key={item.id}
            className={item.id === value ? 'selected' : ''}
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export interface ActionComposerPanelProps {
  activeGroupId?: string;
  onApplied?: () => void;
}

export default function ActionComposerPanel({
  activeGroupId,
  onApplied,
}: ActionComposerPanelProps) {
  const groups = drawStore.groups;
  const [catalog, setCatalog] = useState<ActionCatalog>(EMPTY_CATALOG);
  const [recipe, setRecipe] = useState<ActionRecipe>(defaultRecipe);
  const [mode, setMode] = useState<ComposerMode>(() =>
    localStorage.getItem(COMPOSER_MODE_KEY) === 'advanced' ? 'advanced' : 'simple',
  );
  const [template, setTemplate] = useState('side_raised');
  const [activeRole, setActiveRole] = useState<RoleSlot>('A');
  const [savedRecipes, setSavedRecipes] = useState<Record<string, ActionRecipe>>(loadRecipes);
  const [selectedRecipe, setSelectedRecipe] = useState('');
  const [recipeName, setRecipeName] = useState('');
  const [compiled, setCompiled] = useState<CompileResult | null>(null);

  useEffect(() => {
    api
      .get<ActionCatalog>('/prompt-agent/action-composer')
      .then((response) => setCatalog(response.data))
      .catch(() => message.error('动作目录加载失败'));
  }, []);

  useEffect(() => {
    localStorage.setItem(COMPOSER_MODE_KEY, mode);
  }, [mode]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const { data } = await api.post<CompileResult>(
          '/prompt-agent/compile-action-recipe',
          recipe,
        );
        if (!cancelled) setCompiled(data);
      } catch (error: unknown) {
        if (!cancelled) {
          const detail = (error as { response?: { data?: { detail?: string } } })
            .response?.data?.detail;
          setCompiled({
            ok: false,
            errors: [detail || '动作组合校验失败'],
            warnings: [],
            role_tags: {},
            expression_tags: {},
            interaction_tags: {},
            preview_tags: [],
          });
        }
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [recipe]);

  const currentRole = recipe.roles.find((item) => item.slot === activeRole) || recipe.roles[0];
  const currentGroup =
    groups.find((group) => group.id === activeGroupId) || groups[0];

  const updateRole = (patch: Partial<RoleRecipe>) => {
    setRecipe((current) => ({
      ...current,
      roles: current.roles.map((item) =>
        item.slot === activeRole ? { ...item, ...patch } : item,
      ),
    }));
  };

  const updateRoleGender = (slot: RoleSlot, gender: Gender) => {
    setRecipe((current) => {
      const next = cloneRecipe(current);
      const target = next.roles.find((item) => item.slot === slot);
      if (target) target.gender = gender;
      if (next.roles.length === 2) {
        const genders = new Set(next.roles.map((item) => item.gender));
        if (genders.has('male')) {
          const male = next.roles.find((item) => item.gender === 'male');
          const female = next.roles.find((item) => item.gender === 'female');
          if (male && female) {
            next.direction_profile = 'male_dominant';
            next.dominant_role = male.slot;
            next.receiving_role = female.slot;
          }
        } else {
          next.direction_profile = 'same_sex_custom';
          next.dominant_role = 'A';
          next.receiving_role = 'B';
        }
      }
      return next;
    });
  };

  const updateInteractionRow = (id: string, patch: Partial<InteractionRecipe>) => {
    setRecipe((current) => ({
      ...current,
      interactions: current.interactions.map((item) =>
        item.id === id ? { ...item, ...patch } : item,
      ),
    }));
  };

  const addInteraction = () => {
    const limit = mode === 'simple' ? 3 : 4;
    if (recipe.interactions.length >= limit) {
      message.warning(`当前模式最多支持 ${limit} 个动作步骤`);
      return;
    }
    setRecipe((current) => ({
      ...current,
      interactions: [
        ...current.interactions,
        {
          id: `interaction-${Date.now()}`,
          source_role: 'B',
          source_part: 'hands',
          action: 'contact',
          target_role: 'A',
          target_part: 'waist',
        },
      ],
    }));
  };

  const removeInteraction = (id: string) => {
    setRecipe((current) => ({
      ...current,
      interactions: current.interactions.filter((item) => item.id !== id),
    }));
  };

  const moveInteraction = (id: string, direction: -1 | 1) => {
    setRecipe((current) => {
      const index = current.interactions.findIndex((item) => item.id === id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.interactions.length) {
        return current;
      }
      const interactions = [...current.interactions];
      [interactions[index], interactions[target]] = [
        interactions[target],
        interactions[index],
      ];
      return { ...current, interactions };
    });
  };

  const loadRecipe = (value: string) => {
    setSelectedRecipe(value);
    const stored = savedRecipes[value];
    if (stored) {
      setRecipe(cloneRecipe(stored));
      setRecipeName(stored.name);
      setActiveRole('A');
    }
  };

  const saveRecipe = () => {
    const name = recipeName.trim() || recipe.name.trim();
    if (!name) {
      message.warning('请输入玩法名称');
      return;
    }
    const next = { ...savedRecipes, [name]: { ...cloneRecipe(recipe), name } };
    localStorage.setItem(RECIPE_KEY, JSON.stringify(next));
    setSavedRecipes(next);
    setSelectedRecipe(name);
    message.success('已保存为我的玩法');
  };

  const templateOptions = [
    { label: '侧卧抬腿 · 对方坐姿支撑', value: 'side_raised' },
    { label: '跪姿 · 后方互动', value: 'kneeling_rear' },
    { label: '女女 · 并肩互动', value: 'female_pair' },
  ];

  const applyTemplate = (value: string) => {
    setTemplate(value);
    if (value === 'kneeling_rear') {
      const next = defaultRecipe();
      next.name = '跪姿 · 后方互动';
      next.roles = [
        role('A', 'female', { base: 'kneeling', pelvis: 'away', arms: 'support', head: 'tilted', expression: 'enduring', gaze: 'closed_eyes' }),
        role('B', 'male', { base: 'kneeling', pelvis: 'toward_partner', head: 'lowered' }),
      ];
      next.interactions = [
        { id: 'interaction-1', source_role: 'B', source_part: 'hands', action: 'grab', target_role: 'A', target_part: 'waist' },
        { id: 'interaction-2', source_role: 'B', source_part: 'pelvis', action: 'contact', target_role: 'A', target_part: 'pelvis' },
      ];
      next.primary_action = 'anal_insertion';
      setRecipe(next);
      return;
    }
    if (value === 'female_pair') {
      const next = defaultRecipe();
      next.name = '女女 · 并肩互动';
      next.direction_profile = 'same_sex_custom';
      next.dominant_role = 'A';
      next.receiving_role = 'B';
      next.roles = [
        role('A', 'female', { base: 'sitting', pelvis: 'side', near_leg: 'bent', far_leg: 'bent', arms: 'natural', head: 'facing', expression: 'smile' }),
        role('B', 'female', { base: 'sitting', pelvis: 'side', near_leg: 'bent', far_leg: 'bent', arms: 'hold_partner', head: 'facing', expression: 'smile' }),
      ];
      next.interactions = [
        { id: 'interaction-1', source_role: 'A', source_part: 'hands', action: 'kiss', target_role: 'B', target_part: 'shoulder' },
        { id: 'interaction-2', source_role: 'B', source_part: 'hands', action: 'support', target_role: 'A', target_part: 'waist' },
      ];
      setRecipe(next);
      return;
    }
    setRecipe(defaultRecipe());
  };

  const applyToDraw = () => {
    if (!compiled?.ok) {
      message.error(compiled?.errors[0] || '动作组合尚未通过校验');
      return;
    }
    if (!currentGroup) {
      message.warning('当前没有可应用的提示词组');
      return;
    }
    let document = normalizePromptDocument(
      currentGroup.prompt_document || createEmptyStructuredDocument(),
    );
    document.mode = 'structured';

    const ensured = recipe.roles.map((roleItem, index) => {
      const existing = document.characters[index];
      if (existing) return { ...existing, order: index };
      return createPromptCharacter(index, { gender: roleItem.gender === 'male' ? '男' : '女' });
    });
    document.characters = ensured;

    for (const roleItem of recipe.roles) {
      const index = roleItem.slot === 'A' ? 0 : 1;
      const character = document.characters[index];
      if (!character) continue;
      document = updateCharacter(document, character.id, (item) => ({
        ...item,
        order: index,
        enabled: true,
        gender: roleItem.gender === 'male' ? '男' : '女',
        role_id:
          roleItem.gender === 'male'
            ? roleItem.slot === 'A'
              ? 'boyA'
              : 'boyB'
            : roleItem.slot === 'A'
              ? 'girlA'
              : 'girlB',
        display_name:
          roleItem.gender === 'male'
            ? roleItem.slot === 'A'
              ? '男A'
              : '男B'
            : roleItem.slot === 'A'
              ? '女A'
              : '女B',
        pose_or_action: {
          ...item.pose_or_action,
          tags: compiled.role_tags[roleItem.slot] || [],
          source: 'action-composer',
        },
        expression: {
          ...item.expression,
          tags:
            roleItem.gender === 'female'
              ? compiled.expression_tags[roleItem.slot] || []
              : [],
          enabled: roleItem.gender === 'female',
          source: 'action-composer',
        },
        state: {
          ...item.state,
          tags: [optionLabel(catalog.phases, recipe.phase)],
          source: 'action-composer',
        },
      }));
    }

    document = updateInteraction(document, (interaction) => ({
      ...interaction,
      pose_preset: undefined,
      action_tags: compiled.interaction_tags.action_tags || [],
      contact_tags: compiled.interaction_tags.contact_tags || [],
      relationship_tags: compiled.interaction_tags.relationship_tags || [],
      composition_constraints: compiled.interaction_tags.composition_constraints || [],
    }));

    updateGroupDocument(currentGroup.id, document);
    message.success(`已应用到${currentGroup.id === activeGroupId ? '当前' : '第一'}提示词组`);
    onApplied?.();
  };

  const buildOptions = (items: CatalogOption[], includeEmpty = false) => [
    ...(includeEmpty ? [{ label: '不设置', value: '' }] : []),
    ...items.map((item) => ({ label: item.label, value: item.id })),
  ];

  const interactionColumns: ColumnsType<InteractionRecipe> = [
    {
      title: '执行方',
      key: 'source',
      width: 220,
      render: (_, row) => (
        <Space.Compact block>
          <Select
            value={row.source_role}
            options={[{ value: 'A', label: 'A' }, { value: 'B', label: 'B' }]}
            onChange={(value) => updateInteractionRow(row.id, { source_role: value })}
            style={{ width: 56 }}
          />
          <Select
            value={row.source_part}
            options={buildOptions(catalog.source_parts)}
            onChange={(value) => updateInteractionRow(row.id, { source_part: value })}
            style={{ width: 120 }}
          />
        </Space.Compact>
      ),
    },
    {
      title: '动作',
      dataIndex: 'action',
      width: 110,
      render: (value: string, row) => (
        <Select
          value={value}
          options={buildOptions(catalog.actions)}
          onChange={(next) => updateInteractionRow(row.id, { action: next })}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '目标方',
      key: 'target',
      width: 240,
      render: (_, row) => (
        <Space.Compact block>
          <Select
            value={row.target_role}
            options={[{ value: 'A', label: 'A' }, { value: 'B', label: 'B' }]}
            onChange={(value) => updateInteractionRow(row.id, { target_role: value })}
            style={{ width: 56 }}
          />
          <Select
            value={row.target_part}
            options={catalog.target_parts
              .filter((item) => {
                const target = recipe.roles.find((roleItem) => roleItem.slot === row.target_role);
                return !item.owner_gender || item.owner_gender === target?.gender;
              })
              .map((item) => ({ label: item.label, value: item.id }))}
            onChange={(value) => updateInteractionRow(row.id, { target_part: value })}
            style={{ width: 125 }}
          />
        </Space.Compact>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 50,
      render: (_, row) => (
        <Button danger type="text" onClick={() => removeInteraction(row.id)}>
          删除
        </Button>
      ),
    },
  ];

  const directionText =
    recipe.direction_profile === 'same_sex_custom'
      ? `主导角色${recipe.dominant_role} → 接收角色${recipe.receiving_role}`
      : recipe.direction_profile === 'female_dominant'
        ? '女性主导 → 男性接收'
        : '男性主导 → 女性接收';

  const helpContent = (
    <div className="action-help-content">
      <ol>
        <li>简单模式先用模板起步，只设置基础姿态、手臂、头部和 1–3 个动作步骤。</li>
        <li>高级模式可继续调整骨盆、近远侧腿、主动作阶段、主导关系和完整交互表。</li>
        <li>动作步骤可以用上下箭调整顺序，每步表达“谁 → 做什么 → 对谁”。</li>
        <li>切换模式不会删除 recipe 字段或已保存玩法。</li>
        <li>女性角色可以设置表情与视线，男性角色只保留姿态和动作。</li>
        <li>校验通过后应用到当前提示词组。</li>
      </ol>
      <p>第一版男女组合默认男性主导、女性接收；女女组合需要显式设置主导角色。</p>
    </div>
  );

  return (
    <div className="action-composer-panel">
      <div className="action-composer-toolbar">
        <Space wrap>
          <Segmented
            value={mode}
            options={[
              { value: 'simple', label: '简单' },
              { value: 'advanced', label: '高级' },
            ]}
            onChange={(value) => setMode(value as ComposerMode)}
          />
          <Select
            value={template}
            options={templateOptions}
            onChange={applyTemplate}
            style={{ width: 250 }}
            placeholder="从模板开始"
          />
          <Tag color="processing">{directionText}</Tag>
          <Tag color={compiled?.ok ? 'success' : 'error'}>
            {compiled?.ok ? '校验通过' : `${compiled?.errors.length || 0} 个错误`}
          </Tag>
          <span className="action-composer-context">
            当前提示词组：{currentGroup?.id || '未选择'}
          </span>
        </Space>
        <Popover content={helpContent} title="动作编排使用说明" trigger="click">
          <Button>使用说明</Button>
        </Popover>
      </div>

      <Row gutter={[12, 12]} className="action-composer-grid">
        <Col xs={24} lg={7} xl={6}>
          <Card
            size="small"
            title={mode === 'simple' ? '角色基础姿态' : '角色与身体状态'}
            className="action-composer-card"
          >
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <Space wrap>
                <Button
                  type={activeRole === 'A' ? 'primary' : 'default'}
                  onClick={() => setActiveRole('A')}
                >
                  角色A · {recipe.roles[0]?.gender === 'male' ? '男' : '女'}
                </Button>
                <Button
                  type={activeRole === 'B' ? 'primary' : 'default'}
                  onClick={() => setActiveRole('B')}
                >
                  角色B · {recipe.roles[1]?.gender === 'male' ? '男' : '女'}
                </Button>
              </Space>
              <label className="action-select-field">
                <span>角色性别</span>
                <Select
                  value={currentRole.gender}
                  options={[
                    { value: 'female', label: '女性' },
                    { value: 'male', label: '男性' },
                  ]}
                  onChange={(value) => updateRoleGender(activeRole, value)}
                />
              </label>
              <RoleOptions
                label="基础姿态"
                options={catalog.base_states}
                value={currentRole.base}
                onChange={(value) => updateRole({ base: value })}
              />
              {mode === 'advanced' ? (
                <>
                  <RoleOptions
                    label="骨盆与躯干"
                    options={catalog.pelvis_states}
                    value={currentRole.pelvis}
                    onChange={(value) => updateRole({ pelvis: value })}
                  />
                  <RoleOptions
                    label="近侧腿"
                    options={catalog.near_leg_states}
                    value={currentRole.near_leg}
                    onChange={(value) => updateRole({ near_leg: value })}
                  />
                  <RoleOptions
                    label="远侧腿"
                    options={catalog.far_leg_states}
                    value={currentRole.far_leg}
                    onChange={(value) => updateRole({ far_leg: value })}
                  />
                </>
              ) : null}
              <RoleOptions
                label="手臂状态"
                options={catalog.arm_states}
                value={currentRole.arms}
                onChange={(value) => updateRole({ arms: value })}
              />
              <RoleOptions
                label="头部朝向"
                options={catalog.head_states}
                value={currentRole.head}
                onChange={(value) => updateRole({ head: value })}
              />
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={10} xl={11}>
          <Card
            size="small"
            title={mode === 'simple' ? '动作步骤' : '结构化动作交互表'}
            extra={<Button type="primary" ghost onClick={addInteraction}>添加动作</Button>}
            className="action-composer-card"
          >
            {mode === 'simple' ? (
              <div className="action-step-list">
                {recipe.interactions.length ? (
                  recipe.interactions.map((row, index) => {
                    const target = recipe.roles.find(
                      (roleItem) => roleItem.slot === row.target_role,
                    );
                    return (
                      <Card
                        key={row.id}
                        size="small"
                        className="action-step-card"
                        title={`步骤 ${index + 1}`}
                        extra={
                          <Space size={2}>
                            <Tooltip title="上移">
                              <Button
                                type="text"
                                size="small"
                                aria-label="上移动作步骤"
                                icon={<ArrowUpOutlined />}
                                disabled={index === 0}
                                onClick={() => moveInteraction(row.id, -1)}
                              />
                            </Tooltip>
                            <Tooltip title="下移">
                              <Button
                                type="text"
                                size="small"
                                aria-label="下移动动作步骤"
                                icon={<ArrowDownOutlined />}
                                disabled={index === recipe.interactions.length - 1}
                                onClick={() => moveInteraction(row.id, 1)}
                              />
                            </Tooltip>
                            <Button
                              danger
                              type="text"
                              size="small"
                              onClick={() => removeInteraction(row.id)}
                            >
                              删除
                            </Button>
                          </Space>
                        }
                      >
                        <div className="action-step-row">
                          <div className="action-step-block">
                            <span>执行方</span>
                            <Space.Compact block>
                              <Select
                                value={row.source_role}
                                options={[
                                  { value: 'A', label: '角色A' },
                                  { value: 'B', label: '角色B' },
                                ]}
                                onChange={(value) =>
                                  updateInteractionRow(row.id, { source_role: value })
                                }
                              />
                              <Select
                                value={row.source_part}
                                options={buildOptions(catalog.source_parts)}
                                onChange={(value) =>
                                  updateInteractionRow(row.id, { source_part: value })
                                }
                              />
                            </Space.Compact>
                          </div>
                          <span className="action-step-arrow">→</span>
                          <label className="action-step-block">
                            <span>动作</span>
                            <Select
                              value={row.action}
                              options={buildOptions(catalog.actions)}
                              onChange={(value) =>
                                updateInteractionRow(row.id, { action: value })
                              }
                            />
                          </label>
                          <span className="action-step-arrow">→</span>
                          <div className="action-step-block">
                            <span>目标方</span>
                            <Space.Compact block>
                              <Select
                                value={row.target_role}
                                options={[
                                  { value: 'A', label: '角色A' },
                                  { value: 'B', label: '角色B' },
                                ]}
                                onChange={(value) =>
                                  updateInteractionRow(row.id, { target_role: value })
                                }
                              />
                              <Select
                                value={row.target_part}
                                options={catalog.target_parts
                                  .filter(
                                    (item) =>
                                      !item.owner_gender ||
                                      item.owner_gender === target?.gender,
                                  )
                                  .map((item) => ({
                                    label: item.label,
                                    value: item.id,
                                  }))}
                                onChange={(value) =>
                                  updateInteractionRow(row.id, { target_part: value })
                                }
                              />
                            </Space.Compact>
                          </div>
                        </div>
                      </Card>
                    );
                  })
                ) : (
                  <Empty description="尚未添加动作步骤" />
                )}
                <div className="action-simple-summary">
                  <Tag>主动作：{optionLabel(catalog.primary_actions, recipe.primary_action)}</Tag>
                  <Tag>阶段：{optionLabel(catalog.phases, recipe.phase)}</Tag>
                  <Tag>{directionText}</Tag>
                </div>
              </div>
            ) : (
              <>
                <Table
                  rowKey="id"
                  columns={interactionColumns}
                  dataSource={recipe.interactions}
                  pagination={false}
                  size="small"
                  scroll={{ x: 620 }}
                  locale={{ emptyText: <Empty description="尚未添加动作交互" /> }}
                />
                <Divider />
                <Row gutter={[10, 10]}>
                  <Col xs={24} md={12}>
                    <label className="action-select-field">
                      <span>主动作</span>
                      <Select
                        value={recipe.primary_action}
                        options={buildOptions(catalog.primary_actions)}
                        onChange={(value) =>
                          setRecipe((current) => ({ ...current, primary_action: value }))
                        }
                      />
                    </label>
                  </Col>
                  <Col xs={24} md={12}>
                    <label className="action-select-field">
                      <span>动作阶段</span>
                      <Select
                        value={recipe.phase}
                        options={buildOptions(catalog.phases)}
                        onChange={(value) =>
                          setRecipe((current) => ({ ...current, phase: value }))
                        }
                      />
                    </label>
                  </Col>
                </Row>
                {recipe.direction_profile === 'same_sex_custom' ? (
                  <Row gutter={[10, 10]} style={{ marginTop: 10 }}>
                    <Col span={12}>
                      <label className="action-select-field">
                        <span>主导角色</span>
                        <Select
                          value={recipe.dominant_role}
                          options={[
                            { value: 'A', label: '角色A' },
                            { value: 'B', label: '角色B' },
                          ]}
                          onChange={(value) =>
                            setRecipe((current) => ({ ...current, dominant_role: value }))
                          }
                        />
                      </label>
                    </Col>
                    <Col span={12}>
                      <label className="action-select-field">
                        <span>接收角色</span>
                        <Select
                          value={recipe.receiving_role}
                          options={[
                            { value: 'A', label: '角色A' },
                            { value: 'B', label: '角色B' },
                          ]}
                          onChange={(value) =>
                            setRecipe((current) => ({ ...current, receiving_role: value }))
                          }
                        />
                      </label>
                    </Col>
                  </Row>
                ) : null}
              </>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={7} xl={7}>
          <Card size="small" title="校验、表情与输出" className="action-composer-card">
            {currentRole.gender === 'female' ? (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <RoleOptions
                  label="主要表情"
                  options={catalog.expressions}
                  value={currentRole.expression}
                  onChange={(value) => updateRole({ expression: value })}
                />
                <RoleOptions
                  label="视线"
                  options={catalog.gazes}
                  value={currentRole.gaze}
                  onChange={(value) => updateRole({ gaze: value })}
                />
              </Space>
            ) : (
              <Alert
                type="info"
                showIcon
                message="男性角色第一版只配置姿态、接触和动作，不提供表情、视线和面部细节。"
              />
            )}

            <Divider>校验状态</Divider>
            <div className="action-validation">
              {compiled?.errors.map((item) => (
                <Alert key={item} type="error" showIcon message={item} />
              ))}
              {compiled?.warnings.map((item) => (
                <Alert key={item} type="warning" showIcon message={item} />
              ))}
              {compiled?.ok && !compiled.warnings.length ? (
                <Alert type="success" showIcon message="动作组合校验通过" />
              ) : null}
            </div>

            <Divider>最终写入标签</Divider>
            <div className="action-preview-tags">
              {(compiled?.preview_tags || []).map((tag) => (
                <Tag key={tag}>{tag}</Tag>
              ))}
            </div>

            <Divider />
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Input
                value={recipeName}
                placeholder="我的玩法名称"
                onChange={(event) => setRecipeName(event.target.value)}
                onPressEnter={saveRecipe}
              />
              <Space.Compact block>
                <Select
                  value={selectedRecipe || undefined}
                  placeholder="载入已保存玩法"
                  options={Object.keys(savedRecipes).map((name) => ({ value: name, label: name }))}
                  onChange={loadRecipe}
                  style={{ flex: 1 }}
                />
                <Tooltip title="保存当前组合为本地玩法">
                  <Button onClick={saveRecipe}>保存</Button>
                </Tooltip>
              </Space.Compact>
              <Button type="primary" block disabled={!compiled?.ok} onClick={applyToDraw}>
                应用到当前提示词组
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
