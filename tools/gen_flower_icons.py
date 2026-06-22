import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtGui import QGuiApplication, QImage, QPixmap
from PyQt6.QtCore import Qt
app = QGuiApplication(sys.argv)
from desktop_cat.sprite_sheet import SpriteSheet
from desktop_cat.garden import FLOWER_NAMES, FLOWER_VARIANT_COUNT
sheet = SpriteSheet(scale=1)
if not sheet.load():
    print('FAILED to load sheet'); sys.exit(1)
outdir = os.path.join('desktop_cat', 'web', 'library', 'flowers')
os.makedirs(outdir, exist_ok=True)

def autocrop(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if img.pixelColor(x, y).alpha() > 8:
                minx = min(minx, x); miny = min(miny, y)
                maxx = max(maxx, x); maxy = max(maxy, y)
    if maxx < 0:
        return img
    return img.copy(minx, miny, maxx - minx + 1, maxy - miny + 1)

for v in range(FLOWER_VARIANT_COUNT):
    pix = sheet.growth_frame_pixmap(v, 99999)
    if pix is None or pix.isNull():
        print(f'variant {v}: NO PIXMAP'); continue
    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    img = autocrop(img)
    # scale up crisply (pixel art) so the icon reads at small sizes
    target = 64
    scaled = img.scaled(target, target, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation)
    path = os.path.join(outdir, f'flower_{v}.png')
    ok = scaled.save(path, 'PNG')
    print(f'variant {v} ({FLOWER_NAMES[v]}): {scaled.width()}x{scaled.height()} -> {path}  ok={ok}')
print('DONE')
