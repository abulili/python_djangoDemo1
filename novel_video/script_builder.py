import re

from .models import MaterialAsset
from .storage import key_to_storage_ref, path_to_key


DEFAULT_SPLIT_PUNCTUATION = ["，", "。", "！", "？", "；", "：", ",", ".", "!", "?", ";", ":"]


def apply_name_replacements(text, replacements):
    result = text or ""
    for item in replacements or []:
        old = item.get("from", "")
        new = item.get("to", "")
        if old:
            result = result.replace(old, new)
    return result


def normalize_scrolling_text(text):
    return (text or "").strip()


def normalize_sentence_text(text, rules):
    result = text or ""
    rules = rules or {}

    if rules.get("replace_colon_with_space"):
        result = result.replace("：", " ").replace(":", " ")

    if rules.get("remove_quotes"):
        for ch in ["“", "”", "‘", "’", '"', "'"]:
            result = result.replace(ch, "")

    if rules.get("remove_extra_newlines"):
        result = re.sub(r"\n{2,}", "\n", result)

    if rules.get("normalize_spaces"):
        result = re.sub(r"[ \t]+", " ", result)

    return result.strip()


def split_to_sentences(text, punctuation=None):
    punctuation = punctuation or DEFAULT_SPLIT_PUNCTUATION
    escaped = "".join(re.escape(ch) for ch in punctuation)
    return [item.strip() for item in re.split(f"[{escaped}]+", text) if item.strip()]


def guess_duration(text):
    return max(2, min(6, len(text or "") // 12 + 2))


def asset_json(asset, role):
    if not asset:
        return None
    path = asset.get_path()
    if asset.storage_type == MaterialAsset.STORAGE_UPLOAD and asset.file:
        path = key_to_storage_ref(path_to_key(asset.file.path))
    return {
        "role": role,
        "asset_id": asset.id,
        "name": asset.name,
        "material_type": asset.material_type,
        "storage_type": asset.storage_type,
        "path": path,
        "style": asset.style,
        "tags": asset.tags,
        "duration": asset.duration,
    }


def build_assets(job):
    assets = []
    for item in [
        asset_json(job.background_asset, "background"),
        asset_json(job.bgm_asset, "bgm"),
        asset_json(job.opening_audio_asset, "opening_audio"),
    ]:
        if item:
            assets.append(item)
    return assets


def build_opening_lines(job):
    raw_lines = getattr(job, "opening_lines", None) or []
    lines = []

    for item in raw_lines[:4]:
        text = apply_name_replacements((item or {}).get("text", ""), job.name_replacements).strip()
        if not text:
            continue
        lines.append({
            "text": normalize_sentence_text(text, job.text_rules),
            "font": {
                "name": (item or {}).get("font_name") or job.font_name,
                "size": int((item or {}).get("font_size") or job.font_size or 54),
                "color": (item or {}).get("font_color") or job.font_color,
                "stroke_width": int((item or {}).get("stroke_width") or job.font_stroke_width or 3),
                "stroke_color": (item or {}).get("stroke_color") or job.font_stroke_color,
            },
        })

    if lines:
        return lines

    text = apply_name_replacements(getattr(job, "opening_text", ""), job.name_replacements)
    text = normalize_sentence_text(text, job.text_rules)
    if not text:
        return []

    return [{
        "text": text,
        "font": {
            "name": job.font_name,
            "size": job.font_size,
            "color": job.font_color,
            "stroke_width": job.font_stroke_width,
            "stroke_color": job.font_stroke_color,
        },
    }]


def build_opening(job):
    opening_enabled = bool(getattr(job, "opening_enabled", False))
    audio_mode = getattr(job, "opening_audio_mode", "uploaded") or "uploaded"
    lines = build_opening_lines(job)
    audio_asset = job.opening_audio_asset if audio_mode == "uploaded" else None

    if not opening_enabled and not lines and not audio_asset:
        return None

    text = "\n".join(item["text"] for item in lines)

    return {
        "text": text,
        "lines": lines,
        "duration": job.opening_duration,
        "audio_mode": audio_mode,
        "background": asset_json(job.background_asset, "background"),
        "audio": asset_json(audio_asset, "opening_audio"),
        "font": {
            "name": job.font_name,
            "size": job.font_size,
            "color": job.font_color,
            "stroke_width": job.font_stroke_width,
            "stroke_color": job.font_stroke_color,
            "position": "center",
        },
    }


def build_base_script(job):
    return {
        "title": job.title,
        "render_mode": job.render_mode,
        "style": job.style,
        "text_start_time": max(float(getattr(job, "text_start_time", 0) or 0), 0),
        "opening": build_opening(job),
        "assets": build_assets(job),
        "audio": {
            "bgm": asset_json(job.bgm_asset, "bgm"),
            "bgm_loop": job.bgm_loop,
            "bgm_volume": job.bgm_volume,
            "bgm_speed": job.bgm_speed,
            "tts_enabled": job.tts_enabled,
            "tts_voice": job.tts_voice,
            "tts_rate": job.tts_rate,
            "tts_volume": job.tts_volume,
        },
    }


def build_sentence_card_script(job, text):
    script = build_base_script(job)
    sentences = split_to_sentences(text, job.split_punctuation or DEFAULT_SPLIT_PUNCTUATION)
    script["segments"] = [
        {
            "index": index,
            "text": sentence,
            "duration": guess_duration(sentence),
            "keywords": [job.style] if job.style else [],
            "background": asset_json(job.background_asset, "background"),
            "font": {
                "name": job.font_name,
                "size": job.font_size,
                "color": job.font_color,
                "stroke_width": job.font_stroke_width,
                "stroke_color": job.font_stroke_color,
                "position": job.sentence_position,
            },
        }
        for index, sentence in enumerate(sentences, start=1)
    ]
    return script


def build_scrolling_text_script(job, text):
    script = build_base_script(job)
    script["main"] = {
        "text": text,
        "duration": job.target_duration or 0,
        "text_start_time": max(float(getattr(job, "text_start_time", 0) or 0), 0),
        "background": asset_json(job.background_asset, "background"),
        "font": {
            "name": job.font_name,
            "size": job.font_size,
            "color": job.font_color,
            "stroke_width": job.font_stroke_width,
            "stroke_color": job.font_stroke_color,
        },
        "scrolling": {
            "start_y": job.scrolling_start_y,
            "end_y": job.scrolling_end_y,
            "speed": job.scrolling_speed,
        },
    }
    return script


def build_script(job):
    raw_text = apply_name_replacements(job.novel_text, job.name_replacements)

    if job.render_mode == "sentence_card":
        text = normalize_sentence_text(raw_text, job.text_rules)
        return build_sentence_card_script(job, text)

    text = normalize_scrolling_text(raw_text)
    return build_scrolling_text_script(job, text)
