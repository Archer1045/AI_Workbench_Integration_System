import { fetchRuntimeConfig, type RuntimeConfig } from '../api';

export const FALLBACK_RUNTIME_CONFIG: RuntimeConfig = {
  backend: {
    host: '127.0.0.1',
    port: 8500,
    api_base: '/api',
  },
  services: {
    ollama: { base_url: 'http://127.0.0.1:11434' },
    comfyui: { base_url: 'http://127.0.0.1:8188' },
  },
  draw: {
    default_model: 'chosenIrisesMix_v20Anima.safetensors',
    default_prompt:
      'uncensored, masterpiece, score 7, highres, absurdres, best quality, very aesthetic, anime coloring, 1girl, solo, long hair, blue eyes, school uniform, sailor collar, white shirt, pleated skirt, looking at viewer, smile, upper body, simple background, cherry blossoms',
    default_negative_prompt:
      'worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, signature, mosaic_censored, bar_censor, text_censor, censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship',
    default_width: 1080,
    default_height: 1920,
    default_steps: 18,
    default_cfg: 1,
    default_lora_strength_model: 0.8,
    default_lora_strength_clip: 0.8,
    group_count_min: 1,
    max_group_count: 20,
    max_total_count: 100,
    width_min: 256,
    width_max: 4096,
    height_min: 256,
    height_max: 4096,
    steps_min: 1,
    steps_max: 80,
    cfg_min: 0.5,
    cfg_max: 20,
    cfg_step: 0.5,
    lora_strength_min: 0,
    lora_strength_max: 1.5,
    lora_strength_step: 0.05,
    allowed_sizes: [
      [1080, 1920],
      [1920, 1080],
      [1024, 1024],
    ],
  },
  video: {
    default_frames: 121,
    default_fps: 24,
    default_width: 512,
    default_height: 512,
    default_steps: 20,
    default_cfg: 6,
    default_denoise: 1,
    default_lora_strength: 1,
    seed_min: 0,
    timeout_seconds: 7200,
    keyframe_max_bytes: 20 * 1024 * 1024,
    script_max_length: 4000,
    steps_min: 1,
    steps_max: 100,
    cfg_min: 0.5,
    cfg_max: 20,
    cfg_step: 0.5,
    denoise_min: 0,
    denoise_max: 1,
    denoise_step: 0.05,
    lora_strength_min: 0,
    lora_strength_max: 1.5,
    lora_strength_step: 0.05,
    allowed_frames: [33, 81, 121],
    allowed_sizes: [
      [512, 512],
      [832, 480],
      [480, 832],
    ],
  },
  train: {
    default_caption_threshold: 0.35,
    default_caption_batch_size: 4,
    default_skip_existing: true,
    default_remove_underscore: true,
    default_auto_convert: true,
    default_resolution: 1024,
    default_repeats: 5,
    default_batch_size: 1,
    default_network_dim: 32,
    default_network_alpha: 16,
    default_learning_rate: 0.0002,
    default_epochs: 4,
    default_save_every: 1,
    default_max_steps: 0,
    caption_threshold_min: 0.1,
    caption_threshold_max: 0.9,
    caption_threshold_step: 0.05,
    caption_batch_min: 1,
    caption_batch_max: 16,
    resolution_min: 512,
    resolution_max: 2048,
    resolution_step: 64,
    repeats_min: 1,
    repeats_max: 50,
    batch_size_min: 1,
    batch_size_max: 8,
    network_dim_min: 4,
    network_dim_max: 128,
    network_alpha_min: 4,
    network_alpha_max: 128,
    learning_rate_min: 0.0000001,
    learning_rate_max: 0.01,
    learning_rate_step: 0.00005,
    epochs_min: 1,
    epochs_max: 200,
    save_every_min: 1,
    save_every_max: 50,
    max_steps_min: 0,
    max_steps_max: 100000,
    merge_ratio_default: 1,
    merge_ratio_min: 0.1,
    merge_ratio_max: 2,
    merge_ratio_step: 0.1,
  },
  compare: {
    default_width: 1080,
    default_height: 1920,
    default_steps: 18,
    default_cfg: 1,
    width_min: 256,
    width_max: 4096,
    height_min: 256,
    height_max: 4096,
    steps_min: 1,
    steps_max: 80,
    cfg_min: 0.5,
    cfg_max: 20,
    cfg_step: 0.5,
  },
  preset_composition: {
    max_items: 12,
  },
  preset_assets: {
    root: '',
    template_version: 'thumbnail_template_v5',
    upload_max_bytes: 20 * 1024 * 1024,
    upload_max_pixels: 20_000_000,
    candidate_min: 1,
    candidate_max: 4,
    candidate_default: 2,
    batch_max_items: 50,
    cpu_concurrency: 2,
    ai_concurrency: 1,
    preview_format: 'WEBP',
    preview_quality: 90,
    targets: {
      pose: {
        generation_size: [832, 1216],
        output_size: [512, 768],
        format: 'PNG',
        quality: 95,
      },
      clothing: {
        generation_size: [540, 960],
        output_size: [270, 480],
        format: 'WEBP',
        quality: 90,
      },
      scene: {
        generation_size: [1024, 576],
        output_size: [480, 270],
        format: 'WEBP',
        quality: 90,
      },
      body: {
        generation_size: [540, 960],
        output_size: [270, 480],
        format: 'WEBP',
        quality: 90,
      },
      expansion: {
        generation_size: [768, 768],
        output_size: [384, 384],
        format: 'WEBP',
        quality: 90,
      },
      toy: {
        generation_size: [768, 768],
        output_size: [384, 384],
        format: 'WEBP',
        quality: 90,
      },
      character: {
        generation_size: [540, 960],
        output_size: [270, 480],
        format: 'WEBP',
        quality: 90,
      },
    },
    defaults: {
      version: 1,
      model: 'chosenIrisesMix_v20Anima.safetensors',
      loras: [],
      lora_strengths: {},
      lora_strength_model: 0.8,
      lora_strength_clip: 0.8,
      steps: 18,
      cfg: 1,
      seed_strategy: 'random',
      seed: null,
      crop_mode: 'cover',
      focus_x: 0.5,
      focus_y: 0.5,
      zoom: 1,
      candidate_count: 2,
      style_positive:
        'uncensored, masterpiece, score 7, highres, absurdres, best quality, very aesthetic, anime coloring',
      style_negative:
        'worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, lowres, signature, mosaic_censored, bar_censor, text_censor, censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship',
      user_positive: '',
      user_negative: '',
    },
  },
  settings: {
    health_interval_default: 15,
    health_interval_min: 5,
    health_interval_max: 3600,
    max_failures_default: 3,
    max_failures_min: 1,
    max_failures_max: 20,
    auto_shutdown_delay_default: 60,
    auto_shutdown_delay_min: 10,
    auto_shutdown_delay_max: 600,
    data_retention_default: 0,
    data_retention_min: 0,
    data_retention_max: 3650,
  },
  query: {
    page_min: 1,
    records_page_default: 1,
    records_page_size_default: 10,
    records_page_size_max: 100,
    prompt_stats_top_default: 20,
    prompt_stats_top_max: 500,
    image_library_page_default: 1,
    image_library_page_size_default: 20,
    image_library_page_size_max: 100,
    prompt_set_page_default: 1,
    prompt_set_page_size_default: 10,
    prompt_set_page_size_max: 100,
    video_keyframes_limit_default: 200,
    video_keyframes_limit_max: 1000,
    video_scripts_limit_default: 30,
    video_scripts_limit_max: 200,
    video_library_limit_default: 100,
    video_library_limit_max: 500,
    train_history_limit_default: 100,
    train_history_limit_max: 500,
    system_tasks_limit_default: 50,
    system_tasks_limit_max: 200,
  },
  backup: {
    keep_count: 10,
  },
};

let currentConfig: RuntimeConfig = FALLBACK_RUNTIME_CONFIG;
let loadPromise: Promise<RuntimeConfig> | null = null;

function mergeRuntimeConfig(value: Partial<RuntimeConfig>): RuntimeConfig {
  return {
    backend: { ...FALLBACK_RUNTIME_CONFIG.backend, ...value.backend },
    services: {
      ollama: { ...FALLBACK_RUNTIME_CONFIG.services.ollama, ...value.services?.ollama },
      comfyui: { ...FALLBACK_RUNTIME_CONFIG.services.comfyui, ...value.services?.comfyui },
    },
    draw: { ...FALLBACK_RUNTIME_CONFIG.draw, ...value.draw },
    video: {
      ...FALLBACK_RUNTIME_CONFIG.video,
      ...value.video,
      allowed_frames:
        Array.isArray(value.video?.allowed_frames) && value.video.allowed_frames.length > 0
          ? value.video.allowed_frames
          : FALLBACK_RUNTIME_CONFIG.video.allowed_frames,
      allowed_sizes:
        Array.isArray(value.video?.allowed_sizes) && value.video.allowed_sizes.length > 0
          ? value.video.allowed_sizes
          : FALLBACK_RUNTIME_CONFIG.video.allowed_sizes,
    },
    train: { ...FALLBACK_RUNTIME_CONFIG.train, ...value.train },
    compare: { ...FALLBACK_RUNTIME_CONFIG.compare, ...value.compare },
    preset_composition: {
      ...FALLBACK_RUNTIME_CONFIG.preset_composition,
      ...value.preset_composition,
    },
    preset_assets: {
      ...FALLBACK_RUNTIME_CONFIG.preset_assets,
      ...value.preset_assets,
      targets: {
        ...FALLBACK_RUNTIME_CONFIG.preset_assets.targets,
        ...value.preset_assets?.targets,
      },
      defaults: {
        ...FALLBACK_RUNTIME_CONFIG.preset_assets.defaults,
        ...value.preset_assets?.defaults,
      },
    },
    settings: { ...FALLBACK_RUNTIME_CONFIG.settings, ...value.settings },
    query: { ...FALLBACK_RUNTIME_CONFIG.query, ...value.query },
    backup: { ...FALLBACK_RUNTIME_CONFIG.backup, ...value.backup },
  };
}

export function getRuntimeConfig(): RuntimeConfig {
  return currentConfig;
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  if (loadPromise) return loadPromise;
  loadPromise = fetchRuntimeConfig()
    .then((value) => {
      currentConfig = mergeRuntimeConfig(value);
      return currentConfig;
    })
    .catch(() => currentConfig);
  return loadPromise;
}
