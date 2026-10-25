import { useEffect, useState } from 'react';
import ActionComposerPanel from './ActionComposerPanel';
import DrawPanel from './DrawPanel';
import InpaintPanel from './InpaintPanel';

type DrawingMode = 'draw' | 'inpaint' | 'composer';

const MODE_KEY = 'rider-studio:ai-drawing-mode-v1';

function loadMode(): DrawingMode {
  try {
    const value = localStorage.getItem(MODE_KEY);
    return value === 'composer' || value === 'inpaint' ? value : 'draw';
  } catch {
    return 'draw';
  }
}

export default function AIDrawingWorkspace() {
  const [mode, setMode] = useState<DrawingMode>(loadMode);
  const [activeGroupId, setActiveGroupId] = useState<string>('');
  const [inpaintSource, setInpaintSource] = useState<{
    recordId?: number;
    imageUrl: string;
    width: number;
    height: number;
    label: string;
  } | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {
      // Ignore local storage failures.
    }
  }, [mode]);

  return (
    <div className="ai-drawing-workspace">
      <div className="ai-drawing-mode-tabs" role="tablist" aria-label="AI 绘画模式">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'draw'}
          className={mode === 'draw' ? 'active' : ''}
          onClick={() => setMode('draw')}
        >
          绘画
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'inpaint'}
          className={mode === 'inpaint' ? 'active' : ''}
          onClick={() => setMode('inpaint')}
        >
          局部重绘
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'composer'}
          className={mode === 'composer' ? 'active' : ''}
          onClick={() => setMode('composer')}
        >
          动作编排
        </button>
      </div>
      <div className="ai-drawing-mode-panel" hidden={mode !== 'draw'}>
        <DrawPanel
          controlledActiveGroupId={activeGroupId}
          onActiveGroupIdChange={setActiveGroupId}
          onSendToInpaint={(source) => {
            setInpaintSource(source);
            setMode('inpaint');
          }}
        />
      </div>
      <div className="ai-drawing-mode-panel" hidden={mode !== 'inpaint'}>
        <InpaintPanel initialSource={inpaintSource ?? undefined} />
      </div>
      <div className="ai-drawing-mode-panel" hidden={mode !== 'composer'}>
        <ActionComposerPanel
          activeGroupId={activeGroupId}
          onApplied={() => setMode('draw')}
        />
      </div>
    </div>
  );
}
