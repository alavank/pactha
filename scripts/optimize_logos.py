#!/usr/bin/env python3
"""Padrao de otimizacao de logos do PACTHA.

Redimensiona (lado maior <= MAX_DIM, mantendo proporcao e transparencia) e
recomprime cada logo, sem perda visivel — logos aparecem com ~56-80px, entao
512px ja e nitido ate em telas retina. SVG e ignorado (vetor, ja e leve).

Uso (rodar SEMPRE que uma logo nova chegar em frontend/public/):
    python scripts/optimize_logos.py [pasta]
"""
import sys
from pathlib import Path
from PIL import Image

MAX_DIM = 512
EXTS = {".png", ".jpg", ".jpeg"}
PUBLIC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "frontend" / "public"


def kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def main() -> None:
    total_before = total_after = 0
    for f in sorted(PUBLIC.iterdir()):
        if f.suffix.lower() not in EXTS:
            continue
        before = f.stat().st_size
        try:
            img = Image.open(f)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {f.name}: {e}")
            continue
        w0, h0 = img.size
        if max(w0, h0) > MAX_DIM:
            img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
        # Re-salva otimizado e sem metadata (nao propaga img.info/EXIF)
        if f.suffix.lower() == ".png":
            img.save(f, "PNG", optimize=True)  # preserva RGBA (transparencia)
        else:
            img.convert("RGB").save(f, "JPEG", quality=85, optimize=True, progressive=True)
        after = f.stat().st_size
        total_before += before
        total_after += after
        print(f"  {f.name}: {w0}x{h0} {kb(before)} -> {img.size[0]}x{img.size[1]} {kb(after)}")
    if total_before:
        pct = 100 * (1 - total_after / total_before)
        print(f"TOTAL: {kb(total_before)} -> {kb(total_after)} ({pct:.0f}% menor)")


if __name__ == "__main__":
    main()
