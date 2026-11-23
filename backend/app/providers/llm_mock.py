"""Deterministic mock LLM.

This is not a stub that returns canned fixtures - it reads the actual story text
and produces a real story breakdown, cast, scene plan, dialogue and camera work
using text analysis. That is what lets the app be demonstrable end-to-end with
no API key, and it means the pipeline bugs you hit in mock mode are real bugs.

Output is JSON-stringified and fed back through ``BaseLLM.complete_json``, so
schema validation and the one-shot JSON repair retry are exercised here too.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from .base import BaseLLM
from ..styles.presets import get_style_preset

# --------------------------------------------------------------------------- #
# Lexicons
# --------------------------------------------------------------------------- #

STOPWORDS = {
    "the", "and", "but", "for", "nor", "yet", "so", "with", "from", "into", "onto",
    "over", "under", "about", "after", "before", "while", "when", "then", "than",
    "that", "this", "these", "those", "there", "their", "them", "they", "she",
    "he", "his", "her", "its", "it", "was", "were", "been", "being", "are", "is",
    "am", "be", "had", "has", "have", "did", "does", "do", "will", "would",
    "could", "should", "can", "may", "might", "must", "not", "no", "yes", "all",
    "any", "some", "one", "two", "three", "very", "just", "only", "also", "even",
    "still", "again", "once", "now", "later", "suddenly", "finally", "meanwhile",
    "however", "because", "as", "at", "by", "in", "of", "on", "to", "up", "down",
    "out", "off", "a", "an", "i", "you", "we", "us", "my", "your", "our", "what",
    "who", "why", "how", "where", "which", "if", "or", "day", "night", "time",
    "said", "says", "told", "asked", "replied", "looked", "went", "came",
}

GENRE_KEYWORDS: dict[str, list[str]] = {
    "science fiction": ["robot", "space", "alien", "starship", "orbit", "cyber", "future", "mars", "android", "ai", "hologram", "colony"],
    "fantasy": ["dragon", "magic", "wizard", "kingdom", "sword", "spell", "elf", "prophecy", "rune", "sorcer"],
    "mystery": ["detective", "clue", "murder", "mystery", "case", "investigat", "missing", "suspect", "alibi"],
    "horror": ["ghost", "haunted", "blood", "scream", "demon", "corpse", "curse", "grave"],
    "romance": ["love", "kiss", "heart", "romance", "wedding", "beloved", "crush"],
    "slice of life": ["school", "classroom", "home", "friend", "family", "shop", "kitchen", "neighbour", "neighbor"],
    "action": ["fight", "battle", "chase", "explosion", "punch", "war", "attack", "blade", "gunfire"],
    "adventure": ["journey", "quest", "map", "treasure", "island", "mountain", "expedition", "voyage"],
}

MOOD_KEYWORDS: dict[str, list[str]] = {
    "tense": ["fight", "danger", "chase", "panic", "gun", "blade", "threat", "trap"],
    "joyful": ["laugh", "smile", "celebrat", "happy", "win", "feast", "dance"],
    "somber": ["cry", "funeral", "loss", "alone", "sad", "rain", "grave", "goodbye"],
    "mysterious": ["secret", "whisper", "unknown", "hidden", "dark", "shadow", "letter"],
    "hopeful": ["hope", "dawn", "promise", "begin", "new", "sunrise", "light"],
    "angry": ["angry", "rage", "shout", "furious", "betray"],
}

EMOTION_LEXICON: dict[str, list[str]] = {
    "joy": ["smile", "laugh", "happy", "joy", "delight", "cheer", "grin", "celebrat", "excited", "warm", "hug"],
    "sadness": ["cry", "tear", "sad", "grief", "loss", "lonely", "alone", "mourn", "sigh", "goodbye"],
    "anger": ["angry", "rage", "furious", "shout", "yell", "fist", "glare", "snarl", "betray"],
    "fear": ["afraid", "fear", "terror", "tremble", "panic", "danger", "threat", "hide", "flee"],
    "surprise": ["sudden", "gasp", "shock", "surprise", "unexpected", "startled", "reveal", "appear"],
    "disgust": ["disgust", "rot", "foul", "sneer", "revolt", "bitter", "stink"],
    "determination": ["resolve", "determin", "decide", "must", "stand", "promise", "protect", "refuse", "swore"],
    "love": ["love", "dear", "tender", "embrace", "kiss", "care", "gentle"],
    "confusion": ["confus", "puzzle", "wonder", "unsure", "strange", "why", "doubt"],
}

EXPRESSIONS: dict[str, str] = {
    "joy": "bright open eyes, wide genuine smile, raised cheeks",
    "sadness": "downcast eyes, slight frown, lowered shoulders",
    "anger": "furrowed brows, narrowed eyes, clenched jaw",
    "fear": "wide eyes, raised brows, tense parted lips",
    "surprise": "eyes wide open, brows high, mouth slightly agape",
    "disgust": "wrinkled nose, narrowed eyes, mouth pulled to one side",
    "determination": "steady gaze, set jaw, brows drawn together",
    "love": "soft gaze, gentle smile, relaxed brows",
    "confusion": "one brow raised, head tilted, uncertain frown",
    "neutral": "relaxed expression, calm eyes",
}

SETTING_KEYWORDS: dict[str, list[str]] = {
    "a narrow city street": ["street", "city", "road", "alley", "traffic", "crossing"],
    "a quiet room": ["room", "bedroom", "home", "house", "kitchen", "apartment"],
    "a school corridor": ["school", "classroom", "campus", "college", "locker"],
    "a dense forest": ["forest", "tree", "woods", "jungle", "grove"],
    "a starship deck": ["ship", "space", "station", "cockpit", "airlock", "orbit"],
    "a busy market": ["market", "bazaar", "shop", "stall", "town", "square"],
    "a rooftop at dusk": ["roof", "terrace", "ledge", "skyline"],
    "an old temple": ["temple", "shrine", "church", "mosque", "monastery", "altar"],
    "a riverbank": ["river", "bank", "shore", "bridge", "water"],
    "an empty station platform": ["station", "platform", "train", "tracks"],
}

TIME_WORDS: dict[str, list[str]] = {
    "dawn": ["dawn", "sunrise", "morning", "first light"],
    "day": ["day", "noon", "afternoon", "midday"],
    "dusk": ["dusk", "sunset", "evening", "twilight"],
    "night": ["night", "midnight", "dark", "moon", "stars"],
}

PERIOD_WORDS: dict[str, list[str]] = {
    "a distant future": ["space", "robot", "starship", "colony", "android", "cyber", "orbit"],
    "the distant past": ["kingdom", "sword", "village", "prophecy", "emperor", "castle"],
    "present day": [],
}

REACTIVE_LINES: dict[str, list[str]] = {
    "joy": ["We actually did it.", "I can't stop smiling.", "This is the best day."],
    "sadness": ["I thought it would be different.", "There's nothing left here.", "Don't go. Not yet."],
    "anger": ["Enough. This ends now.", "You had no right.", "Say that again."],
    "fear": ["Did you hear that?", "Stay close to me.", "We shouldn't be here."],
    "surprise": ["Wait - what is that?", "That can't be right.", "How long has that been there?"],
    "disgust": ["That's revolting.", "I'm not touching that.", "Get it away from me."],
    "determination": ["I'm not running. Not this time.", "Then we do it my way.", "Hold the line."],
    "love": ["I'm glad you're here.", "You don't have to do this alone.", "Stay. Just for a minute."],
    "confusion": ["That doesn't make any sense.", "Something's wrong here.", "I've seen this before... I think."],
    "neutral": ["Let's keep moving.", "We should check the next one.", "Give me a second."],
}

SFX_BY_EMOTION = {
    "anger": ["KRAK", "THUD", "SLAM"],
    "fear": ["CREAK", "THMP", "hiss"],
    "surprise": ["GASP", "WHAM", "KLANG"],
    "joy": ["heh", "clap", "ding"],
}

SHOT_CYCLE = ["medium", "medium_close", "over_the_shoulder", "low_angle", "high_angle", "wide"]

LENS_BY_SHOT = {
    "establishing_wide": "18mm wide",
    "wide": "24mm",
    "medium": "35mm",
    "medium_close": "50mm",
    "close_up": "85mm portrait",
    "extreme_close_up": "100mm macro",
    "over_the_shoulder": "50mm",
    "low_angle": "24mm low",
    "high_angle": "35mm high",
    "bird_eye": "20mm overhead",
    "dutch_angle": "35mm tilted",
}


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'\-])", text)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences or [text]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]+", text)


def content_words(text: str) -> list[str]:
    return [w for w in tokenize(text) if w.lower() not in STOPWORDS and len(w) > 3]


def keyword_hits(text: str, lexicon: dict[str, list[str]]) -> dict[str, int]:
    low = text.lower()
    return {key: sum(low.count(k) for k in keys) for key, keys in lexicon.items()}


def best_key(text: str, lexicon: dict[str, list[str]], default: str) -> str:
    hits = keyword_hits(text, lexicon)
    best = max(hits.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else default


def clean_character_name(name: str | None) -> str:
    """Normalise a name from prose or a user reference, stripping possessives and junk."""
    if name is None:
        return ""
    cleaned = name.strip().strip("\"'` ")
    cleaned = re.sub(r"\s+'s\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b([A-Za-z]+)'s\b", r"\1", cleaned, flags=re.I)
    cleaned = re.sub(r"[\.,;:!?]+$", "", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


LOCATION_WORDS = {
    "town", "city", "village", "river", "riverbank", "street", "market", "bank",
    "forest", "hill", "station", "platform", "square", "harbor", "bridge", "alley",
    "garden", "tower", "temple", "road", "district", "lane", "field", "bay",
    "port", "camp", "gate", "plain", "cliff",
}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"}
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
COMMON_SENTENCE_WORDS = {"the", "in", "at", "on", "near", "from", "for", "with", "when",
                         "then", "after", "before", "but", "and", "however", "tonight", "yesterday"}
ACTION_VERBS = {
    "walked", "climbed", "held", "hold", "found", "finds", "stood", "waited", "waits",
    "watched", "looked", "looks", "turned", "opened", "opens", "carried", "carries",
    "whispered", "whispers", "said", "says", "asked", "asks", "replied", "replies",
    "called", "calls", "listened", "listens", "remembered", "remembers", "held",
    "ran", "ran", "ran", "moved", "moves", "left", "returned", "returns",
}


def _is_location_phrase(sentence: str, match_start: int, phrase: str) -> bool:
    context = sentence[max(0, match_start - 60):match_start].lower()
    if re.search(r"\b(?:in|at|near|by|of|from|inside|outside|beside)\s+(?:the\s+)?(?:a\s+|an\s+)?(?:.*\b)?(?:town|city|village|river|street|market|bank|forest|hill|station|platform|square|harbor|bridge|gardens?|tower|temple|district|road|alley|bay|field|gate)\b", context, flags=re.I):
        return True
    phrase_l = phrase.lower()
    return len(phrase.split()) > 1 and any(word in LOCATION_WORDS for word in phrase_l.split())


def extract_names(text: str, exclude: set[str] | None = None) -> list[str]:
    """Keep only character-like names and ignore locations, sentence-initial junk, and dates."""
    exclude_lower = {clean_character_name(e).lower() for e in (exclude or set()) if clean_character_name(e)}
    counts: dict[str, float] = {}

    for sentence in split_sentences(text):
        for match in re.finditer(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\b", sentence):
            name = clean_character_name(match.group(1))
            if not name:
                continue
            if any(name.lower().split()[-1] in {"the", "a", "an"} for _ in [0]):
                continue

            low = name.lower()
            if low in STOPWORDS or low in exclude_lower:
                continue
            if low in MONTHS or low in WEEKDAYS:
                continue
            if any(word.lower() in COMMON_SENTENCE_WORDS for word in name.split()[:1]):
                continue
            if _is_location_phrase(sentence, match.start(), name):
                continue

            context = sentence[max(0, match.start() - 40):match.end() + 50].lower()
            direct_speech = bool(re.search(rf"(?:^|\s){re.escape(low)}\s*:\s*\"|(?:said|asked|replied|whispered|murmured|called)\s+{re.escape(low)}\b|{re.escape(low)}\s+(?:said|asked|replied|whispered|murmured|called)\b", context))
            action_subject = bool(re.search(rf"\b{re.escape(low)}\s+(?:walked|climbed|held|held|found|finds|stood|waited|waits|watched|looked|looks|turned|opened|opens|carried|carries|whispered|whispers|said|says|asked|asks|replied|replies|called|calls|listened|listens|remembered|remembers|moved|moves|left|returned|returns)\b", context, flags=re.I))
            if not (direct_speech or action_subject):
                continue

            counts[name] = counts.get(name, 0.0) + (3.0 if direct_speech else 1.5)

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    seen: set[str] = set()
    names: list[str] = []
    for name, score in ranked:
        if score < 1.0:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= 6:
            break
    return names


def distribute(total: int, buckets: int) -> list[int]:
    """Split ``total`` panels across ``buckets`` scenes, each getting at least one."""
    buckets = max(1, min(buckets, total))
    base, rem = divmod(total, buckets)
    counts = [base + (1 if i < rem else 0) for i in range(buckets)]
    return [c for c in counts if c > 0]


def clean_clause(text: str) -> str:
    clause = text.strip().rstrip(".!?")
    clause = re.sub(r"^(and|but|then|so|yet|however|meanwhile|suddenly|finally)\s+", "", clause, flags=re.I)
    return clause[:120]


def short_subject(text: str, fallback: str = "they") -> str:
    words = content_words(text)
    return words[0].lower() if words else fallback


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #


class MockLLM(BaseLLM):
    name = "mock"

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._last: dict[str, Any] = {}
        self._last_call: tuple[str, dict[str, Any]] | None = None

    # BaseLLM hook ---------------------------------------------------------
    def _raw_for_task(self, task: str, payload: dict[str, Any], system: str, user: str) -> str:
        self._last_call = (task, payload)
        builder = getattr(self, f"_build_{task}", None)
        if builder is None:
            self._last = {"error": f"mock provider has no builder for task '{task}'"}
        else:
            self._last = builder(payload or {})
        return json.dumps(self._last)

    def _generate(self, system: str, user: str) -> str:
        # The one-shot repair retry lands here. Re-run the task's own builder, so
        # the mock behaves like a model that can correct itself - while a builder
        # that genuinely produces invalid output still fails after the retry.
        if self._last_call is not None:
            task, payload = self._last_call
            return self._raw_for_task(task, payload, system, user)
        return json.dumps(self._last)

    def _rng(self, *parts: Any) -> random.Random:
        key = "|".join(str(p) for p in (self._seed, *parts))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return random.Random(int(digest, 16))

    # -- tasks -------------------------------------------------------------
    def _build_story_understanding(self, payload: dict[str, Any]) -> dict[str, Any]:
        story = payload.get("story_text", "")
        title = payload.get("title") or "Untitled Comic"
        panel_count = int(payload.get("panel_count", 8))
        user_chars = payload.get("user_characters") or []

        sentences = split_sentences(story)
        genre = best_key(story, GENRE_KEYWORDS, "drama")
        mood = best_key(story, MOOD_KEYWORDS, "neutral")
        loc_name = None
        for match in re.finditer(r"\b(?:in|at|near|by|of|from)\s+(?:the\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b", story):
            candidate = clean_character_name(match.group(1))
            if not candidate:
                continue
            if candidate.lower() in {"the", "a", "an"}:
                continue
            if any(part.lower() in LOCATION_WORDS for part in candidate.split()):
                continue
            if len(candidate.split()) > 1:
                loc_name = candidate
                break
        setting = loc_name or best_key(story, SETTING_KEYWORDS, "an unnamed place")
        time_of_day = best_key(story, TIME_WORDS, "day")
        period = "present day"
        for candidate, words in PERIOD_WORDS.items():
            if words and any(w in story.lower() for w in words):
                period = candidate
                break

        exclude = {c["name"] for c in user_chars if c.get("name")}
        extracted = extract_names(story, exclude=exclude)

        characters: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        if user_chars:
            for ref in user_chars:
                name = clean_character_name(ref.get("name") or "")
                if not name:
                    continue
                key = name.lower()
                if key in seen_names:
                    continue
                seen_names.add(key)
                characters.append(
                    {
                        "name": name,
                        "role": "protagonist" if not characters else "supporting",
                        "appearance": ref.get("description") or f"{name}, as shown in the reference image",
                        "personality": "defined by the story",
                        "importance": 5 if not characters else 4,
                    }
                )
        else:
            for i, name in enumerate(extracted):
                clean = clean_character_name(name)
                if not clean or clean.lower() in seen_names:
                    continue
                seen_names.add(clean.lower())
                characters.append(
                    {
                        "name": clean,
                        "role": "protagonist" if not characters else "supporting",
                        "appearance": f"{clean}, described but not pictured",
                        "personality": "determined, guarded",
                        "importance": 5 if not characters else max(2, 4 - i),
                    }
                )
        if not characters:
            characters.append(
                {
                    "name": "the narrator",
                    "role": "protagonist",
                    "appearance": "an ordinary person in ordinary clothes",
                    "personality": "observant",
                    "importance": 3,
                }
            )
        characters = characters[:5]

        logline = clean_clause(sentences[0]) if sentences else title
        scene_count = max(2, min(len(sentences) // 2 or 2, 6))
        scene_count = max(2, min(scene_count, max(2, panel_count // 2)))
        story_words = len(story.split())
        recommended_panel_count = max(2, min(24, max(len(sentences), (story_words + 34) // 35)))

        themes = [w for w in content_words(story)][:5]
        themes = list(dict.fromkeys(themes)) or ["memory", "choice"]

        return {
            "title": title,
            "logline": logline,
            "genre": genre,
            "tone": mood,
            "setting": setting,
            "time_period": period,
            "themes": themes[:4],
            "characters": characters,
            "scene_count": scene_count,
            "recommended_panel_count": recommended_panel_count,
            "narrative_arc": [
                f"Setup: {clean_clause(sentences[0]) if sentences else 'we meet the cast'}",
                f"Complication: {clean_clause(sentences[len(sentences) // 2]) if sentences else 'something goes wrong'}",
                f"Resolution: {clean_clause(sentences[-1]) if sentences else 'the dust settles'}",
            ],
        }

    def _build_character_sheet(self, payload: dict[str, Any]) -> dict[str, Any]:
        drafts = payload.get("characters") or []
        analysis = payload.get("story_analysis") or {}
        style = payload.get("style", "manga")
        preset = get_style_preset(style)
        palette = preset.palette

        sheets: list[dict[str, Any]] = []
        for draft in drafts:
            name = draft.get("name") or "Unnamed"
            rng = self._rng("sheet", name)
            skin = rng.choice(["warm tan", "fair", "deep brown", "olive", "light brown"])
            hair = rng.choice(["short black hair", "shoulder-length dark brown hair", "cropped auburn hair", "long tied-back hair", "silver-streaked hair"])
            eyes = rng.choice(["dark brown eyes", "grey eyes", "deep green eyes", "amber eyes"])
            build = rng.choice(["tall and lean", "average height, wiry", "short and solid", "broad-shouldered"])
            outfit = rng.choice(
                [
                    "weathered dark jacket over a plain shirt, worn trousers",
                    "simple hooded cloak with a leather belt and pouch",
                    "school uniform with a loosened tie and scuffed shoes",
                    "technical flight suit with rolled sleeves and tool straps",
                    "plain work clothes, sleeves rolled, canvas satchel",
                ]
            )
            feature_pool = [
                "small scar above the left eyebrow",
                "always wears one glove",
                "silver ring on the right thumb",
                "cracked lens on a pendant",
                "distinctive streak in the hair",
                "freckles across the nose",
                "notched left ear",
                "ink stain on the right hand",
            ]
            features = rng.sample(feature_pool, k=3)
            sheets.append(
                {
                    "name": name,
                    "role": draft.get("role", "supporting"),
                    "appearance": (
                        f"{build}, {skin} skin, {hair}, {eyes}. "
                        f"{draft.get('appearance') or 'Design based on the story description.'}"
                    ),
                    "outfit": outfit,
                    "personality": draft.get("personality") or "reserved, quick to act",
                    "distinguishing_features": features,
                    "palette": palette[:4],
                    "signature_props": [rng.choice(["canvas satchel", "worn notebook", "pocket knife", "brass compass", "cracked phone"])],
                }
            )
        return {"characters": sheets, "_style": preset.id, "_genre": analysis.get("genre", "drama")}

    def _build_scene_planning(self, payload: dict[str, Any]) -> dict[str, Any]:
        story = payload.get("story_text", "")
        panel_count = int(payload.get("panel_count", 8))
        analysis = payload.get("story_analysis") or {}
        # the node hands over a list of names; accept drafts too so both shapes work
        characters: list[str] = []
        seen: set[str] = set()
        for item in payload.get("characters") or []:
            name = ""
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict) and item.get("name"):
                name = str(item["name"])
            cleaned = clean_character_name(name)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            characters.append(cleaned)
        characters = characters or ["the narrator"]

        sentences = split_sentences(story)
        scene_count = int(analysis.get("scene_count") or max(2, min(4, panel_count // 2)))
        scene_count = max(1, min(scene_count, panel_count))
        per_scene = distribute(panel_count, scene_count)

        # chunk the story sentences across scenes
        chunks: list[list[str]] = []
        if sentences:
            size = max(1, len(sentences) // scene_count)
            for i in range(scene_count):
                start = i * size
                end = len(sentences) if i == scene_count - 1 else start + size
                chunk = sentences[start:end]
                chunks.append(chunk or [sentences[min(start, len(sentences) - 1)]])
        else:
            chunks = [["The story begins."] for _ in range(scene_count)]

        scenes: list[dict[str, Any]] = []
        for i, count in enumerate(per_scene):
            chunk = chunks[i] if i < len(chunks) else chunks[-1]
            text = " ".join(chunk)
            mood = best_key(text, MOOD_KEYWORDS, analysis.get("tone", "neutral"))
            setting = best_key(text, SETTING_KEYWORDS, analysis.get("setting") or "an unnamed place")
            tod = best_key(text, TIME_WORDS, "day")
            title_words = content_words(text)[:3] or ["scene"]
            beats = self._beats_from_chunk(chunk, count, setting)
            scenes.append(
                {
                    "scene_id": f"s{i + 1}",
                    "index": i + 1,
                    "title": " ".join(w.capitalize() for w in title_words),
                    "summary": clean_clause(chunk[0]) if chunk else f"Scene {i + 1}",
                    "setting": setting,
                    "time_of_day": tod,
                    "characters": characters,
                    "action": clean_clause(text),
                    "mood": mood,
                    "beats": beats,
                }
            )
        return {"scenes": scenes, "_panel_count": sum(len(s["beats"]) for s in scenes)}

    def _beats_from_chunk(self, chunk: list[str], count: int, setting: str) -> list[str]:
        beats: list[str] = []
        for sentence in chunk:
            beats.append(clean_clause(sentence))
        while len(beats) < count:
            i = len(beats)
            beats.append(
                f"beat {i + 1}: the group reacts and presses on through {setting}"
            )
        if len(beats) > count:
            # merge the tail so the beat count matches the panel count exactly
            head = beats[: count - 1]
            tail = " ".join(beats[count - 1 :])
            beats = head + [clean_clause(tail)]
        return beats

    def _build_emotion_detection(self, payload: dict[str, Any]) -> dict[str, Any]:
        beats = payload.get("beats") or []
        out: list[dict[str, Any]] = []
        for beat in beats:
            action = beat.get("action", "")
            scene_mood = beat.get("scene_mood", "neutral")
            hits = keyword_hits(action, EMOTION_LEXICON)
            best = max(hits.items(), key=lambda kv: kv[1])
            if best[1] > 0:
                emotion = best[0]
            else:
                emotion = {
                    "tense": "fear",
                    "joyful": "joy",
                    "somber": "sadness",
                    "mysterious": "confusion",
                    "hopeful": "determination",
                    "angry": "anger",
                }.get(scene_mood, "neutral")
            rng = self._rng("emotion", beat.get("panel_id", ""), action)
            intensity = 0.85 if best[1] > 1 else (0.65 if best[1] == 1 else 0.45)
            if emotion in ("joy", "anger", "fear"):
                intensity = min(1.0, intensity + 0.1)
            out.append(
                {
                    "panel_id": beat["panel_id"],
                    "emotion": emotion,
                    "intensity": round(intensity + rng.uniform(-0.05, 0.05), 2),
                    "expression": EXPRESSIONS.get(emotion, EXPRESSIONS["neutral"]),
                }
            )
        return {"beats": out}

    def _build_dialogue_generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        panels = payload.get("panels") or []
        story_text = payload.get("story_text") or ""
        used_texts: set[str] = set()

        story_lines = []
        for match in re.finditer(r'"([^"\\]{1,120})"', story_text):
            text = match.group(1).strip()
            if not text:
                continue
            clean = clean_clause(text)
            if clean and clean.lower() not in {line.lower() for line in story_lines}:
                story_lines.append(clean)

        fallback_lines = [
            "Stay with me.",
            "We should keep moving.",
            "Not this time.",
            "Hold the line.",
            "Keep watching.",
            "I can still hear it.",
        ]

        out: list[dict[str, Any]] = []
        for panel in panels:
            panel_id = panel.get("panel_id", "")
            action = panel.get("action", "")
            emotion = panel.get("emotion", "neutral")
            speakers = [c for c in (panel.get("characters") or []) if c]
            rng = self._rng("dialogue", panel_id, action)

            lines: list[dict[str, Any]] = []
            kind = "speech"
            if emotion == "anger":
                kind = "shout"
            elif emotion in ("fear", "sadness"):
                kind = "whisper"
            elif emotion == "confusion" and rng.random() < 0.4:
                kind = "thought"

            available = [text for text in story_lines if text.lower() not in used_texts]
            if not available:
                available = [text for text in fallback_lines if text.lower() not in used_texts]
            if not panel.get("silent") and available:
                text = available[0]
                used_texts.add(text.lower())
                lines.append(
                    {
                        "speaker": speakers[0] if speakers else "Narrator",
                        "text": text,
                        "kind": kind,
                        "emotion": emotion,
                    }
                )

            narration = None
            if panel.get("is_first_of_scene"):
                narration = clean_clause(action)[:160] or None
            lines = [line for line in lines if not (narration and line["speaker"].lower() == "narrator" and line["text"].strip().lower() == narration.strip().lower())]

            sfx = None
            if emotion in SFX_BY_EMOTION and rng.random() < 0.5:
                sfx = rng.choice(SFX_BY_EMOTION[emotion])

            out.append(
                {
                    "panel_id": panel_id,
                    "lines": lines,
                    "narration": narration,
                    "sfx": sfx,
                }
            )
        return {"panels": out}

    def _build_camera_director(self, payload: dict[str, Any]) -> dict[str, Any]:
        panels = payload.get("panels") or []
        out: list[dict[str, Any]] = []
        for panel in panels:
            panel_id = panel.get("panel_id", "")
            emotion = panel.get("emotion", "neutral")
            action = (panel.get("action") or "").lower()
            idx_in_scene = int(panel.get("index_in_scene", 0))

            if panel.get("is_first_of_scene"):
                shot = "establishing_wide"
                rationale = "Open the scene by establishing location and scale."
            elif emotion in ("anger", "fear", "surprise"):
                shot = "close_up"
                rationale = "Push in on the emotional peak of the beat."
            elif emotion in ("sadness", "love") and idx_in_scene % 2 == 1:
                shot = "medium_close"
                rationale = "Hold the beat on the character's reaction."
            elif any(w in action for w in ("fight", "run", "chase", "attack", "jump")):
                shot = "low_angle"
                rationale = "Low angle to add force and momentum to the action."
            elif panel.get("is_last_of_scene"):
                shot = "over_the_shoulder"
                rationale = "Close the scene on the character's point of view."
            else:
                shot = SHOT_CYCLE[idx_in_scene % len(SHOT_CYCLE)]
                rationale = "Vary the rhythm between the surrounding beats."

            composition = {
                "establishing_wide": "wide establishing frame, characters small in the lower third",
                "wide": "full-body action, generous headroom",
                "medium": "waist-up, character centred with negative space to one side",
                "medium_close": "chest-up, shallow background separation",
                "close_up": "face fills the frame, background reduced to soft shapes",
                "extreme_close_up": "tight on the eyes, extreme detail",
                "over_the_shoulder": "over the shoulder toward the subject of the beat",
                "low_angle": "camera below eye level looking up, dynamic diagonal",
                "high_angle": "camera above, subject compressed against the ground",
                "bird_eye": "directly overhead, geometric staging",
                "dutch_angle": "tilted horizon, off-balance framing",
            }[shot]
            out.append(
                {
                    "panel_id": panel_id,
                    "camera": {
                        "shot": shot,
                        "angle_notes": "eye level" if "angle" not in shot else shot.replace("_", " "),
                        "lens": LENS_BY_SHOT.get(shot, "35mm"),
                        "composition": composition,
                        "movement": "static" if idx_in_scene % 2 == 0 else "subtle push in",
                        "rationale": rationale,
                    },
                }
            )
        return {"panels": out}

    def _build_visual_prompt_generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        panels = payload.get("panels") or []
        style = payload.get("style", "manga")
        preset = get_style_preset(style)
        sheets = {c.get("name", "").lower(): c for c in (payload.get("character_sheets") or [])}

        out: list[dict[str, Any]] = []
        for panel in panels:
            names = [n for n in (panel.get("characters") or []) if n]
            parts: list[str] = []

            subject = ", ".join(names) if names else "the protagonist"
            parts.append(subject)

            for name in names:
                sheet = sheets.get(name.lower())
                if sheet:
                    parts.append(
                        f"{name}: {sheet.get('appearance', '').strip()} wearing "
                        f"{sheet.get('outfit', '').strip()}, consistent with reference image"
                    )
                    feats = sheet.get("distinguishing_features") or []
                    if feats:
                        parts.append(f"{name} keeps: {', '.join(feats[:3])}")

            camera = panel.get("camera") or {}
            shot = camera.get("shot", "medium")
            parts.append(f"camera: {shot.replace('_', ' ')} shot, {camera.get('lens', '35mm')}")
            if camera.get("composition"):
                parts.append(camera["composition"])

            if panel.get("setting"):
                parts.append(f"setting: {panel['setting']}")
            if panel.get("time_of_day"):
                parts.append(f"time: {panel['time_of_day']}")
            if panel.get("action"):
                parts.append(f"action: {panel['action']}")
            if panel.get("expression"):
                parts.append(f"expression: {panel['expression']}")
            if panel.get("emotion"):
                parts.append(f"mood: {panel['emotion']}")
            if panel.get("dialogue_hint"):
                parts.append(f"scene context: {panel['dialogue_hint']}")

            parts.append(preset.prompt_fragment)
            parts.append("consistent character design across panels, original character")

            negative = (
                preset.negative_fragment
                + ", extra fingers, deformed hands, extra limbs, text artifacts, watermark, "
                "signature, logo, lowres, blurry, jpeg artifacts, mutated proportions"
            )
            out.append(
                {
                    "panel_id": panel.get("panel_id", ""),
                    "positive": ", ".join(p.strip().rstrip(",") for p in parts if p and p.strip()),
                    "negative": negative,
                }
            )
        return {"panels": out}


def build_mock_llm(seed: int = 42) -> MockLLM:
    return MockLLM(seed=seed)
