"""Create a Windows shortcut (Sao.lnk) that launches the app with our
paw icon — and pins correctly to the taskbar.

WHY THIS EXISTS
  Running `python main.py` (or `py main.py`) makes Windows treat the
  process as python.exe, so the taskbar shows the Python logo and — worse
  — pinning pins *python.exe*, not our app.  The fix Windows actually
  honours is to launch from a .lnk shortcut that:
    • runs pythonw.exe (no console window) with main.py
    • has our app_icon.ico set as its IconLocation
    • carries the same AppUserModelID we set at runtime, so the live
      window groups under (and inherits the icon of) the shortcut.
  Pin THAT shortcut and the paw sticks.

USAGE
  py -3.12 tools/make_shortcut.py
  → writes Sao.lnk in the project root.  Double-click it to run; right-
    click → Pin to taskbar to pin with the paw icon.
"""
from __future__ import annotations

import os
import sys

APP_ID = 'Whishy.DesktopCat.Sao'   # must match main.py's AppUserModelID


def _pythonw_path() -> str:
    """pythonw.exe next to the current interpreter (no console window)."""
    d = os.path.dirname(sys.executable)
    pw = os.path.join(d, 'pythonw.exe')
    return pw if os.path.exists(pw) else sys.executable


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(root, 'main.py')
    icon = os.path.join(root, 'desktop_cat', 'app_icon.ico')
    lnk = os.path.join(root, 'Sao.lnk')
    pyw = _pythonw_path()

    if not os.path.exists(icon):
        print('app_icon.ico missing — run: py -3.12 tools/make_icon.py first')
        return 1

    # Build the .lnk via the Windows Script Host COM object (no extra deps).
    try:
        import win32com.client  # pywin32, already a project dependency
    except Exception as e:
        print(f'pywin32 not available ({e}); cannot create shortcut.')
        return 1

    shell = win32com.client.Dispatch('WScript.Shell')
    sc = shell.CreateShortcut(lnk)
    sc.TargetPath = pyw
    sc.Arguments = f'"{main_py}"'
    sc.WorkingDirectory = root
    sc.IconLocation = icon
    sc.WindowStyle = 7            # minimized launch (the GUI is frameless anyway)
    sc.Description = 'Sao — Desktop Cat'
    sc.Save()

    # Stamp the AppUserModelID onto the shortcut so a pinned copy groups
    # under the same identity as the running window (icon + grouping).
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        GPS_READWRITE = 0x00000002   # SHGetPropertyStoreFromParsingName flag
        store = propsys.SHGetPropertyStoreFromParsingName(
            lnk, None, GPS_READWRITE, propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID,
                       propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
        store.Commit()
    except Exception as e:
        # Non-fatal: the .lnk still works + shows the icon; only taskbar
        # grouping identity is slightly weaker without it.
        print(f'(note) could not stamp AppUserModelID on shortcut: {e}')

    print(f'wrote {lnk}')
    print('Double-click it to run.  Right-click the taskbar button -> '
          'Pin to taskbar to keep the paw icon.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
