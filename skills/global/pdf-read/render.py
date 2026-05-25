#!/usr/bin/env python3
"""PDF を全ページ PNG にレンダリングし、テキスト抽出も保存する。

Usage: render.py <input.pdf> <output_dir>

出力:
  <output_dir>/page-1.png, page-2.png, ...
  <output_dir>/pdfplumber-text.txt  (任意: pdfplumber が入っていれば)

ライセンス方針:
  - pypdfium2 (Apache 2.0 / BSD 3-clause) を使用
  - PyMuPDF (AGPL) は商用ライセンス影響があるため使わない
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium

ZOOM = 2.0  # 2x スケール (約 144 DPI 相当)


def render_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("page-*.png"):
        stale.unlink()
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages = []
    try:
        for i, page in enumerate(pdf, start=1):
            try:
                bitmap = page.render(scale=ZOOM)
                try:
                    pil_image = bitmap.to_pil()
                finally:
                    bitmap.close()
                png = out_dir / f"page-{i}.png"
                pil_image.save(png)
                pages.append(png)
                print(f"  page-{i}.png  {pil_image.width}x{pil_image.height}  ({png.stat().st_size:,} bytes)")
            finally:
                page.close()
    finally:
        pdf.close()
    return pages


def extract_text(pdf_path: Path, out_dir: Path) -> Path | None:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None

    out_file = out_dir / "pdfplumber-text.txt"
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            lines.append(f"=== PAGE {i} ===")
            text = page.extract_text() or "(no text)"
            lines.append(text)
            tables = page.extract_tables()
            for t_i, t in enumerate(tables, start=1):
                lines.append(f"-- TABLE {t_i} --")
                for row in t:
                    lines.append(str(row))
            lines.append("")
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: render.py <input.pdf> <output_dir>", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])

    print(f"[pdf-read] rendering {pdf_path} -> {out_dir}/")
    pages = render_pages(pdf_path, out_dir)
    text_file = extract_text(pdf_path, out_dir)

    print()
    print(f"--> {len(pages)} pages rendered to {out_dir}/")
    if text_file:
        print(f"--> text extracted to {text_file}")
    else:
        print("--> text extraction skipped (pdfplumber not available)")
    print()
    print("Next: Read each page-N.png with the Read tool for visual confirmation.")
    print("      Text extraction misses figures/SmartArt/charts -- always check the PNG.")


if __name__ == "__main__":
    main()
