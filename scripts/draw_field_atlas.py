"""Render the original vector compositions for FluxLake's field atlas."""

import math
import random
from pathlib import Path

WIDTH, HEIGHT = 900, 420
LAVENDER = "#c59af6"
MINT = "#87f6cb"
INK = "#171023"


def line(points, color=LAVENDER, opacity=0.7, width=1):
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-opacity="{opacity}" stroke-width="{width}"/>'


def shape(points, fill="url(#stone)", color=LAVENDER, opacity=0.55):
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{coords}" fill="{fill}" stroke="{color}" stroke-opacity="{opacity}"/>'


def curve(path, color=LAVENDER, opacity=0.7, width=1, fill="none"):
    return f'<path d="{path}" fill="{fill}" stroke="{color}" stroke-opacity="{opacity}" stroke-width="{width}"/>'


def ellipse(x, y, rx, ry, color=LAVENDER, opacity=0.65, rotation=0):
    return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="none" stroke="{color}" stroke-opacity="{opacity}" transform="rotate({rotation} {x} {y})"/>'


def dot(x, y, radius=2, color=MINT, opacity=0.85):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" opacity="{opacity}"/>'


def beam(path):
    return curve(path, MINT, 0.10, 9) + curve(path, MINT, 0.38, 3) + curve(path, MINT, 0.9)


def apertures():
    for x, y, size in [(390, 244, 92), (555, 206, 119), (714, 173, 79)]:
        for radius in range(12, size, 9):
            yield ellipse(x, y, radius, round(radius * 0.68), opacity=0.32, rotation=-28)
        yield ellipse(x, y, size, round(size * 0.68), MINT, 0.57, -28)
        yield dot(x, y, 3)
    yield beam("M99 336 390 244 555 206 714 173 871 102")


def funnel():
    for index in range(22):
        height = 50 + 14 * index
        end = 187 + index * 2
        yield curve(
            f"M89 {height} C308 {height} 377 {end} 587 {end} S760 {end} 865 {end}",
            MINT if index % 5 == 0 else LAVENDER,
            0.56,
        )
    for x, radius in [(390, 119), (490, 81), (585, 47)]:
        yield ellipse(x, 208, 35, radius, opacity=0.8, rotation=11)
    yield beam("M587 208H865")


def vault():
    for level in range(9):
        y = 103 + level * 28
        yield shape([(190, y + 64), (515, y - 42), (824, y + 21), (515, y + 110)])
        for index in range(1, 5):
            yield line(
                [(190 + 53 * index, y + 56 + 7 * index), (515 + 56 * index, y - 37 + 13 * index)],
                opacity=0.28,
            )
        yield dot(742, y + 42, 2 if level % 2 else 3)


def normalized():
    for row in range(11):
        for col in range(16):
            drift = max(0, 8 - col)
            x = 170 + col * 41 + drift * math.sin(row * 1.7 + col) * 2
            y = 67 + row * 27 + drift * math.cos(row + col) * 3
            yield dot(
                x, y, 2.6 if col > 9 else 1.4, MINT if row % 5 == 0 else LAVENDER, 0.55 + col / 42
            )
    for col in range(9, 16):
        yield line([(170 + col * 41, 50), (170 + col * 41, 355)], opacity=0.18)
    for row in range(11):
        yield line([(539, 67 + row * 27), (810, 67 + row * 27)], opacity=0.22)


def prism():
    yield shape([(510, 58), (694, 144), (680, 290), (506, 351), (341, 268), (349, 124)])
    yield shape([(510, 58), (694, 144), (506, 205), (349, 124)], "url(#aura)")
    yield shape([(506, 205), (694, 144), (680, 290), (506, 351)], "url(#aura)")
    yield beam("M108 286 506 205 784 77")
    for index in range(12):
        y = 109 + index * 17
        yield line(
            [(510, 207), (669, y), (854, y)], MINT if index % 4 == 0 else LAVENDER, 0.63, 1.1
        )


def canopy():
    yield beam("M162 212H319")
    for branch in range(7):
        y = 62 + branch * 49
        yield curve(f"M319 212C389 212 379 {y} 502 {y}", opacity=0.78)
        yield dot(502, y, 3)
        for leaf in (-14, 0, 14):
            x = 684 + (branch % 3) * 39
            yield curve(f"M502 {y} Q565 {y} 585 {y + leaf}H{x}", opacity=0.4)
            yield shape(
                [
                    (x, y + leaf - 3),
                    (x + 26, y + leaf - 3),
                    (x + 26, y + leaf + 3),
                    (x, y + leaf + 3),
                ],
                "url(#stone)",
                MINT,
            )


def ridges():
    for group, color in [(0, LAVENDER), (1, MINT)]:
        for row in range(15):
            points = []
            for x in range(130, 864, 8):
                crest = math.exp(-(((x - (420 + group * 160 + row * 8)) / (104 + group * 14)) ** 2))
                y = 141 + 11 * row - 138 * crest + group * 22
                points.append((x, y))
            yield line(points, color, 0.28 + row / 40)


def echo():
    for index in range(12):
        radius = 52 + index * 12
        x = 560 + index * 4
        y = 213 - index * 1.2
        yield ellipse(
            x, y, radius, round(radius * 0.65), MINT if index in (3, 9) else LAVENDER, 0.4, -24
        )
    yield beam(
        "M124 271 C281 271 334 231 424 202 S612 145 717 169 Q778 194 754 258 Q736 293 673 280 Q637 269 626 237"
    )
    for x, y in [(334, 231), (424, 202), (717, 169), (754, 258), (626, 237)]:
        yield dot(x, y, 3)


def isolation():
    for band in range(9):
        y = 45 + band * 38
        yield curve(f"M102 {y} C303 {y} 393 {y - 25} 530 {y}", opacity=0.35)
    yield curve("M539 20 Q594 116 559 222 Q519 332 575 406", MINT, 0.8, 2)
    for radius in range(26, 119, 14):
        yield ellipse(718, 219, radius, round(radius * 0.78), opacity=0.35, rotation=16)
    for x, y in [(685, 195), (714, 227), (759, 200), (741, 256), (777, 238)]:
        yield dot(x, y, 3, "#e6aa9e")


def cadence():
    for tier in range(5):
        y = 84 + tier * 61
        yield line([(139 + tier * 28, y), (865, y)], opacity=0.43)
        for index in range(12 - tier):
            x = 203 + tier * 28 + index * 48
            size = 11 + (index * 13 + tier * 7) % 34
            yield line([(x, y - size), (x, y + 11)], opacity=0.54)
            yield dot(x, y, 3 if (index + tier) % 4 == 0 else 1.6)
    yield beam("M203 84H344V145H468V206H592V267H716V328H864")


def thread():
    branches = [(175, 234), (337, 123), (491, 250), (661, 105), (832, 190)]
    for (x1, y1), (x2, y2) in zip(branches, branches[1:], strict=False):
        for offset in (-50, -25, 25, 50):
            yield curve(
                f"M{x1} {y1} Q{(x1 + x2) / 2} {(y1 + y2) / 2 + offset} {x2} {y2}", opacity=0.35
            )
    yield line(branches, MINT, 0.90, 2)
    for x, y in branches:
        yield ellipse(x, y, 19, 19, opacity=0.7)
        yield dot(x, y, 4)


def inquiry():
    for rotation in (-54, -28, -2, 24, 50):
        yield ellipse(615, 212, 201, 82, opacity=0.54, rotation=rotation)
    yield ellipse(615, 212, 167, 167, opacity=0.23)
    yield beam("M235 308 Q373 287 510 227 Q563 192 615 212")
    for x, y, r in [
        (615, 212, 8),
        (448, 142, 3),
        (753, 159, 4),
        (698, 323, 4),
        (573, 83, 2),
        (781, 220, 2),
    ]:
        yield dot(x, y, r)


def threshold():
    for depth in range(11):
        x = 245 + depth * 33
        y = 57 + depth * 13
        width = 471 - depth * 37
        yield curve(
            f"M{x} 362V{y + 70} Q{x} {y} {x + width / 2} {y} Q{x + width} {y} {x + width} {y + 70}V362Z",
            MINT if depth in (3, 10) else LAVENDER,
            0.55,
            1.1,
            "url(#stone)",
        )
    yield beam("M180 391 631 303 795 391")


def corridor():
    for index in range(15):
        x, y = 96 + index * 36, 30 + index * 11
        yield shape(
            [
                (x, y + 64),
                (x + 124, y),
                (882 - index * 17, y + 8),
                (882 - index * 17, 394 - index * 10),
                (x + 125, 388 - index * 10),
                (x, 324 - index * 10),
            ],
            "none",
            MINT if index % 5 == 0 else LAVENDER,
            0.55,
        )
    yield beam("M125 348Q405 329 638 204")


def core():
    base = [(513, 35), (746, 108), (808, 246), (666, 365), (392, 331), (286, 179)]
    center = (558, 209)
    for i, start in enumerate(base):
        end = base[(i + 1) % len(base)]
        yield shape([start, end, center], "url(#aura)" if i % 2 == 0 else "url(#stone)")
    for step in range(1, 10):
        t = step / 11
        points = [
            (center[0] + (x - center[0]) * t, center[1] + (y - center[1]) * t) for x, y in base
        ]
        yield shape(points, "none", MINT if step in (2, 8) else LAVENDER, 0.47)
    yield dot(*center, 5)


def fields():
    for row in range(6):
        for col in range(4):
            x, y = 225 + col * 143 + row * 9, 50 + row * 56
            yield shape([(x, y), (x + 123, y), (x + 113, y + 40), (x - 10, y + 40)], "url(#stone)")
            yield line(
                [(x + 16, y + 14), (x + 63 + (row + col) % 3 * 9, y + 14)],
                MINT if row == col else LAVENDER,
                0.74,
            )
            yield line([(x + 16, y + 27), (x + 49, y + 27)], opacity=0.35)
    yield beam("M197 76L252 327H812")


def pattern():
    for layer in range(21):
        y = 62 + layer * 14
        points = [
            (x, y + 32 * math.sin(x / 111 + layer / 13) - 49 * math.cos(x / 188))
            for x in range(146, 885, 8)
        ]
        yield line(points, MINT if layer in (6, 14) else LAVENDER, 0.34 + layer / 70)
    for x, y in [(364, 173), (495, 213), (632, 228), (760, 245)]:
        yield line([(x, y - 24), (x, y + 32)], MINT, 0.56)
        yield dot(x, y, 3.2)


def recovery():
    for row in range(13):
        y = 126 + row * 14
        yield curve(f"M109 {y}H335L391 {y - 44}L443 {y + 35}L483 {y - 12}", opacity=0.39)
        yield curve(
            f"M521 {y - 12}L565 {y + 24}L622 {y - 42}L686 {y}H861",
            MINT if row == 6 else LAVENDER,
            0.60,
        )
    yield curve("M502 54V368", MINT, 0.41)
    yield ellipse(502, 210, 33, 33, MINT, 0.75)
    yield dot(502, 210, 4)


def answer():
    points = [(251, 318), (408, 128), (574, 223), (699, 83), (812, 274)]
    for index, (x, y) in enumerate(points):
        yield ellipse(x, y, 27 + index * 4, 21 + index * 3, opacity=0.69, rotation=-21)
        yield dot(x, y, 3)
        yield curve(
            f"M{x} {y} C{x - 30} {y + 54} 619 320 574 223",
            MINT if index in (0, 3) else LAVENDER,
            0.61,
        )
    yield beam("M574 223 Q688 183 812 274")


COMPOSITIONS = {
    "source-apertures": apertures,
    "packet-funnel": funnel,
    "strata-vault": vault,
    "normalized-grid": normalized,
    "aggregate-prism": prism,
    "contract-canopy": canopy,
    "distribution-ridges": ridges,
    "replay-echo": echo,
    "isolated-pocket": isolation,
    "receipt-cadence": cadence,
    "evidence-thread": thread,
    "signal-inquiry": inquiry,
    "gated-threshold": threshold,
    "entry-corridor": corridor,
    "immutable-core": core,
    "observed-fields": fields,
    "pattern-ridges": pattern,
    "recovery-resonance": recovery,
    "inspectable-answer": answer,
}


def render(name, composition):
    rng = random.Random(name)
    sky = "".join(
        dot(
            rng.uniform(95, 886),
            rng.uniform(12, 406),
            rng.choice((0.7, 1.1, 1.5)),
            LAVENDER,
            rng.choice((0.17, 0.24, 0.43)),
        )
        for _ in range(67)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">'
        '<defs><radialGradient id="sky" cx="68%" cy="42%" r="72%">'
        '<stop stop-color="#41245b"/><stop offset=".61" stop-color="#20152f"/><stop offset="1" stop-color="#130f21"/>'
        '</radialGradient><linearGradient id="stone" x2=".7" y2="1"><stop stop-color="#3a2556"/><stop offset="1" stop-color="#1b132a"/></linearGradient>'
        '<linearGradient id="aura" x2="1" y2="1"><stop stop-color="#6e46a0" stop-opacity=".50"/><stop offset="1" stop-color="#28554f" stop-opacity=".26"/></linearGradient></defs>'
        '<path d="M0 0h900v420H0z" fill="url(#sky)"/>' + sky + "".join(composition()) + "</svg>\n"
    )


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "src/fluxlake/web/atlas"
    output.mkdir(exist_ok=True)
    for filename, composition in COMPOSITIONS.items():
        (output / f"{filename}.svg").write_text(
            render(filename, composition), encoding="utf-8", newline="\n"
        )
