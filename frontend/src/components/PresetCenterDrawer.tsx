import { AppstoreOutlined, PictureOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Drawer, Space, Tabs } from 'antd';
import { useEffect, useState } from 'react';
import {
  loadPresetCenterState,
  savePresetCenterState,
} from '../presetLibraryState';
import PresetLibraryPanel, {
  type PresetLibraryApplyOptions,
  type PresetLibraryItem,
} from './PresetLibraryPanel';

export interface PresetCenterDrawerProps {
  open: boolean;
  onClose: () => void;
  onApply?: (
    kind: string,
    item: PresetLibraryItem,
    options: PresetLibraryApplyOptions,
  ) => void;
  onAddToComposition?: (kind: string, item: PresetLibraryItem) => void;
  onManageThumbnail?: (kind: string, item: PresetLibraryItem) => void;
  onOpenComposition?: () => void;
  onOpenWorkshop?: () => void;
  onOpenCharacter?: () => void;
}

export default function PresetCenterDrawer({
  open,
  onClose,
  onApply,
  onAddToComposition,
  onManageThumbnail,
  onOpenComposition,
  onOpenWorkshop,
  onOpenCharacter,
}: PresetCenterDrawerProps) {
  const [activeSection, setActiveSection] = useState(
    () => loadPresetCenterState().activeSection,
  );

  useEffect(() => {
    savePresetCenterState({ activeSection });
  }, [activeSection]);

  const items = [
    {
      key: 'browse',
      label: '浏览预设',
      children: (
        <PresetLibraryPanel
          variant="drawer"
          onApply={onApply}
          onAddToComposition={onAddToComposition}
          onManageThumbnail={onManageThumbnail}
        />
      ),
    },
    {
      key: 'composition',
      label: '预设组合',
      children: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="预设组合会把多个类型合并为同一个最终提示词。"
          />
          <Button
            type="primary"
            icon={<AppstoreOutlined />}
            onClick={onOpenComposition}
          >
            打开预设组合
          </Button>
        </Space>
      ),
    },
    {
      key: 'workshop',
      label: '预设工坊',
      children: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="用于管理候选图、版本和缩略图。可在浏览预设时直接进入指定预设。"
          />
          <Button icon={<PictureOutlined />} onClick={onOpenWorkshop}>
            打开预设工坊
          </Button>
        </Space>
      ),
    },
    {
      key: 'character',
      label: '角色工具',
      children: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="查询、填写和管理角色外貌与默认服装。"
          />
          <Button icon={<UserOutlined />} onClick={onOpenCharacter}>
            打开角色外貌
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Drawer
      title="预设选择器"
      width="min(1280px, 96vw)"
      open={open}
      onClose={onClose}
      destroyOnClose={false}
      className="preset-center-drawer"
    >
      <Tabs
        className="preset-center-tabs"
        activeKey={activeSection}
        items={items}
        onChange={setActiveSection}
      />
    </Drawer>
  );
}
