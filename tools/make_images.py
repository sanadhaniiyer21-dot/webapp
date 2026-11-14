"""
Generate the site's illustrations as SVG.

The shop has no photography it owns, and stock photography of tea is both a
cliche and a licensing problem. So every image here is drawn in code: flat
shapes in a limited palette, one accent per image, a grain texture from an SVG
noise filter, in the manner of a printed catalogue rather than clip-art.

    python tools/make_images.py

Writes:
    core/static/core/img/teas/<slug>.svg   one per tea, in that tea's colour
    core/static/core/img/hero.svg          the home page composition
    core/static/core/img/leaf.svg          the small botanical mark
    core/static/core/img/bowl.svg          used by the brew guide

A real photograph always wins: templates check for
core/static/core/img/teas/<slug>.jpg first and only fall back to the SVG, so
dropping in photographs later needs no code change.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.content import TEAS  # noqa: E402

IMG_DIR = ROOT / "core" / "static" / "core" / "img"
TEA_DIR = IMG_DIR / "teas"

# The site's own palette, repeated here so the images match the stylesheet.
PAPER = "#F3EEE4"
PAPER_DEEP = "#E9E2D3"
INK = "#1A1916"
HAIRLINE = "#D6CEBD"
GREEN_DARK = "#2B3A2C"

# One colour per tea, chosen to look like that tea's liquor or leaf.
CATEGORY_COLOUR = {
    "green": "#7E9B3F",
    "matcha": "#6E8B2E",
    "black": "#8B3A1F",
    "oolong": "#B5762F",
    "white": "#C4B88A",
    "dark": "#4A2C1C",
    "tisane": "#C08A2E",
    "blend": "#A4552B",
}

# Where a tea's own colour is more specific than its category's.
SLUG_COLOUR = {
    "hojicha-kyobancha": "#8A5A2B",
    "jasmine-silver-pearls": "#B8BE72",
    "gyokuro-yame": "#5F8438",
    "lapsang-souchong-pine-smoked": "#55352A",
    "darjeeling-first-flush-jungpana": "#B08A3C",
    "nilgiri-frost-winter-picking": "#A8571F",
    "chamomile-fayoum-whole-flower": "#D8A93B",
    "tulsi-and-mint": "#5E7F55",
    "rooibos-and-orange-peel": "#B1431F",
    "hibiscus-and-rose": "#9B1B3A",
    "lemongrass-and-ginger": "#A8B44A",
    "masala-chai-house-blend": "#A4552B",
    "earl-grey-cold-pressed-bergamot": "#9A6B24",
    "kashmiri-kahwa": "#C9922F",
    "shou-puer-2016-menghai": "#3F2619",
    "liu-bao-aged-basket": "#4F3220",
}

# Which object is drawn for a tea. Varying the silhouette by category stops the
# grid looking like one shape recoloured twenty-eight times.
CATEGORY_SHAPE = {
    "green": "tin",
    "black": "tin",
    "oolong": "tin",
    "white": "pouch",
    "matcha": "bowl",
    "dark": "cake",
    "tisane": "jar",
    "blend": "tin",
}


def colour_for(tea: dict) -> str:
    return SLUG_COLOUR.get(tea["slug"]) or CATEGORY_COLOUR.get(tea["category"], INK)


# ---------------------------------------------------------------------------
# Shared SVG pieces
# ---------------------------------------------------------------------------


def defs(seed: int, accent: str) -> str:
    """
    Filters and patterns.

    The grain is one feTurbulence layer drawn over everything at low opacity.
    It is what stops large flat fills reading as a vector graphic, and it is
    cheap: one filter, no raster assets.
    """
    return f"""  <defs>
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4"
                    seed="{seed}" result="noise"/>
      <feColorMatrix in="noise" type="saturate" values="0"/>
    </filter>
    <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse"
             patternTransform="rotate(35)">
      <line x1="0" y1="0" x2="0" y2="6" stroke="{accent}" stroke-width="1.6"
            opacity="0.55"/>
    </pattern>
  </defs>"""


def grain_overlay(width: int, height: int) -> str:
    return (
        f'  <rect width="{width}" height="{height}" filter="url(#grain)" '
        f'opacity="0.10" style="mix-blend-mode:multiply"/>'
    )


def leaf_path(length: float) -> str:
    """
    One leaf, drawn pointing along +x with its base at the origin.

    Keeping the shape at the origin is what makes it placeable: each leaf is
    positioned with its own translate then rotated about its own base. An
    earlier version rotated every leaf about the group origin instead, which
    flung them off the stem and left the sprigs looking like specks.
    """
    half = length * 0.27
    return (
        f"M0 0 "
        f"C {length * 0.26:.1f} {-half:.1f} {length * 0.74:.1f} {-half * 0.95:.1f} "
        f"{length:.1f} 0 "
        f"C {length * 0.74:.1f} {half * 0.95:.1f} {length * 0.26:.1f} {half:.1f} 0 0 Z"
    )


def sprig(x: int, y: int, accent: str, scale: float = 1.0, flip: bool = False) -> str:
    """
    A botanical sprig: one stem with four alternating leaves, as filled shapes
    rather than outlines, so it prints like a woodcut.

    Angles are in SVG degrees, where +y points down, so "up and to the right"
    is -40 and "up and to the left" is -140.
    """
    transform = f"translate({x} {y}) scale({-scale if flip else scale} {scale})"

    parts = [
        f'    <path d="M0 10 C -3 -16 2 -46 0 -78" stroke="{accent}" '
        f'stroke-width="2.4" fill="none" stroke-linecap="round"/>'
    ]
    for index, (offset, length) in enumerate([(-4, 36), (-26, 31), (-46, 26), (-62, 20)]):
        angle = -40 if index % 2 == 0 else -140
        parts.append(
            f'    <g transform="translate(0 {offset}) rotate({angle})">\n'
            f'      <path d="{leaf_path(length)}" fill="{accent}" opacity="0.9"/>\n'
            f'      <line x1="2" y1="0" x2="{length - 3:.1f}" y2="0" '
            f'stroke="{PAPER_DEEP}" stroke-width="1" opacity="0.55"/>\n'
            f"    </g>"
        )
    return f'  <g transform="{transform}">\n' + "\n".join(parts) + "\n  </g>"


def steam(x: int, y: int, colour: str, count: int = 3) -> str:
    """Three thin rising lines. No gradient, no blur, no glow."""
    lines = []
    for index in range(count):
        offset = (index - (count - 1) / 2) * 16
        height = 42 + (index % 2) * 14
        lines.append(
            f'    <path d="M{offset} 0 C {offset - 9} {-height * 0.33} '
            f"{offset + 9} {-height * 0.66} {offset} {-height}\" "
            f'stroke="{colour}" stroke-width="2" fill="none" '
            f'stroke-linecap="round" opacity="0.5"/>'
        )
    return f'  <g transform="translate({x} {y})">\n' + "\n".join(lines) + "\n  </g>"


# ---------------------------------------------------------------------------
# The four tea objects
# ---------------------------------------------------------------------------

W, H = 400, 500


def shape_tin(accent: str, name: str) -> str:
    """A straight-sided caddy with a narrower lid and a label band."""
    return f"""  <!-- lid -->
  <rect x="132" y="150" width="136" height="26" fill="{INK}"/>
  <rect x="124" y="176" width="152" height="12" fill="{accent}"/>
  <!-- body -->
  <rect x="124" y="188" width="152" height="196" fill="{accent}"/>
  <rect x="124" y="188" width="152" height="196" fill="none"
        stroke="{INK}" stroke-width="2"/>
  <!-- label band -->
  <rect x="124" y="252" width="152" height="68" fill="{PAPER}"/>
  <line x1="124" y1="252" x2="276" y2="252" stroke="{INK}" stroke-width="2"/>
  <line x1="124" y1="320" x2="276" y2="320" stroke="{INK}" stroke-width="2"/>
  <line x1="140" y1="286" x2="260" y2="286" stroke="{accent}" stroke-width="2.5"/>
  <!-- hatched base, for weight -->
  <rect x="124" y="352" width="152" height="32" fill="url(#hatch)"/>
  <rect x="124" y="384" width="152" height="8" fill="{INK}"/>"""


def shape_bowl(accent: str, name: str) -> str:
    """A chawan: wide, low, with a visible well of liquid."""
    return f"""  <!-- liquid -->
  <path d="M112 266 L288 266 C286 300 262 330 200 330
           C138 330 114 300 112 266 Z" fill="{accent}"/>
  <ellipse cx="200" cy="266" rx="88" ry="15" fill="{accent}"/>
  <ellipse cx="200" cy="264" rx="74" ry="11" fill="{PAPER}" opacity="0.22"/>
  <!-- bowl wall -->
  <path d="M104 258 L296 258 C294 306 258 344 200 344
           C142 344 106 306 104 258 Z" fill="none"
        stroke="{INK}" stroke-width="2.5"/>
  <line x1="104" y1="258" x2="296" y2="258" stroke="{INK}" stroke-width="2.5"/>
  <!-- foot -->
  <rect x="172" y="344" width="56" height="14" fill="{INK}"/>
  <!-- whisk marks in the foam -->
  <path d="M166 262 C182 256 218 256 234 262" stroke="{PAPER}"
        stroke-width="2" fill="none" opacity="0.5"/>"""


def shape_cake(accent: str, name: str) -> str:
    """A pressed cake, seen slightly from above, with a paper wrapper."""
    return f"""  <!-- the paper the cake is wrapped in, laid open behind it -->
  <rect x="104" y="196" width="192" height="168" fill="{PAPER}"/>
  <rect x="104" y="196" width="192" height="168" fill="none"
        stroke="{INK}" stroke-width="2"/>
  <line x1="200" y1="196" x2="200" y2="364" stroke="{HAIRLINE}" stroke-width="1.5"/>
  <line x1="104" y1="280" x2="296" y2="280" stroke="{HAIRLINE}" stroke-width="1.5"/>
  <!-- cake, seen a little from above -->
  <path d="M110 262 L110 300 C110 322 150 338 200 338
           C250 338 290 322 290 300 L290 262 Z" fill="{accent}"/>
  <ellipse cx="200" cy="262" rx="90" ry="36" fill="{accent}"/>
  <path d="M110 262 L110 300 C110 322 150 338 200 338
           C250 338 290 322 290 300 L290 262" fill="none"
        stroke="{INK}" stroke-width="2.5"/>
  <ellipse cx="200" cy="262" rx="90" ry="36" fill="none"
           stroke="{INK}" stroke-width="2.5"/>
  <!-- the dimple every pressed cake has, where the cloth was knotted -->
  <ellipse cx="200" cy="260" rx="22" ry="9" fill="{INK}" opacity="0.32"/>
  <ellipse cx="200" cy="262" rx="60" ry="23" fill="none" stroke="{PAPER}"
           stroke-width="1.5" opacity="0.35"/>"""


def shape_pouch(accent: str, name: str) -> str:
    """A flat-bottomed paper pouch with a folded, clipped top."""
    return f"""  <!-- folded top -->
  <path d="M136 168 L264 168 L256 196 L144 196 Z" fill="{INK}"/>
  <rect x="186" y="156" width="28" height="16" fill="{accent}"/>
  <!-- body, slightly tapered -->
  <path d="M144 196 L256 196 L266 384 L134 384 Z" fill="{accent}"/>
  <path d="M144 196 L256 196 L266 384 L134 384 Z" fill="none"
        stroke="{INK}" stroke-width="2"/>
  <!-- side gusset -->
  <path d="M232 196 L242 384" stroke="{INK}" stroke-width="1.5" opacity="0.45"/>
  <!-- label -->
  <rect x="152" y="246" width="96" height="74" fill="{PAPER}"/>
  <rect x="152" y="246" width="96" height="74" fill="none"
        stroke="{INK}" stroke-width="1.8"/>
  <line x1="166" y1="280" x2="234" y2="280" stroke="{accent}" stroke-width="2.5"/>
  <line x1="166" y1="294" x2="214" y2="294" stroke="{HAIRLINE}" stroke-width="2"/>"""


def shape_jar(accent: str, name: str) -> str:
    """A glass jar, so dried flowers are visible through it."""
    return f"""  <!-- lid -->
  <rect x="150" y="162" width="100" height="22" fill="{INK}"/>
  <rect x="158" y="184" width="84" height="10" fill="{HAIRLINE}"/>
  <!-- glass -->
  <path d="M140 194 L260 194 L260 374 L140 374 Z" fill="{PAPER_DEEP}"/>
  <!-- contents, loosely packed -->
  <g>
    <circle cx="172" cy="300" r="15" fill="{accent}" opacity="0.92"/>
    <circle cx="208" cy="286" r="18" fill="{accent}" opacity="0.8"/>
    <circle cx="236" cy="314" r="13" fill="{accent}" opacity="0.95"/>
    <circle cx="190" cy="330" r="16" fill="{accent}" opacity="0.72"/>
    <circle cx="224" cy="348" r="12" fill="{accent}" opacity="0.88"/>
    <circle cx="160" cy="344" r="11" fill="{accent}" opacity="0.8"/>
    <circle cx="206" cy="356" r="10" fill="{accent}" opacity="0.6"/>
  </g>
  <path d="M140 194 L260 194 L260 374 L140 374 Z" fill="none"
        stroke="{INK}" stroke-width="2.5"/>
  <!-- one highlight line, flat, no gradient -->
  <line x1="154" y1="212" x2="154" y2="300" stroke="{PAPER}"
        stroke-width="4" opacity="0.5"/>
  <!-- paper label -->
  <rect x="140" y="226" width="120" height="40" fill="{PAPER}"/>
  <line x1="140" y1="226" x2="260" y2="226" stroke="{INK}" stroke-width="1.8"/>
  <line x1="140" y1="266" x2="260" y2="266" stroke="{INK}" stroke-width="1.8"/>
  <line x1="156" y1="246" x2="244" y2="246" stroke="{accent}" stroke-width="2.5"/>"""


SHAPES = {
    "tin": shape_tin,
    "bowl": shape_bowl,
    "cake": shape_cake,
    "pouch": shape_pouch,
    "jar": shape_jar,
}


def tea_svg(tea: dict, seed: int) -> str:
    accent = colour_for(tea)
    shape_name = CATEGORY_SHAPE.get(tea["category"], "tin")
    body = SHAPES[shape_name](accent, tea["name"])

    # A bowl already has steam; everything else gets a sprig instead.
    decoration = (
        steam(200, 240, accent) if shape_name == "bowl" else sprig(318, 150, accent, 0.9)
    )
    second = sprig(78, 404, accent, 0.62, flip=True)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     width="{W}" height="{H}" role="img"
     aria-label="Illustration of {tea['name']}">
{defs(seed, accent)}
  <rect width="{W}" height="{H}" fill="{PAPER_DEEP}"/>
  <!-- a single hairline frame, in place of a card border -->
  <rect x="20" y="20" width="{W - 40}" height="{H - 40}" fill="none"
        stroke="{HAIRLINE}" stroke-width="1.5"/>
{decoration}
{body}
{second}
  <!-- category rule and swatch, bottom left -->
  <line x1="40" y1="{H - 56}" x2="150" y2="{H - 56}" stroke="{INK}"
        stroke-width="1.5"/>
  <circle cx="{W - 48}" cy="{H - 56}" r="9" fill="{accent}"/>
{grain_overlay(W, H)}
</svg>
"""


# ---------------------------------------------------------------------------
# Standalone images
# ---------------------------------------------------------------------------


def hero_svg() -> str:
    """
    The home page composition: a cup, seen at an angle, with steam and two
    sprigs. Tall, so it can sit beside the headline in a two-column grid.
    """
    accent = "#B5552F"
    width, height = 600, 800
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
     width="{width}" height="{height}" role="img"
     aria-label="Line illustration of a cup of tea with two sprigs of tea leaves">
{defs(7, accent)}
  <rect width="{width}" height="{height}" fill="{PAPER_DEEP}"/>
  <rect x="26" y="26" width="{width - 52}" height="{height - 52}" fill="none"
        stroke="{HAIRLINE}" stroke-width="1.5"/>

  <!-- horizon rule, which gives the objects somewhere to stand -->
  <line x1="26" y1="596" x2="{width - 26}" y2="596" stroke="{INK}"
        stroke-width="1.5"/>

{steam(300, 392, GREEN_DARK, 4)}

  <!-- saucer -->
  <ellipse cx="300" cy="582" rx="168" ry="26" fill="{PAPER}"/>
  <ellipse cx="300" cy="582" rx="168" ry="26" fill="none" stroke="{INK}"
           stroke-width="2.5"/>
  <ellipse cx="300" cy="578" rx="104" ry="16" fill="none" stroke="{HAIRLINE}"
           stroke-width="1.5"/>

  <!-- the tea itself -->
  <ellipse cx="300" cy="420" rx="118" ry="22" fill="{accent}"/>
  <ellipse cx="300" cy="418" rx="96" ry="15" fill="{PAPER}" opacity="0.18"/>

  <!-- cup wall -->
  <path d="M182 412 L418 412 C414 500 368 558 300 558
           C232 558 186 500 182 412 Z" fill="{PAPER}" opacity="0.35"/>
  <path d="M182 412 L418 412 C414 500 368 558 300 558
           C232 558 186 500 182 412 Z" fill="none" stroke="{INK}"
        stroke-width="3"/>
  <line x1="182" y1="412" x2="418" y2="412" stroke="{INK}" stroke-width="3"/>
  <!-- handle -->
  <path d="M418 440 C470 440 476 506 420 512" fill="none" stroke="{INK}"
        stroke-width="3" stroke-linecap="round"/>
  <!-- one band of colour on the cup, no shading -->
  <path d="M190 470 C214 478 386 478 410 470" fill="none" stroke="{accent}"
        stroke-width="4" opacity="0.8"/>

{sprig(506, 318, GREEN_DARK, 1.6)}
{sprig(92, 250, GREEN_DARK, 1.2, flip=True)}

{grain_overlay(width, height)}
</svg>
"""


def leaf_svg() -> str:
    """The small botanical mark used beside the wordmark."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"
     width="48" height="48" role="img" aria-label="Tea leaf mark">
  <path d="M24 44 C24 28 24 16 24 5" stroke="currentColor" stroke-width="2.2"
        fill="none" stroke-linecap="round"/>
  <path d="M24 30 C14 29 8 23 7 14 C17 14 23 20 24 30 Z" fill="currentColor"/>
  <path d="M24 22 C34 21 40 15 41 6 C31 6 25 12 24 22 Z" fill="currentColor"
        opacity="0.72"/>
</svg>
"""


def bowl_svg() -> str:
    """A bowl with steam, used as the brew guide's masthead image."""
    accent = "#B5552F"
    width, height = 420, 280
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
     width="{width}" height="{height}" role="img"
     aria-label="Illustration of a tea bowl with rising steam">
{defs(11, accent)}
  <rect width="{width}" height="{height}" fill="{PAPER_DEEP}"/>
{steam(210, 112, GREEN_DARK, 3)}
  <ellipse cx="210" cy="150" rx="96" ry="17" fill="{accent}"/>
  <path d="M114 148 L306 148 C303 196 265 232 210 232
           C155 232 117 196 114 148 Z" fill="none" stroke="{INK}"
        stroke-width="2.5"/>
  <line x1="114" y1="148" x2="306" y2="148" stroke="{INK}" stroke-width="2.5"/>
  <rect x="182" y="232" width="56" height="12" fill="{INK}"/>
  <line x1="40" y1="248" x2="380" y2="248" stroke="{HAIRLINE}" stroke-width="1.5"/>
{grain_overlay(width, height)}
</svg>
"""


def main() -> int:
    TEA_DIR.mkdir(parents=True, exist_ok=True)

    for index, tea in enumerate(TEAS):
        path = TEA_DIR / f"{tea['slug']}.svg"
        path.write_text(tea_svg(tea, seed=index + 1), encoding="utf-8")
    print(f"wrote {len(TEAS)} tea illustrations to {TEA_DIR.relative_to(ROOT)}")

    (IMG_DIR / "hero.svg").write_text(hero_svg(), encoding="utf-8")
    (IMG_DIR / "leaf.svg").write_text(leaf_svg(), encoding="utf-8")
    (IMG_DIR / "bowl.svg").write_text(bowl_svg(), encoding="utf-8")
    print("wrote hero.svg, leaf.svg, bowl.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
