// 提示词 Agent 工作区：图片反推 + 自然语言生成
import { Button, Checkbox, Input, Radio, Space } from 'antd';
import { promptStore, fromImage, fromText, sendToDraw } from '../stores/prompt';

export default function PromptAgent() {
  const { mode, imageBase64, imageName, text, result, status, autoDraw } = promptStore;

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      promptStore.imageBase64 = String(reader.result);
      promptStore.imageName = file.name;
    };
    reader.readAsDataURL(file);
  };

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
        <div className="result panel-box">
          <div className="status">{status}</div>
          {result?.description ? <div className="result-block">原始描述：{result.description}</div> : null}
          {result?.prompt ? <div className="result-block">英文提示词：{result.prompt}</div> : null}
          <Space direction="vertical" style={{ marginTop: 12 }}>
            <Checkbox checked={autoDraw} onChange={(e) => (promptStore.autoDraw = e.target.checked)}>
              发送到绘画区后自动开始生成
            </Checkbox>
            <Button onClick={sendToDraw}>发送到绘画区</Button>
          </Space>
        </div>
      </div>
    </div>
  );
}
