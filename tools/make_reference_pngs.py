# tools/make_reference_pngs.py
# Betta Farm Management System
# Session 26H — Generate reference silhouettes as PNG using Pillow.
# No cairo, no native libs. Just Pillow.
#
# Usage (from repo root):
#   python tools/make_reference_pngs.py
#
# Writes 4 PNGs to modules/reference_shapes/.

from pathlib import Path
from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "modules" / "reference_shapes"
W, H = 800, 600


def new_canvas():
    """White canvas, RGB mode."""
    return Image.new("RGB", (W, H), (255, 255, 255))


def draw_traditional_show(draw):
    """Traditional Show Plakat: fan dorsal (not extended), pointed anal,
    rounded 180° caudal."""
    # Body — elongated ellipse
    draw.ellipse([120, 250, 480, 350], fill=(0, 0, 0))
    # Head taper
    draw.polygon([(120, 300), (60, 280), (60, 320)], fill=(0, 0, 0))
    # Eye
    draw.ellipse([95, 290, 110, 305], fill=(255, 255, 255))
    # Dorsal — fan shape (moderate, not extended)
    draw.polygon([(280, 250), (330, 130), (420, 150), (460, 250)],
                 fill=(0, 0, 0))
    # Caudal — rounded 180 spread
    draw.polygon([(480, 240), (640, 180), (720, 220), (740, 300),
                  (720, 380), (640, 420), (480, 360)], fill=(0, 0, 0))
    # Anal — pointed trapezoid
    draw.polygon([(300, 350), (400, 470), (470, 430), (490, 350)],
                 fill=(0, 0, 0))
    # Ventral fins
    draw.polygon([(200, 350), (180, 460), (220, 500), (235, 400), (235, 350)],
                 fill=(0, 0, 0))
    draw.polygon([(240, 350), (240, 470), (270, 510), (290, 480), (280, 400),
                  (280, 350)], fill=(0, 0, 0))


def draw_symmetrical_show(draw):
    """Symmetrical Show Plakat: extended dorsal, trapezoid anal, D-caudal."""
    # Body
    draw.ellipse([120, 255, 480, 345], fill=(0, 0, 0))
    # Head
    draw.polygon([(120, 300), (55, 282), (55, 318)], fill=(0, 0, 0))
    # Eye
    draw.ellipse([90, 292, 105, 307], fill=(255, 255, 255))
    # Dorsal — extended tall
    draw.polygon([(220, 255), (260, 60), (400, 80), (470, 120), (490, 255)],
                 fill=(0, 0, 0))
    # Caudal — D-shape 180
    draw.polygon([(490, 250), (640, 160), (735, 230), (760, 300),
                  (735, 370), (640, 440), (490, 350)], fill=(0, 0, 0))
    # Anal — trapezoid
    draw.polygon([(280, 345), (380, 500), (480, 485), (510, 345)],
                 fill=(0, 0, 0))
    # Ventral fins
    draw.polygon([(190, 345), (170, 440), (200, 500), (225, 470), (220, 380),
                  (220, 345)], fill=(0, 0, 0))
    draw.polygon([(240, 345), (240, 460), (270, 510), (290, 480), (280, 380),
                  (280, 345)], fill=(0, 0, 0))


def draw_asymmetrical_show(draw):
    """Asymmetrical Show Plakat: plakat fan dorsal, pointed anal,
    D-caudal 180."""
    # Body
    draw.ellipse([120, 250, 480, 350], fill=(0, 0, 0))
    # Head
    draw.polygon([(120, 300), (55, 282), (55, 318)], fill=(0, 0, 0))
    # Eye
    draw.ellipse([90, 292, 105, 307], fill=(255, 255, 255))
    # Dorsal — fan (moderate)
    draw.polygon([(260, 250), (300, 130), (400, 150), (450, 190), (470, 250)],
                 fill=(0, 0, 0))
    # Caudal — D 180
    draw.polygon([(490, 250), (620, 160), (710, 240), (740, 300),
                  (710, 360), (620, 440), (490, 350)], fill=(0, 0, 0))
    # Anal — pointed
    draw.polygon([(300, 350), (400, 490), (470, 445), (500, 350)],
                 fill=(0, 0, 0))
    # Ventral extended
    draw.polygon([(190, 350), (160, 460), (200, 530), (230, 490), (220, 380),
                  (220, 350)], fill=(0, 0, 0))
    draw.polygon([(240, 350), (240, 470), (270, 530), (290, 490), (280, 380),
                  (280, 350)], fill=(0, 0, 0))


def draw_pet_grade(draw):
    """Pet-grade baseline: relaxed pose, moderate fins."""
    # Body (slightly shorter)
    draw.ellipse([140, 260, 480, 340], fill=(0, 0, 0))
    # Head
    draw.polygon([(140, 300), (85, 285), (85, 315)], fill=(0, 0, 0))
    # Eye
    draw.ellipse([115, 293, 130, 308], fill=(255, 255, 255))
    # Dorsal — modest
    draw.polygon([(280, 260), (320, 180), (400, 200), (430, 220), (440, 260)],
                 fill=(0, 0, 0))
    # Caudal — moderate (not full 180)
    draw.polygon([(490, 260), (580, 220), (640, 250), (660, 300),
                  (640, 350), (580, 380), (490, 340)], fill=(0, 0, 0))
    # Anal — moderate
    draw.polygon([(320, 340), (400, 430), (460, 415), (490, 340)],
                 fill=(0, 0, 0))
    # Ventral modest
    draw.polygon([(220, 340), (210, 410), (240, 450), (260, 430), (250, 380),
                  (250, 340)], fill=(0, 0, 0))
    draw.polygon([(260, 340), (260, 420), (280, 460), (300, 430), (290, 380),
                  (290, 340)], fill=(0, 0, 0))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    variants = [
        ("hmpk_traditional_show", draw_traditional_show),
        ("hmpk_symmetrical_show", draw_symmetrical_show),
        ("hmpk_asymmetrical_show", draw_asymmetrical_show),
        ("hmpk_pet_grade", draw_pet_grade),
    ]

    for name, draw_fn in variants:
        img = new_canvas()
        draw = ImageDraw.Draw(img)
        draw_fn(draw)
        out = OUT_DIR / f"{name}.png"
        img.save(out, "PNG")
        print(f"Wrote {out}")

    print()
    print(f"Done. {len(variants)} silhouettes generated in {OUT_DIR}")


if __name__ == "__main__":
    main()
