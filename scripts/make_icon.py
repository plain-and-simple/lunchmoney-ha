"""Render the Lunch Money for Home Assistant icon.

Concept: a house whose roof carries a coin slot, with a bitten gold coin dropping
into it. House = Home Assistant, slot = banking, bite = lunch. Drawn at 4x and
downsampled so every edge is antialiased without needing a vector renderer.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

S = 4  # supersample factor
W = 512  # final logical size
C = W * S

OUT = Path(
    "/Users/youcha_agent/Documents/LunchMoneyIntoHA/custom_components/lunchmoney/brand"
)

BG_TOP = (2, 136, 209)
BG_BOTTOM = (1, 70, 130)
ROOF = (255, 255, 255)
BODY = (214, 234, 248)
SLOT = (1, 60, 112)
COIN = (255, 201, 77)
COIN_RIM = (232, 163, 23)
COIN_MARK = (150, 92, 12)


def s(*vals: float) -> tuple[int, ...]:
    """Scale logical coordinates up to the supersampled canvas."""
    return tuple(round(v * S) for v in vals)


def rounded_tile() -> Image.Image:
    """Return the background tile with a vertical gradient and rounded corners."""
    grad = Image.new("RGB", (1, C))
    for y in range(C):
        t = y / (C - 1)
        grad.putpixel(
            (0, y),
            tuple(
                round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)
            ),
        )
    tile = grad.resize((C, C)).convert("RGBA")

    mask = Image.new("L", (C, C), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, C - 1, C - 1], radius=112 * S, fill=255
    )
    tile.putalpha(mask)
    return tile


def draw_house(base: Image.Image) -> None:
    """Draw the body, then the roof over it, then punch the coin slot."""
    d = ImageDraw.Draw(base)

    # Body sits under the roof's overhang so the two read as separate planes.
    d.rounded_rectangle(s(150, 286, 362, 444), radius=14 * S, fill=BODY)

    # Roof: a broad triangle. Supersampling keeps the apex clean, so it needs
    # no rounding-off — and a cap there reads as a finial rather than a roof.
    d.polygon([s(256, 172), s(404, 298), s(108, 298)], fill=ROOF)

    # Coin slot, sized to sit comfortably inside the roof at this height.
    d.rounded_rectangle(s(210, 246, 302, 267), radius=10 * S, fill=SLOT)

    # A door, so the house reads as a house and not an arrow. Square-footed, so
    # it sits on the floor instead of floating above it.
    d.rounded_rectangle(
        s(234, 362, 278, 444),
        radius=14 * S,
        fill=(255, 255, 255),
        corners=(True, True, False, False),
    )


def coin_layer() -> Image.Image:
    """Return the coin on its own layer, with a bite punched out of the rim."""
    layer = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cx, cy, r = 256, 92, 58
    d.ellipse(s(cx - r, cy - r, cx + r, cy + r), fill=COIN_RIM)
    d.ellipse(s(cx - r + 9, cy - r + 9, cx + r - 9, cy + r - 9), fill=COIN)

    # A dollar mark makes it unambiguously money rather than a biscuit.
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", 72 * S, index=1
        )
    except OSError:
        font = ImageFont.load_default()
    d.text(s(cx, cy + 1), "$", font=font, fill=COIN_MARK, anchor="mm")

    # The bite: a circle centred on the rim, removed from the alpha channel so
    # the tile shows through rather than being painted over.
    bite = Image.new("L", (C, C), 255)
    ImageDraw.Draw(bite).ellipse(s(270, 24, 332, 86), fill=0)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), bite))

    # A slight tilt reads as motion — the coin is going in, not sitting there.
    return layer.rotate(-14, resample=Image.BICUBIC, center=s(cx, cy))


def main() -> None:
    """Compose the icon and write both required sizes."""
    base = rounded_tile()
    draw_house(base)
    base.alpha_composite(coin_layer())

    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in ((512, "icon@2x.png"), (256, "icon.png")):
        base.resize((size, size), Image.LANCZOS).save(OUT / name)
        print(f"wrote {OUT / name} ({size}x{size})")


if __name__ == "__main__":
    main()
