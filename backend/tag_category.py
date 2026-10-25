"""Local dictionary and embedding fallback for drawing prompt tags.

Categories mirror the existing /api/prompt-agent/split response keys so the
public API stays stable: character/action/background/style/other.
"""
from __future__ import annotations

import math
import re
import threading

import config

CATEGORIES = ("character", "action", "background", "style", "other")
# The locally cached embedder is Chinese-oriented; keep the threshold high so
# low-confidence English matches fall through to the LLM layer instead of
# guessing. Set TAG_EMBED_MODEL to an English model for a more aggressive vector stage.
_MIN_SIMILARITY = 0.9
_EMBED_MODEL = config.TAG_EMBED_MODEL
_EMBED_CACHE_DIR = str(config.TAG_EMBED_CACHE_DIR)

# Whole normalized tags that should never be inferred from a contained word.
_EXACT_OVERRIDES = {
    "age difference": "other",
    "arcaea": "other",
    "arknights": "other",
    "azur lane": "other",
    "blue archive": "other",
    "danbooru": "other",
    "fate grand order": "other",
    "genshin": "other",
    "genshin impact": "other",
    "hetero": "other",
    "honkai": "other",
    "honkai impact 3rd": "other",
    "honkai star rail": "other",
    "lesbian": "other",
    "nikke": "other",
    "onee shota": "other",
    "original character": "other",
    "original characters": "other",
    "r18": "other",
    "uncensored": "other",
    "yuri": "other",
    "censored": "other",
    "orns": "other",
    "vibrator": "other",
    "remote control vibrator": "other",
    "mosaic censoring": "other",
    "year 2023 break": "other",
}

_TERMS: dict[str, tuple[str, ...]] = {
    "character": (
        # counts and person types
        "1girl", "1boy", "2girl", "2boy", "2girls", "2boys", "3girls", "3boys", "multiple girls",
        "multiple boys", "girls", "boys", "female", "male", "girl", "boy", "woman",
        "man", "solo", "duo", "trio", "threesome", "twosome", "group", "character",
        "characters", "female character", "anime girl", "anime boy", "loli", "shota",
        "bishounen", "idol", "maid", "nurse", "demon girl", "fox girl", "cat girl",
        "animal girl", "magical girl", "schoolgirl", "schoolboy",
        "oni", "demon", "angel", "vampire", "elf", "fairy", "kemonomimi",
        # project characters commonly seen in real prompt records
        "thea", "nekojira", "noshiro", "firefly", "lumine", "mudrock", "theresa",
        "castorice", "skirk", "albion", "argus", "la pluma", "columbina", "sandrone",
        "rita rossweisse",
        # body and appearance
        "hair", "hairstyle", "ahoge", "bangs", "braid", "ponytail", "twintails",
        "sidelocks", "forelock", "hairband", "hair ornament", "hair accessory",
        "hair flower", "hair bow", "eye", "eyes", "eyebrow", "eyelashes", "pupil",
        "pupils", "heterochromia", "face", "cheek", "cheeks", "nose", "mouth", "lips",
        "chin", "jaw", "ear", "ears", "pointy ears", "animal ears", "fox ears",
        "cat ears", "nekomimi", "horn", "horns", "demon horns", "tail", "demon tail",
        "fox tail", "wing", "wings", "demon wings", "feather", "feathers", "skin",
        "freckle", "freckles", "mole", "scar", "blush", "body", "figure", "breast",
        "breasts", "nipple", "nipples", "cleavage", "chest", "areola", "navel",
        "stomach", "waist", "hip", "hips", "thigh", "thighs", "leg", "legs", "knee",
        "feet", "foot", "toes", "sole", "soles", "hand", "hands", "arm", "arms",
        "shoulder", "shoulders", "collarbone", "neck", "back", "butt", "ass",
        "cameltoe", "pussy", "vagina", "penis", "cervix", "clitoris", "testicles",
        "abs", "muscle", "muscles", "skindentation", "piercing", "piercings",
        "clitoral", "clitoral rings", "rings", "ring", "cutout", "cutouts",
        # clothing and accessories
        "outfit", "outfits", "clothes", "clothing", "uniform", "school uniform",
        "maid outfit", "nurse outfit", "dress", "shirt", "blouse", "skirt", "pants",
        "jeans", "shorts", "leggings", "stockings", "pantyhose", "tights", "socks",
        "legwear", "thighhighs", "fishnets", "garter belt", "garter", "underwear",
        "panties", "bra", "brassiere", "lingerie", "babydoll", "negligee",
        "nightgown", "bikini", "swimsuit", "one piece", "bodysuit", "leotard",
        "latex", "see through clothes", "sheer clothes", "kimono", "qipao", "apron",
        "coat", "jacket", "sweater", "cardigan", "hoodie", "turtleneck", "glove",
        "gloves", "mittens", "boots", "boot", "shoes", "heel", "heels", "hat", "cap",
        "beret", "crown", "tiara", "ribbon", "bow", "hairband", "headband",
        "headphones", "earrings", "necklace", "choker", "collar", "tie", "necktie",
        "scarf", "muffler", "mask", "eyepatch", "glasses", "visor", "armor", "belt",
        "corset", "lace", "frill", "frills", "sleeve", "sleeves", "cuffs", "trim",
        "strap", "straps", "chain", "jewelry", "accessory", "accessories",
        "ornament", "ornaments", "decoration", "decorations", "costume", "costumes",
        "fashion", "see through", "barefoot", "pendant", "slender and tall",
        "aegyo sal", "halterneck", "criss cross halter", "three people",
        "halo", "black halo", "broken halo", "toned", "virtuosa",
    ),
    "action": (
        "pose", "poses", "posing", "standing", "standing up", "sitting", "sitting on",
        "lying", "lying down", "lying pose", "supine", "side lying", "prone",
        "kneeling", "squatting", "squat", "walking", "running", "jumping", "dancing",
        "fighting", "leaning", "leaning forward", "bending", "stretching", "crawling",
        "crouching", "looking", "looking at viewer", "looking away", "looking back",
        "looking at another", "staring", "glancing", "turning head", "smile",
        "smiling", "grinning", "laughing", "cry", "crying", "tears", "blushing",
        "expression", "facial expression", "detailed facial expression", "closed eyes",
        "closed mouth", "open mouth", "parted lips", "ahegao", "torogao", "focused",
        "intense", "embarrassed", "surprised", "angry", "sad", "holding",
        "holding hands", "holding another", "grabbing", "grabbing from behind",
        "touching", "caressing", "petting", "licking", "kissing", "hugging",
        "embracing", "handholding", "fondling", "masturbation", "masturbating",
        "handjob", "footjob", "blowjob", "fellatio", "cunnilingus", "oral",
        "oral sex", "sex", "sexual", "intercourse", "penetration", "vaginal", "anal",
        "cowgirl position", "reverse cowgirl position", "missionary position",
        "doggystyle", "from behind", "on top", "lying on", "after sex",
        "breastfeeding", "ejaculation", "orgasm", "cumming", "cum", "cum in",
        "cum on", "cum overflow", "spread legs", "spread", "legs apart",
        "legs spread", "crossed legs", "leg lift", "lifted", "carrying",
        "piggyback", "princess carry", "presenting", "presenting own pussy",
        "exposed", "pulled down", "pulled up", "shirt lift", "skirt lift",
        "hair flowing over", "tail raised", "against wall", "full nelson",
        "human stacking", "one hand", "hand on", "hand up", "hand in front",
        "hand on own", "pointing", "waving", "clapping", "throwing", "catching",
        "pulling", "pushing", "opening", "closing", "resting", "raising", "lowering",
        "winking", "saluting", "bowing", "bent over", "arched", "on back",
        "pussy juice", "pussy juice on fingers", "female masturbation",
        "vaginal object insertion", "unusual insertion", "object insertion",
        "male masturbation", "breast play", "penis inside vagina", "penis inside",
        "cum inside", "cum in pussy", "internal cumshot", "creampie",
        "pussy spread", "spread pussy", "legs spread wide",
        "feetjob", "paizuri", "saliva", "sweat", "facing viewer",
        "head tilt", "straddling", "trembling", "wet",
    ),
    "background": (
        "background", "backdrop", "simple background", "white background",
        "black background", "pure white background", "indoor", "outdoor", "scene",
        "scenes", "setting", "environment", "room", "bedroom", "bathroom", "kitchen",
        "classroom", "school", "living room", "dining room", "cafe", "bar",
        "restaurant", "office", "hallway", "corridor", "stair", "stairs",
        "staircase", "escalator", "elevator", "street", "alley", "city", "town",
        "village", "building", "buildings", "house", "home", "rooftop", "balcony",
        "porch", "veranda", "door", "window", "windows", "wall", "walls",
        "white walls", "floor", "ceiling", "curtain", "curtains", "white curtains",
        "bed", "couch", "sofa", "chair", "table", "desk", "bookshelf", "shelf",
        "bookshelves", "stage", "auditorium", "church", "temple", "shrine",
        "castle", "ruins", "tower", "cave", "forest", "woods", "tree", "trees",
        "garden", "park", "field", "meadow", "grass", "flower", "flowers",
        "flower field", "mountain", "hill", "cliff", "sea", "ocean", "beach",
        "shore", "river", "lake", "pond", "pool", "water", "waterfall", "rain",
        "raining", "snow", "snowing", "sky", "cloud", "clouds", "night", "day",
        "sunrise", "sunset", "dawn", "dusk", "moon", "stars", "star", "nebula",
        "galaxy", "planet", "space", "underwater", "aquarium", "greenhouse", "zoo",
        "farm", "countryside", "desert", "volcano", "island", "dock", "harbor",
        "ship", "boat", "train", "bus", "car", "vehicle", "bicycle", "market",
        "shop", "store", "supermarket", "library", "hospital", "clinic", "airport",
        "station", "platform", "factory", "warehouse", "battlefield", "dungeon",
        "sewer", "graveyard", "cemetery", "green screen", "blurry background",
        "colorful background", "gradient background", "city lights", "neon lights",
        "indoor setting", "indoor scene", "outdoor scene", "partially submerged",
        "carpet", "cherry blossoms", "indoors", "outdoors",
    ),
    "style": (
        "masterpiece", "best quality", "high quality", "amazing quality",
        "great quality", "good quality", "normal quality", "low quality",
        "worst quality", "very aesthetic", "aesthetic", "cute aesthetic",
        "elegant", "sensual", "sexy", "artistic", "elegant and sensual", "score",
        "quality", "anime", "manga", "manhwa", "anime style", "2d anime style",
        "anime art", "anime illustration", "anime coloring", "anime character design",
        "art", "art style", "illustration", "digital art",
        "sexy anime art", "character design", "original", "official art",
        "concept art", "painting", "oil painting", "watercolor",
        "watercolor tones", "sketch", "lineart", "line art", "clear lines",
        "coloring", "color", "colors", "vibrant colors", "gradient",
        "smooth gradients", "shading", "cel shading", "render", "rendering",
        "detailed", "high detail", "highly detailed", "intricate details",
        "intricate design", "realistic", "realistic details", "photoreal",
        "photorealistic", "photo", "photography", "cinematic",
        "cinematic composition", "cinematic lighting", "film", "noir", "retro",
        "vintage", "pixel art", "3d", "cgi", "wallpaper",
        "magic atmosphere", "atmosphere", "warm and cozy atmosphere",
        "soft white and pink tones", "symbolic ability", "symbolic power",
        "material growth", "highres", "absurdres", "high resolution", "resolution",
        "8k", "4k", "hd", "ultra detailed", "detailed texture", "refined design",
        "clean and simple", "soft focus effect", "focus effect", "bokeh",
        "lens flare", "depth of field", "motion blur", "film grain", "grain",
        "chromatic aberration", "bloom", "vignette", "filter", "soft lighting",
        "studio lighting", "gentle lighting", "dramatic lighting", "rim light",
        "backlighting", "neon lighting", "volumetric lighting", "glow", "shadows",
        "contrast", "brightness", "lighting", "light", "lights", "full body",
        "upper body", "lower body", "cowboy shot", "medium shot", "wide shot",
        "close up", "close-up", "from above", "from below", "pov", "first person",
        "first-person", "centered composition", "center composition",
        "symmetrical composition", "composition", "angle", "dutch angle", "shot",
        "style", "styles", "clean lines", "soft focus", "out of focus",
        "magical", "magical aura", "blurry",
        "foreshortening", "evocative",
    ),
    "other": (
        "nsfw", "explicit", "erotic", "nude", "naked", "nudity", "text",
        "watermark", "signature", "speech bubble", "multiple views",
        "multiple angles", "reference sheet", "comparison", "sample", "request",
        "commission", "artist", "no humans", "animal focus", "sex toy",
        "used condom", "condom", "condoms", "condom on nipples", "condom in mouth",
        "condom in ass", "condom left inside", "used condom in mouth",
        "used condom in clothes", "condom belt", "condom thigh strap",
        "condom in pussy", "condom on penis", "official alternate costume",
        "alternate costume", "magic item", "magic items", "originium",
        "oripathy lesion", "heart", "lora", "twitter username",
    ),
}

_CATEGORY_RANK = {category: index for index, category in enumerate(CATEGORIES)}
_RULES = tuple(
    sorted(
        ((term, category) for category, terms in _TERMS.items() for term in terms),
        key=lambda item: (-len(item[0]), _CATEGORY_RANK[item[1]]),
    )
)

# Representative tags used by the embedding fallback.
_PROTOTYPES = {
    "character": [
        "1girl",
        "long hair",
        "blue eyes",
        "school uniform",
        "black dress",
        "cat ears",
        "demon girl",
    ],
    "action": [
        "standing",
        "sitting",
        "smiling",
        "holding hands",
        "kissing",
        "running",
        "masturbation",
        "spread legs",
    ],
    "background": [
        "simple background",
        "bedroom",
        "outdoors",
        "blue sky",
        "city street",
        "forest",
        "night",
        "white background",
    ],
    "style": [
        "masterpiece",
        "best quality",
        "anime coloring",
        "very aesthetic",
        "cinematic lighting",
        "highly detailed",
        "photorealistic",
        "highres",
    ],
    "other": [
        "uncensored",
        "explicit",
        "multiple views",
        "watermark",
        "text",
        "request",
        "sex toy",
    ],
}

_WHITESPACE = re.compile(r"\s+")
_BRACKET_TEXT = re.compile(r"[\[\]()]")
_WEIGHT_SUFFIX = re.compile(r":\s*\d+(?:\.\d+)?\s*$")


def normalize_tag(tag: str) -> str:
    """Return a stable lower-case lookup key for a raw prompt tag."""
    key = str(tag or "").strip().lower().replace("_", " ").replace("-", " ")
    key = _BRACKET_TEXT.sub(" ", key)
    key = _WEIGHT_SUFFIX.sub("", key)
    return _WHITESPACE.sub(" ", key).strip()


def dictionary_category(tag: str) -> str | None:
    """Classify a tag with the local dictionary; return None when unknown."""
    raw = str(tag or "")
    if not any(char.isalnum() for char in raw):
        return "other"
    key = normalize_tag(tag)
    if not key:
        return None
    if "@" in key or len(key.split()) > 8:
        return "other"
    override = _EXACT_OVERRIDES.get(key)
    if override in CATEGORIES:
        return override
    for term, category in _RULES:
        if _contains_term(key, term):
            return category
    return None


def _contains_term(key: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in key
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", key))


def best_vector_category(
    vector: list[float],
    labeled_vectors: list[tuple[str, list[float]]],
    min_similarity: float = _MIN_SIMILARITY,
) -> str | None:
    """Return the category of the closest prototype vector above a threshold."""
    best_category: str | None = None
    best_score = -2.0
    for category, prototype in labeled_vectors:
        score = _cosine(vector, prototype)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category if best_score >= min_similarity else None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


_EMBED_LOCK = threading.Lock()
_VECTOR_DISABLED = False
_PROTOTYPE_VECTORS: list[tuple[str, list[float]]] | None = None
_EMBEDDER = None
_VECTOR_CACHE: dict[str, str | None] = {}


def vector_category(tag: str) -> str | None:
    """Embedding fallback for tags the dictionary cannot classify."""
    key = normalize_tag(tag)
    if not key:
        return None
    if key in _VECTOR_CACHE:
        return _VECTOR_CACHE[key]
    category = _vector_category_nocache(key)
    _VECTOR_CACHE[key] = category
    return category


def _vector_category_nocache(key: str) -> str | None:
    global _VECTOR_DISABLED, _PROTOTYPE_VECTORS, _EMBEDDER
    if _VECTOR_DISABLED:
        return None
    with _EMBED_LOCK:
        if _VECTOR_DISABLED:
            return None
        try:
            if _EMBEDDER is None:
                from fastembed import TextEmbedding

                _EMBEDDER = TextEmbedding(model_name=_EMBED_MODEL, cache_dir=_EMBED_CACHE_DIR)
            if _PROTOTYPE_VECTORS is None:
                samples = [
                    (category, prototype)
                    for category, prototypes in _PROTOTYPES.items()
                    for prototype in prototypes
                ]
                raw = list(_EMBEDDER.embed([text for _, text in samples]))
                _PROTOTYPE_VECTORS = [
                    (category, [float(value) for value in vector])
                    for (category, _), vector in zip(samples, raw)
                ]
            query = next(iter(_EMBEDDER.embed([key])))
            query_vector = [float(value) for value in query]
        except Exception:
            _VECTOR_DISABLED = True
            return None
    return best_vector_category(query_vector, _PROTOTYPE_VECTORS or [])
