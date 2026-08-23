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


def make_status_dots(size: int = 14):
    from PIL import Image, ImageDraw, ImageTk

    def _dot(fill: tuple[int, int, int, int], ring: tuple[int, int, int, int]):
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((1, 1, size - 2, size - 2), fill=fill, outline=ring)
        return ImageTk.PhotoImage(image)

    return (
        _dot((34, 197, 94, 255), (21, 128, 61, 255)),
        _dot((148, 163, 184, 255), (100, 116, 139, 255)),
    )


def make_check_icons(size: int = 16):
    from PIL import Image, ImageDraw, ImageTk

    def _box(checked: bool):
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=3, outline=(148, 163, 184, 255), width=1, fill=(24, 35, 58, 255))
        if checked:
            draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=3, outline=(13, 148, 136, 255), width=1, fill=(15, 118, 110, 255))
            draw.line((4, 8, 7, 11), fill=(255, 255, 255, 255), width=2)
            draw.line((7, 11, 12, 4), fill=(255, 255, 255, 255), width=2)
        return ImageTk.PhotoImage(image)

    return _box(False), _box(True)


def apply_window_icon(window) -> None:
    path = icon_path()
    if path.exists():
        try:
            window.iconbitmap(str(path))
        except Exception:
            pass
