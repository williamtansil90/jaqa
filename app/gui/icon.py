from __future__ import annotations

from pathlib import Path

from app.core.storage import app_data_dir


def icon_path() -> Path:
    path = app_data_dir() / "jaqa.ico"
    if path.exists():
        return path
    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGBA", (256, 256), (11, 58, 74, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((16, 16, 240, 240), radius=36, fill=(15, 118, 110, 255))
        try:
            font = ImageFont.truetype("segoeui.ttf", 92)
        except OSError:
            font = ImageFont.load_default()
        draw.text((42, 70), "JQ", fill=(255, 255, 255, 255), font=font)
        image.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    except Exception:
        pass
    return path


def apply_window_icon(window) -> None:
    path = icon_path()
    if path.exists():
        try:
            window.iconbitmap(str(path))
        except Exception:
            pass
