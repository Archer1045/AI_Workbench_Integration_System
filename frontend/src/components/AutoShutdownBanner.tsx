// 任务完成后自动关机倒计时横幅：跨 tab 可见并提供取消入口
import { Button, message } from 'antd';
import { autoShutdownStore, cancelAutoShutdown } from '../stores/autoShutdown';

export default function AutoShutdownBanner() {
  if (!autoShutdownStore.enabled || autoShutdownStore.phase !== 'pending') {
    return null;
  }

  const handleCancel = async () => {
    try {
      await cancelAutoShutdown();
      message.success('已取消本次自动关机');
    } catch {
      message.error('取消自动关机失败');
    }
  };

  return (
    <div className="auto-shutdown-banner">
      <span className="auto-shutdown-banner-text">
        任务已完成，{autoShutdownStore.remaining_seconds ?? 0} 秒后自动关机
      </span>
      <Button danger size="small" onClick={() => void handleCancel()}>
        取消关机
      </Button>
    </div>
  );
}
