# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for Sao (Desktop Cat).
#
#   1. pip install pyinstaller            (PyInstaller >= 6 recommended)
#   2. py -3.12 -m PyInstaller Sao.spec
#   3. Result: a self-contained folder at  dist/Sao/  — run dist/Sao/Sao.exe
#      (zip the whole dist/Sao folder to share it).
#
# This is a ONE-FOLDER build on purpose: bundling Qt WebEngine (the hub UI)
# into a single .exe is unreliable, but the folder build "just works".

block_cipher = None

# ── Runtime data the app reads from disk ─────────────────────────────────────
datas = [
    ('desktop_cat/sprites',      'desktop_cat/sprites'),       # cat + flower + bug art
    ('desktop_cat/web',          'desktop_cat/web'),           # the Library Hub web UI
    ('desktop_cat/app_icon.ico', 'desktop_cat'),
    ('desktop_cat/app_icon.png', 'desktop_cat'),
]

# Imports PyInstaller can't see (dynamic / optional).
hiddenimports = [
    'win32gui', 'win32con', 'win32api', 'win32process', 'win32com',
    'uiautomation', 'comtypes',
    'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel', 'PyQt6.QtMultimedia',
    'winsdk',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Sao',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # no console window — it's an overlay
    icon='desktop_cat/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='Sao',
)
