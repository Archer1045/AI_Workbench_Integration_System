from __future__ import annotations

from collections import Counter

import preset_asset_pipeline as pipeline
import prompt_agent


explicit = [
    item
    for item in prompt_agent.POSE_PRESETS
    if pipeline._pose_has_explicit_clothing(item)
]
print("explicit_count", len(explicit))
print("explicit_categories", Counter(str(item.get("category") or "") for item in explicit))
for item in explicit:
    print(
        item.get("id"),
        "|",
        item.get("category"),
        "|",
        item.get("label"),
        "|",
        item.get("people"),
        "|",
        item.get("draw_prompt"),
    )
