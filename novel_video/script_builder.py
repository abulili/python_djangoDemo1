import re


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
    return {
        "role": role,
        "asset_id": asset.id,
        "name": asset.name,
        "material_type": asset.material_type,
        "storage_type": asset.storage_type,
        "path": asset.get_path(),
        "style": asset.style,
        "tags": asset.tags,
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


def build_opening(job):
    if not job.opening_text and not job.opening_audio_asset:
        return None

    text = apply_name_replacements(job.opening_text, job.name_replacements)
    text = normalize_sentence_text(text, job.text_rules)

    return {
        "text": text,
        "duration": job.opening_duration,
        "background": asset_json(job.background_asset, "background"),
        "audio": asset_json(job.opening_audio_asset, "opening_audio"),
        "font": {
            "name": job.font_name,
            "size": job.font_size,
            "color": job.font_color,
            "position": "center",
        },
    }


def build_base_script(job):
    return {
        "title": job.title,
        "render_mode": job.render_mode,
        "style": job.style,
        "opening": build_opening(job),
        "assets": build_assets(job),
        "audio": {
            "bgm": asset_json(job.bgm_asset, "bgm"),
            "bgm_loop": job.bgm_loop,
            "bgm_volume": job.bgm_volume,
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
        "background": asset_json(job.background_asset, "background"),
        "font": {
            "name": job.font_name,
            "size": job.font_size,
            "color": job.font_color,
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
