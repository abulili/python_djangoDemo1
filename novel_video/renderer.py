import shutil
import subprocess
import math
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageColor, ImageDraw, ImageFont


WIDTH = 1080
HEIGHT = 1920


def run(cmd):
    completed = subprocess.run(cmd, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def ffmpeg():
    return getattr(settings, "FFMPEG_PATH", "ffmpeg")


def find_font(font_name=""):
    candidates = []
    if font_name:
        candidates.append(font_name)
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for item in candidates:
        if item and Path(item).exists():
            return item
    return None


def hex_to_rgba(value):
    try:
        r, g, b = ImageColor.getrgb(value)
        return r, g, b, 255
    except Exception:
        return 255, 255, 255, 255


def wrap_text(draw, text, font, max_width):
    lines = []
    current = ""
    for ch in text:
        trial = current + ch
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def make_text_image(text, path, font_size, color, max_width=900, padding=60, align="center"):
    font_path = find_font()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    probe = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    lines = []

    for paragraph in (text or "").splitlines():
        if paragraph.strip():
            lines.extend(wrap_text(draw, paragraph.strip(), font, max_width))
            lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    line_height = int(font_size * 1.5)
    img_height = max(HEIGHT, padding * 2 + len(lines) * line_height)
    image = Image.new("RGBA", (WIDTH, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    y = padding
    fill = hex_to_rgba(color)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        if align == "left":
            x = padding
        else:
            x = (WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=fill, stroke_width=2, stroke_fill=(0, 0, 0, 180))
        y += line_height

    image.save(path)
    return img_height


def make_horizontal_text_image(text, path, font_size, color, padding=120):
    font_path = find_font()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    probe = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    single_line = "    ".join([line.strip() for line in (text or "").splitlines() if line.strip()])
    if not single_line:
        single_line = " "

    bbox = draw.textbbox((0, 0), single_line, font=font)
    text_width = max(WIDTH, bbox[2] - bbox[0] + padding * 2)
    image = Image.new("RGBA", (text_width, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill = hex_to_rgba(color)
    y = (HEIGHT - (bbox[3] - bbox[1])) // 2
    draw.text((padding, y), single_line, font=font, fill=fill, stroke_width=3, stroke_fill=(0, 0, 0, 220))
    image.save(path)
    return text_width


def make_card_image(text, path, font_size, color):
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font_path = find_font()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    lines = wrap_text(draw, text, font, 880)
    line_height = int(font_size * 1.45)
    total_height = len(lines) * line_height
    y = (HEIGHT - total_height) // 2
    fill = hex_to_rgba(color)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=fill, stroke_width=3, stroke_fill=(0, 0, 0, 220))
        y += line_height

    image.save(path)


def background_video(background_path, duration, output):
    path = Path(background_path or "")
    if not path.exists():
        raise FileNotFoundError(f"background not found: {background_path}")
    if not path.is_file():
        raise FileNotFoundError(f"background path is not a file: {background_path}")

    vf = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},setsar=1,fps=30"

    if path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
        run([
            ffmpeg(), "-y",
            "-loop", "1",
            "-t", str(duration),
            "-i", str(path),
            "-vf", vf,
            "-an",
            "-pix_fmt", "yuv420p",
            str(output),
        ])
        return

    run([
        ffmpeg(), "-y",
        "-stream_loop", "-1",
        "-t", str(duration),
        "-i", str(path),
        "-vf", vf,
        "-an",
        "-pix_fmt", "yuv420p",
        str(output),
    ])


def render_opening(script, work_dir):
    opening = script.get("opening")
    if not opening:
        return None, 0

    duration = int(opening.get("duration") or 3)
    background_path = (opening.get("background") or {}).get("path")
    base = work_dir / "opening_base.mp4"
    output = work_dir / "opening.mp4"

    background_video(background_path, duration, base)

    text = opening.get("text") or ""
    if not text:
        shutil.copyfile(base, output)
        return output, duration

    font = opening.get("font") or {}
    overlay = work_dir / "opening_text.png"
    make_card_image(text, overlay, int(font.get("size") or 54), font.get("color") or "#ffffff")
    run([
        ffmpeg(), "-y",
        "-i", str(base),
        "-i", str(overlay),
        "-filter_complex", "overlay=0:0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output),
    ])
    return output, duration


def render_scrolling_main(script, work_dir):
    main = script["main"]
    requested_duration = int(main.get("duration") or 0)
    background_path = (main.get("background") or {}).get("path")
    base = work_dir / "main_base.mp4"
    text_png = work_dir / "scroll_text.png"
    output = work_dir / "main.mp4"
    font = main.get("font") or {}
    image_height = make_text_image(
        main.get("text") or "",
        text_png,
        int(font.get("size") or 48),
        font.get("color") or "#ffffff",
        max_width=WIDTH - 160,
        padding=80,
        align="left",
    )

    scrolling = main.get("scrolling") or {}
    speed = max(float(scrolling.get("speed") or 1.0), 0.1)
    start_y = int(scrolling.get("start_y", HEIGHT))
    default_end_y = HEIGHT // 2 - image_height
    end_y = int(scrolling.get("end_y", default_end_y))
    x = int(scrolling.get("x", 0))
    duration = requested_duration or max(8, math.ceil(abs(end_y - start_y) / (90 * speed)))
    overlay_expr = f"x={x}:y='{start_y}+({end_y}-{start_y})*t/{duration}':eof_action=pass"

    background_video(background_path, duration, base)

    run([
        ffmpeg(), "-y",
        "-i", str(base),
        "-loop", "1",
        "-i", str(text_png),
        "-filter_complex", f"overlay={overlay_expr}",
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output),
    ])
    return output, duration


def render_sentence_cards(script, work_dir):
    outputs = []
    total_duration = 0

    for item in script.get("segments", []):
        duration = int(item.get("duration") or 3)
        total_duration += duration
        index = int(item.get("index") or len(outputs) + 1)
        background_path = (item.get("background") or {}).get("path")
        base = work_dir / f"card_{index:03}_base.mp4"
        overlay = work_dir / f"card_{index:03}.png"
        output = work_dir / f"card_{index:03}.mp4"

        background_video(background_path, duration, base)
        font = item.get("font") or {}
        make_card_image(item.get("text") or "", overlay, int(font.get("size") or 54), font.get("color") or "#ffffff")

        run([
            ffmpeg(), "-y",
            "-i", str(base),
            "-i", str(overlay),
            "-filter_complex", "overlay=0:0",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output),
        ])
        outputs.append(output)

    return concat_videos(outputs, work_dir / "main.mp4"), total_duration


def concat_videos(videos, output):
    if not videos:
        raise ValueError("no videos to concat")

    if len(videos) == 1:
        shutil.copyfile(videos[0], output)
        return output

    cmd = [ffmpeg(), "-y"]
    for item in videos:
        cmd.extend(["-i", str(item)])

    inputs = "".join(f"[{index}:v:0]" for index in range(len(videos)))
    cmd.extend([
        "-filter_complex",
        f"{inputs}concat=n={len(videos)}:v=1:a=0[v]",
        "-map",
        "[v]",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output),
    ])
    run(cmd)
    return output


def make_silence(duration, output):
    run([
        ffmpeg(), "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-c:a", "aac",
        str(output),
    ])


def make_audio_segment(source_path, duration, output, volume=1.0, loop=False):
    if not source_path:
        make_silence(duration, output)
        return

    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"audio not found: {source_path}")
    if not path.is_file():
        raise FileNotFoundError(f"audio path is not a file: {source_path}")

    loop_args = ["-stream_loop", "-1"] if loop else []
    run([
        ffmpeg(), "-y",
        *loop_args,
        "-i", str(path),
        "-t", str(duration),
        "-af", f"volume={volume},apad",
        "-c:a", "aac",
        str(output),
    ])


def concat_audios(audios, output):
    if not audios:
        return None

    if len(audios) == 1:
        shutil.copyfile(audios[0], output)
        return output

    cmd = [ffmpeg(), "-y"]
    for item in audios:
        cmd.extend(["-i", str(item)])

    inputs = "".join(f"[{index}:a]" for index in range(len(audios)))
    cmd.extend([
        "-filter_complex",
        f"{inputs}concat=n={len(audios)}:v=0:a=1[a]",
        "-map",
        "[a]",
        "-c:a",
        "aac",
        str(output),
    ])
    run(cmd)
    return output


def build_audio_track(script, opening_duration, main_duration, work_dir):
    audios = []

    if opening_duration > 0:
        opening_audio = ((script.get("opening") or {}).get("audio") or {}).get("path", "")
        opening_output = work_dir / "opening_audio.m4a"
        make_audio_segment(opening_audio, opening_duration, opening_output, volume=1.0, loop=False)
        audios.append(opening_output)

    if main_duration > 0:
        audio = script.get("audio") or {}
        bgm = audio.get("bgm") or {}
        bgm_output = work_dir / "main_bgm.m4a"
        make_audio_segment(
            bgm.get("path", ""),
            main_duration,
            bgm_output,
            volume=float(audio.get("bgm_volume", 0.35)),
            loop=bool(audio.get("bgm_loop", True)),
        )
        audios.append(bgm_output)

    return concat_audios(audios, work_dir / "audio.m4a")


def attach_audio(video_path, audio_path, output):
    if not audio_path:
        shutil.copyfile(video_path, output)
        return

    run([
        ffmpeg(), "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(output),
    ])


def make_cover(video_path, output):
    run([
        ffmpeg(), "-y",
        "-ss", "00:00:01",
        "-i", str(video_path),
        "-frames:v", "1",
        str(output),
    ])


def render_video(script, output_dir):
    output_dir = Path(output_dir)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    parts = []
    opening_video, opening_duration = render_opening(script, work_dir)
    if opening_video:
        parts.append(opening_video)

    if script.get("render_mode") == "sentence_card":
        main_video, main_duration = render_sentence_cards(script, work_dir)
    else:
        main_video, main_duration = render_scrolling_main(script, work_dir)

    parts.append(main_video)

    video_only = concat_videos(parts, work_dir / "video_only.mp4")
    audio_track = build_audio_track(script, opening_duration, main_duration, work_dir)
    final_path = output_dir / "final.mp4"
    cover_path = output_dir / "cover.png"

    attach_audio(video_only, audio_track, final_path)
    make_cover(final_path, cover_path)

    return {
        "final_path": str(final_path),
        "cover_path": str(cover_path),
        "duration": opening_duration + main_duration,
    }
