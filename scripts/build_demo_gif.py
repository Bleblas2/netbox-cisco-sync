"""Zbuduj GIF ze screenshotów; wymaga Pillow."""

import argparse
from pathlib import Path

from PIL import GifImagePlugin, Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs/images"
OUTPUT = IMAGES / "netbox-cisco-sync-demo.gif"
STEP = 12
FRAME_MS = 200
START_MS = 3000
END_MS = 1000


def main():
    """Zachowaj skalę i przewijaj długie zdjęcia ze stałą prędkością 60 px/s."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", type=int, default=STEP)
    parser.add_argument("--frame-ms", type=int, default=FRAME_MS)
    parser.add_argument("--colors", type=int, default=64)
    args = parser.parse_args()
    if args.step <= 0 or args.frame_ms < 10 or args.frame_ms % 10 or not 2 <= args.colors <= 256:
        parser.error("Nieprawidłowy krok, czas klatki lub liczba kolorów")
    paths = sorted(IMAGES.glob("netbox-cisco-sync_*.jpeg"))
    if not paths:
        raise SystemExit("Brak screenshotów")
    with Image.open(paths[0]) as first:
        width, height = first.size
        background = first.convert("RGB").getpixel((width - 10, height - 10))
    temporary = OUTPUT.with_suffix(".gif.tmp")
    frames = 0
    total_ms = 0
    with temporary.open("wb") as output:
        for path in paths:
            with Image.open(path) as source:
                source = source.convert("RGB")
            if source.width != width:
                raise ValueError(f"Niezgodna szerokość: {path.name}")
            canvas = Image.new("RGB", (width, max(height, source.height)), background)
            canvas.paste(source, (0, 0))
            # Jedna paleta dla całego zdjęcia zapobiega migotaniu przy przewijaniu.
            indexed = canvas.quantize(colors=args.colors, method=Image.Quantize.MEDIANCUT,
                                      dither=Image.Dither.NONE)
            distance = canvas.height - height
            positions = list(range(0, distance + 1, args.step))
            if positions[-1] != distance:
                positions.append(distance)
            previous = None
            for index, top in enumerate(positions):
                frame = indexed.crop((0, top, width, top + height))
                if frames == 0:
                    header, _ = GifImagePlugin.getheader(frame, info={"loop": 0})
                    for block in header:
                        output.write(block)
                if distance == 0:
                    duration = END_MS
                elif index == 0:
                    duration = START_MS
                elif index == len(positions) - 1:
                    duration = END_MS
                else:
                    duration = round((positions[index + 1] - top) / args.step * args.frame_ms / 10) * 10
                # Zapis różnic zmniejsza rozmiar bez skalowania tekstu.
                bounds = None if previous is None else ImageChops.difference(frame, previous).getbbox()
                tile = frame if bounds is None else frame.crop(bounds)
                offset = (0, 0) if bounds is None else bounds[:2]
                for block in GifImagePlugin.getdata(tile, offset=offset, duration=duration,
                                                   disposal=1, include_color_table=True):
                    output.write(block)
                previous = frame
                frames += 1
                total_ms += duration
            print(f"{path.name}: scroll={distance}px", flush=True)
        output.write(b";")
    temporary.replace(OUTPUT)
    print(f"{OUTPUT}: {width}x{height}, {frames} frames, {total_ms / 1000:.2f}s")


if __name__ == "__main__":
    main()
