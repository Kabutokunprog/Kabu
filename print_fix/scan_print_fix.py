#!/usr/bin/env python3
"""
スキャンPDF(Genius Scan など)を、レーザープリンタで「かすれにくく」するプログラム。

やること:
  1. PDFからページ画像を取り出す(pdfimages を使用)
  2. 印刷解像度(既定 600dpi)まで、なめらかに拡大する
  3. 「まわりより はっきり暗い所」= 文字や線 だけを濃くする
     (うすいグレーの背景・ピンクの枠・裏写りは、まわりとの差が小さいので触らない)
  4. 文字をほんの少しだけ太らせる
  5. PDFに戻す

使い方:
  python3 scan_print_fix.py 入力.pdf 出力.pdf [--dpi 600] [--bold 1] [--color keep|black]

  --bold 0/1/2 : 太らせる強さ(0 = 太らせない)
  --color keep : 赤い文字は「濃い赤」にする(カラープリンタ向け、既定)
  --color black: 色文字も黒にする(白黒プリンタ向け。一番かすれにくい)
必要なもの: Python3, numpy, Pillow, poppler-utils(pdfimages)
"""
import argparse, glob, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None


def local_background(L_img: Image.Image) -> np.ndarray:
    """各場所の「まわりの紙の明るさ」を推定する(文字より十分大きい範囲の最大値)。"""
    w, h = L_img.size
    small = L_img.resize((max(1, w // 8), max(1, h // 8)), Image.BILINEAR)
    small = small.filter(ImageFilter.MaxFilter(5))   # 約 40px 四方で一番明るい所
    small = small.filter(ImageFilter.GaussianBlur(1.5))
    return np.asarray(small.resize((w, h), Image.BILINEAR), dtype=np.float32)


def fix_page(img: Image.Image, src_dpi: float, dpi: int, bold: int, color_mode: str) -> Image.Image:
    rgb_mode = img.mode != "L"
    img = img.convert("RGB" if rgb_mode else "L")

    # 1) 印刷解像度へ拡大(ギザギザを出さずに、細い線を太さ1ドット以上で描けるように)
    scale = dpi / src_dpi
    if scale > 1.05:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)

    arr = np.asarray(img, dtype=np.float32)
    L = arr if not rgb_mode else (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
    bg = local_background(Image.fromarray(L.clip(0, 255).astype(np.uint8)))

    # 2) まわりとの差(=インクの濃さ)
    d = np.clip(bg - L, 0, 255)
    # 差が 35 未満は触らない(裏写り・淡い背景色・紙のムラ)。
    # 差が 35〜110 で徐々に、110以上で「真っ黒」に寄せる。
    D0, D1 = 35.0, 110.0
    t = np.clip((d - D0) / (D1 - D0), 0, 1)
    t = t * t * (3 - 2 * t)                     # なめらかなつなぎ
    target = np.minimum(L, 255 - (d / D1) * 255)  # 差に応じた濃さ
    target = np.clip(target, 0, 255)
    newL = L + (np.minimum(target, L * 0.15) - L) * t   # 濃い所ほど黒へ

    # 3) 少しだけ太らせる(文字と判定された所の周りだけ)
    if bold > 0:
        size = 3 if bold == 1 else 5
        Limg = Image.fromarray(newL.clip(0, 255).astype(np.uint8))
        thick = np.asarray(Limg.filter(ImageFilter.MinFilter(size)), dtype=np.float32)
        mask = np.asarray(Image.fromarray((t > 0.5).astype(np.uint8) * 255)
                          .filter(ImageFilter.MaxFilter(size)), dtype=np.float32) / 255
        newL = newL + (np.minimum(newL, thick * 0.6 + newL * 0.4) - newL) * mask

    newL = newL.clip(0, 255)
    if not rgb_mode:
        return Image.fromarray(newL.astype(np.uint8), "L")

    # 4) 色の扱い
    if color_mode == "black":
        # 文字と判定された所はグレー(黒)に、それ以外は元の色のまま
        g = newL[..., None].repeat(3, axis=2)
        w = np.clip(t * 1.5, 0, 1)[..., None]
        out = arr * (1 - w) + g * w
        out = np.minimum(out, arr)  # 元より明るくはしない
    else:
        # 色文字は真っ黒にせず「濃い色」で止める(明るさ 40 を下限に)
        sat = arr.max(axis=2) - arr.min(axis=2)
        colored = np.clip((sat - 40) / 40, 0, 1)
        floorL = newL * (1 - colored) + np.maximum(newL, np.minimum(L, 40)) * colored
        ratio = np.where(L > 1, floorL / np.maximum(L, 1), 1)[..., None]
        out = arr * ratio                            # 色味を保ったまま暗く
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB")


def page_dpis(pdf):
    out = subprocess.run(["pdfimages", "-list", pdf], capture_output=True, text=True, check=True).stdout
    dpis = []
    for line in out.splitlines()[2:]:
        c = line.split()
        if len(c) > 13 and c[2] == "image":
            dpis.append(float(c[12]))
    return dpis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--bold", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--color", default="keep", choices=["keep", "black"])
    ap.add_argument("--quality", type=int, default=90)
    a = ap.parse_args()

    dpis = page_dpis(a.input)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdfimages", "-all", a.input, os.path.join(tmp, "p")], check=True)
        files = sorted(glob.glob(os.path.join(tmp, "p-*")))
        if len(files) != len(dpis):
            sys.exit("1ページ1枚の画像になっていないPDFには対応していません。")
        pages = []
        for i, (f, dpi) in enumerate(zip(files, dpis), 1):
            print(f"ページ {i}/{len(files)} を処理中 (元 {dpi:.0f}dpi → {a.dpi}dpi)")
            pages.append(fix_page(Image.open(f), dpi, a.dpi, a.bold, a.color))
        pages[0].save(a.output, save_all=True, append_images=pages[1:],
                      resolution=a.dpi, quality=a.quality, subsampling=0)
    print("完了:", a.output)


if __name__ == "__main__":
    main()
