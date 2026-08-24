// AI 绘画工作区：多组提示词批量生成
import { Button, Checkbox, Input, InputNumber, Select, Space } from 'antd';
import { useEffect, useState } from 'react';
import { api, type LoraItem, type ModelItem } from '../api';
import {
  addGroup,
  drawStore,
  removeGroup,
  runDraw,
  updateGroupCount,
  updateGroupPrompt,
} from '../stores/draw';

const sizeOptions = [
  { label: '竖版 1080×1920', value: '1080x1920' },
  { label: '横版 1920×1080', value: '1920x1080' },
  { label: '方形 1024×1024', value: '1024x1024' },
];

async function translate(text: string): Promise<string> {
  if (!text.trim()) return '';
  try {
    const { data } = await api.post('/translate', { text });
    return data.translation || '';
  } catch (e) {
    return '';
  }
}

export default function DrawPanel() {
  const { model, groups, negativePrompt, width, height, steps, cfg, loras, generating, status, total, done, results } =
    drawStore;
  const [lorasList, setLorasList] = useState<LoraItem[]>([]);
  const [modelsList, setModelsList] = useState<ModelItem[]>([]);
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [negTrans, setNegTrans] = useState('');
  const [elapsed, setElapsed] = useState(0);

  // 生成过程中每秒更新按钮上的计时
  useEffect(() => {
    if (generating) {
      setElapsed(0);
      const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
      return () => window.clearInterval(timer);
    }
    setElapsed(0);
  }, [generating]);

  // 加载 LoRA 列表
  useEffect(() => {
    api
      .get('/loras')
      .then((res) => {
        const list = res.data.loras || [];
        setLorasList(list);
        // 默认选中 anima-turbo LoRA
        if (drawStore.loras.length === 0) {
          const turbo = list.find((item: LoraItem) => item.name.includes('anima-turbo'));
          if (turbo) drawStore.loras = [turbo.name];
        }
      })
      .catch(() => setLorasList([]));
  }, []);

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

  // 每组提示词实时翻译（防抖）
  const promptKey = groups.map((group) => group.prompt).join('|');
  useEffect(() => {
    const timer = setTimeout(async () => {
      const entries = await Promise.all(
        groups.map(async (group) => [group.id, await translate(group.prompt)] as const),
      );
      setTranslations(Object.fromEntries(entries));
    }, 900);
    return () => clearTimeout(timer);
  }, [promptKey]);

  // 负面提示词翻译（防抖）
  useEffect(() => {
    const timer = setTimeout(async () => setNegTrans(await translate(negativePrompt)), 900);
    return () => clearTimeout(timer);
  }, [negativePrompt]);

  return (
    <div className="draw-grid">
      <div className="controls panel-box">
        <label>提示词组</label>
        <div className="group-list">
          {groups.map((group, index) => (
            <div className="group-card" key={group.id}>
              <div className="group-header">
                <span>第 {index + 1} 组</span>
                <Space size={8}>
                  <span>张数</span>
                  <InputNumber
                    min={1}
                    max={10}
                    value={group.count}
                    onChange={(value) => updateGroupCount(group.id, value ?? 1)}
                  />
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
              <Input.TextArea
                rows={4}
                value={group.prompt}
                onChange={(e) => updateGroupPrompt(group.id, e.target.value)}
              />
              <div className="translate-text">{translations[group.id] ? `中文：${translations[group.id]}` : ''}</div>
            </div>
          ))}
        </div>
        <Button block onClick={addGroup} style={{ marginTop: 8 }}>
          添加一组
        </Button>

        <label>负面提示词</label>
        <Input.TextArea value={negativePrompt} onChange={(e) => (drawStore.negativePrompt = e.target.value)} rows={4} />
        <div className="translate-text">{negTrans ? `中文：${negTrans}` : ''}</div>

        <Space wrap style={{ marginTop: 8 }}>
          <span>模型</span>
          <Select
            style={{ minWidth: 260 }}
            value={model}
            options={modelsList.map((item) => ({ label: `${item.name} (${item.size_mb}MB)`, value: item.name }))}
            onChange={(value) => (drawStore.model = value)}
          />
        </Space>
        <Space wrap style={{ marginTop: 8 }}>
          <span>尺寸</span>
          <Select
            value={`${width}x${height}`}
            options={sizeOptions}
            onChange={(value) => {
              const [w, h] = value.split('x').map(Number);
              drawStore.width = w;
              drawStore.height = h;
            }}
          />
        </Space>
        <div className="help">尺寸：生成图片的宽高，竖版适合人物立绘，横版适合场景。</div>
        <Space wrap style={{ marginTop: 8 }}>
          <span>步数</span>
          <InputNumber min={1} max={80} value={steps} onChange={(value) => (drawStore.steps = value ?? 18)} />
          <span>CFG</span>
          <InputNumber min={0.5} max={20} step={0.5} value={cfg} onChange={(value) => (drawStore.cfg = value ?? 1)} />
        </Space>
        <div className="help">步数越高细节越多、耗时越长；CFG 越高越贴近提示词，加速 LoRA 通常用 1。</div>
        <div className="lora-list">
          {lorasList.map((item) => (
            <Checkbox
              key={item.name}
              checked={loras.includes(item.name)}
              onChange={(e) => {
                drawStore.loras = e.target.checked
                  ? [...loras, item.name]
                  : loras.filter((name: string) => name !== item.name);
              }}
            >
              {item.name} ({item.size_mb}MB)
            </Checkbox>
          ))}
        </div>
        <Button type="primary" block loading={generating} onClick={() => void runDraw()} style={{ marginTop: 12 }}>
          {generating ? `生成中 ${done}/${total} ${elapsed}s` : '生成图片'}
        </Button>
      </div>
      <div className="result panel-box">
        <div className="status">{status}</div>
        <div className="result-grid">
          {results.map((item, index) => (
            <div className="result-item" key={index}>
              <img src={item.image_url} alt={`第${(item.group_index ?? 0) + 1}组-第${(item.image_index ?? 0) + 1}张`} />
              <div className="result-label">
                第 {(item.group_index ?? 0) + 1} 组 · 第 {(item.image_index ?? 0) + 1} 张
              </div>
            </div>
          ))}
        </div>
        <Button onClick={() => window.open('http://127.0.0.1:8188', '_blank')}>打开 ComfyUI 面板</Button>
      </div>
    </div>
  );
}
