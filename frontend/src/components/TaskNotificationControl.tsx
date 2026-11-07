import { BellOutlined } from '@ant-design/icons';
import { Button, Popover, Space, Switch, Tooltip, message } from 'antd';
import {
  setDesktopNotificationsEnabled,
  setSoundNotificationsEnabled,
  taskNotificationStore,
} from '../stores/taskNotifications';

export default function TaskNotificationControl() {
  const content = (
    <Space direction="vertical" size={10} style={{ minWidth: 220 }}>
      <div>
        <div className="setting-label">完成声音</div>
        <Switch
          checked={taskNotificationStore.soundEnabled}
          onChange={setSoundNotificationsEnabled}
        />
      </div>
      <div>
        <div className="setting-label">桌面通知</div>
        <Switch
          checked={taskNotificationStore.desktopEnabled}
          onChange={(checked) => {
            void setDesktopNotificationsEnabled(checked).then((allowed) => {
              if (checked && !allowed) {
                message.warning('浏览器未授予桌面通知权限');
              }
            });
          }}
        />
      </div>
      <span className="help">页面刷新后保持设置；同一完成事件只提示一次。</span>
    </Space>
  );

  return (
    <Popover title="任务完成通知" content={content} trigger="click">
      <Tooltip title="任务完成通知">
        <Button
          size="small"
          type="text"
          icon={<BellOutlined />}
          aria-label="任务完成通知设置"
        />
      </Tooltip>
    </Popover>
  );
}
