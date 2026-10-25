import type { PromptDocumentV1 } from './api';
import {
  mergeTags,
  updateGlobalBlock,
  updateNegativeBlock,
} from './promptDocument';

export type DrawPromptFragmentCategory =
  | '质量'
  | '风格'
  | '镜头'
  | '光照'
  | '场景'
  | '负向-质量'
  | '负向-身体'
  | '负向-构图'
  | '负向-内容';

export interface DrawPromptFragment {
  id: string;
  label: string;
  category: DrawPromptFragmentCategory;
  description: string;
  tags: string[];
  target:
    | 'quality'
    | 'style'
    | 'camera'
    | 'lighting'
    | 'scene'
    | 'negative_quality'
    | 'negative_anatomy'
    | 'negative_composition'
    | 'negative_content';
}

export const DRAW_PROMPT_FRAGMENTS: DrawPromptFragment[] = [
  {
    id: 'fragment_quality_clean',
    label: '清晰高质量',
    category: '质量',
    description: '通用高质量正向片段',
    tags: ['masterpiece', 'best quality', 'highres', 'very aesthetic'],
    target: 'quality',
  },
  {
    id: 'fragment_quality_illustration',
    label: '精致插画',
    category: '质量',
    description: '强调细节和插画质感',
    tags: ['detailed illustration', 'intricate details', 'clean lineart'],
    target: 'quality',
  },
  {
    id: 'fragment_style_anime',
    label: '现代动画色',
    category: '风格',
    description: '明亮、干净的现代动漫上色',
    tags: ['modern anime style', 'clean colors', 'anime coloring'],
    target: 'style',
  },
  {
    id: 'fragment_style_film',
    label: '胶片颗粒',
    category: '风格',
    description: '轻微胶片质感和自然颗粒',
    tags: ['subtle film grain', 'analog photography feel'],
    target: 'style',
  },
  {
    id: 'fragment_camera_full_body',
    label: '完整全身',
    category: '镜头',
    description: '完整头部、身体和双脚',
    tags: ['full body', 'entire body visible', 'complete head and feet'],
    target: 'camera',
  },
  {
    id: 'fragment_camera_upper',
    label: '半身构图',
    category: '镜头',
    description: '腰上构图，兼顾面部与服装',
    tags: ['upper body', 'cowboy shot'],
    target: 'camera',
  },
  {
    id: 'fragment_camera_closeup',
    label: '面部特写',
    category: '镜头',
    description: '突出面部和表情细节',
    tags: ['close-up', 'detailed face'],
    target: 'camera',
  },
  {
    id: 'fragment_camera_low',
    label: '低视角',
    category: '镜头',
    description: '从下往上的画面角度',
    tags: ['from below', 'low angle'],
    target: 'camera',
  },
  {
    id: 'fragment_camera_high',
    label: '高视角',
    category: '镜头',
    description: '从上往下的画面角度',
    tags: ['from above', 'high angle'],
    target: 'camera',
  },
  {
    id: 'fragment_camera_shallow',
    label: '浅景深',
    category: '镜头',
    description: '主体清晰、背景虚化',
    tags: ['shallow depth of field', 'background blur', 'subject in sharp focus'],
    target: 'camera',
  },
  {
    id: 'fragment_light_soft',
    label: '柔和电影光',
    category: '光照',
    description: '柔和均匀的电影感光线',
    tags: ['cinematic lighting', 'soft light', 'gentle shadows'],
    target: 'lighting',
  },
  {
    id: 'fragment_light_dramatic',
    label: '戏剧光',
    category: '光照',
    description: '明显明暗对比',
    tags: ['dramatic lighting', 'chiaroscuro', 'strong contrast'],
    target: 'lighting',
  },
  {
    id: 'fragment_light_night',
    label: '冷色夜景',
    category: '光照',
    description: '冷色环境光和月光',
    tags: ['cool color palette', 'moonlight', 'blue ambient light'],
    target: 'lighting',
  },
  {
    id: 'fragment_light_sunset',
    label: '暖色夕阳',
    category: '光照',
    description: '金色时刻和暖色轮廓光',
    tags: ['warm lighting', 'golden hour', 'sunset glow'],
    target: 'lighting',
  },
  {
    id: 'fragment_scene_rain',
    label: '雨天',
    category: '场景',
    description: '雨幕、湿地和潮湿氛围',
    tags: ['rain', 'wet ground', 'rainy atmosphere'],
    target: 'scene',
  },
  {
    id: 'fragment_scene_snow',
    label: '雪景',
    category: '场景',
    description: '飘雪和积雪环境',
    tags: ['snow', 'snowfall', 'snowy ground'],
    target: 'scene',
  },
  {
    id: 'fragment_negative_quality',
    label: '低质量排除',
    category: '负向-质量',
    description: '通用低质量与压缩瑕疵',
    tags: ['worst quality', 'low quality', 'blurry', 'jpeg artifacts'],
    target: 'negative_quality',
  },
  {
    id: 'fragment_negative_hands',
    label: '手部修正',
    category: '负向-身体',
    description: '常见手部结构问题',
    tags: ['bad hands', 'extra fingers', 'missing fingers', 'malformed hands'],
    target: 'negative_anatomy',
  },
  {
    id: 'fragment_negative_composition',
    label: '裁切修正',
    category: '负向-构图',
    description: '头部、四肢和画面裁切问题',
    tags: ['cropped head', 'cropped limbs', 'out of frame', 'bad composition'],
    target: 'negative_composition',
  },
  {
    id: 'fragment_negative_text',
    label: '文字水印排除',
    category: '负向-内容',
    description: '文本、签名、水印和边框',
    tags: ['text', 'watermark', 'signature', 'logo', 'border', 'frame'],
    target: 'negative_content',
  },
];

export function applyDrawPromptFragment(
  document: PromptDocumentV1,
  fragment: DrawPromptFragment,
): PromptDocumentV1 {
  if (fragment.target.startsWith('negative_')) {
    const negativeKind = fragment.target.replace(
      'negative_',
      '',
    ) as 'quality' | 'anatomy' | 'composition' | 'content';
    return updateNegativeBlock(document, negativeKind, (block) => ({
      ...block,
      tags: mergeTags(block.tags, fragment.tags),
      source: 'prompt_fragment',
    }));
  }
  return updateGlobalBlock(
    document,
    fragment.target as 'quality' | 'style' | 'camera' | 'lighting' | 'scene',
    (block) => ({
      ...block,
      tags: mergeTags(block.tags, fragment.tags),
      source: 'prompt_fragment',
    }),
  );
}
