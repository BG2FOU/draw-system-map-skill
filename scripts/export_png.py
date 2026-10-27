#!/usr/bin/env python3
"""Render a local SVG to PNG using optional CairoSVG or system librsvg/Pango."""
import argparse
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scale", type=float, default=2)
    parser.add_argument("--renderer", choices=["auto", "librsvg", "cairosvg"], default="auto")
    args = parser.parse_args()
    try:
        if not math.isfinite(args.scale) or args.scale <= 0:
            raise ValueError("scale must be a finite positive number")
        if args.input.resolve() == args.output.resolve() or args.output.suffix.lower() != ".png":
            raise ValueError("use a separate .png output path")
        root = ET.parse(args.input).getroot()
        viewbox = [float(v) for v in root.attrib["viewBox"].replace(",", " ").split()]
        if len(viewbox) != 4 or not all(math.isfinite(v) for v in viewbox) or min(viewbox[2:]) <= 0:
            raise ValueError("SVG needs a finite, positive viewBox")
        width, height = (max(1, math.ceil(v * args.scale)) for v in viewbox[2:])
        if width * height > 100_000_000:
            raise ValueError("PNG exceeds 100 million pixels; reduce --scale")
        backend = None
        if args.renderer in ("auto", "librsvg"):
            try:
                import gi
                gi.require_version("Rsvg", "2.0")
                from gi.repository import Rsvg
                backend = "librsvg"
            except (ImportError, ValueError):
                if args.renderer == "librsvg":
                    raise RuntimeError("librsvg needs system PyGObject and Rsvg 2.0")
        if backend is None:
            try:
                import cairosvg
                backend = "cairosvg"
            except ImportError:
                raise RuntimeError("PNG renderer unavailable: install CairoSVG with Cairo, or system PyGObject/librsvg. SVG remains usable.") from None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if backend == "librsvg":
            # Resize the vector viewport before rendering, not the bitmap afterward.
            root.set("width", str(width))
            root.set("height", str(height))
            ET.register_namespace("", "http://www.w3.org/2000/svg")
            handle = Rsvg.Handle.new_from_data(ET.tostring(root, encoding="utf-8"))
            pixbuf = handle.get_pixbuf()
            if pixbuf is None:
                raise RuntimeError("librsvg could not render this SVG")
            pixbuf.savev(str(args.output), "png", [], [])
        else:
            cairosvg.svg2png(url=str(args.input.resolve()), write_to=str(args.output), output_width=width, output_height=height)
        print(f"Exported {args.output}: {width} x {height}; renderer={backend}")
        return 0
    except (OSError, ValueError, KeyError, ET.ParseError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
