"""
LibraryHubWindow — Sao's Library UI (React) + Groq chat bridge.

QWebChannel exposes SaoBridge to the JS page so the chat input can call
Python (chat, vault ops, file ops, link graph, window controls).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime

# dotenv + groq removed in the 2026-05-28 AI-rip — the hub no longer
# talks to any LLM, so we don't need an API key in .env any more.

from PyQt6.QtCore import (
    Qt, QUrl, QObject, QThread, pyqtSignal, pyqtSlot, QFile, QIODevice,
    QPropertyAnimation, QEasingCurve, QEvent, QTimer,
)
from PyQt6.QtGui  import QCursor, QColor
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore   import QWebEngineSettings, QWebEngineScript
from PyQt6.QtWebChannel      import QWebChannel

# `import groq` removed — AI chat scrapped in the 2026-05-28 trim.

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'library')


# ── "Run on startup" — a HKCU\...\Run registry entry ─────────────────────────
_STARTUP_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
_STARTUP_APP_NAME = 'Sao'


def _startup_command() -> str:
    """The command Windows should run at login.  Uses the built Sao.exe when
    frozen, else launches main.py with pythonw (no console window)."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    main_py = os.path.join(os.path.dirname(_WEB_DIR), '..', '..', 'main.py')
    main_py = os.path.abspath(main_py)
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, 'pythonw.exe')
    launcher = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{launcher}" "{main_py}"'


def _is_run_on_startup() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_RUN_KEY) as k:
            winreg.QueryValueEx(k, _STARTUP_APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _set_run_on_startup(enabled: bool) -> None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, _STARTUP_APP_NAME, 0, winreg.REG_SZ,
                                  _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, _STARTUP_APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f'[run_on_startup] failed: {e}')


def _pick_index_html() -> str:
    """Path to the hub's HTML.  The whole UI is one Babel-transpiled bundle
    (`index.html` loads `xv5-ios-app.jsx` + `app-library.jsx`).  The old
    'production' path — compiled .js files built from the retired xv3/xv4/
    direction-3-v3 sources — was removed, so this is always the dev index."""
    return os.path.join(_WEB_DIR, 'index.html')
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'library_config.json')
_NOTE_EXTS   = {'.md', '.txt', '.markdown'}
_SAO_FOLDER  = 'Sao'                    # name of Sao's personal folder inside a vault
_SAO_JOURNAL_SUB = 'journal'            # observations subfolder
_SAO_DRAFTS_SUB  = 'drafts'             # drafts she writes for the user

# Window bg color (matches the Obsidian-light theme used by the JSX).
# Used everywhere so the window doesn't flash a different color on open.
_BG_HEX = '#eef3fa'   # V41 soft blue paper — matches V41.paper in the JSX

# ── wiki-link parsing ─────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r'\[\[([^\[\]\|#]+?)(?:#[^\[\]\|]*)?(?:\|[^\[\]]*)?\]\]')

def _parse_wikilinks(text: str) -> list[str]:
    """Return list of link target titles found in [[…]] markdown."""
    if not text:
        return []
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]


# ── vault tree ────────────────────────────────────────────────────────────────

def _read_vault_tree(vault_path: str) -> list:
    def walk(abs_path: str):
        books, filenames, mtimes, children = [], [], [], []
        try:
            entries = sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return None
        for entry in entries:
            if entry.name.startswith('.') or entry.name.startswith('_'):
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if entry.is_file() and ext in _NOTE_EXTS:
                books.append(os.path.splitext(entry.name)[0])
                filenames.append(entry.name)
                try:
                    mtimes.append(int(entry.stat().st_mtime))
                except Exception:
                    mtimes.append(0)
            elif entry.is_dir():
                child = walk(entry.path)
                if child is not None:
                    children.append(child)

        def count_total(n):
            return len(n['books']) + sum(count_total(c) for c in n['children'])

        node = {
            'id':        abs_path,
            'path':      abs_path,
            'name':      os.path.basename(abs_path) or abs_path,
            'books':     books,
            'filenames': filenames,
            'mtimes':    mtimes,
            'children':  children,
            'count':     len(books),
        }
        node['total'] = count_total(node)
        return node

    root = walk(vault_path)
    return [root] if root else []


def _vault_summary(tree: list) -> str:
    lines: list[str] = []
    def walk(node, depth):
        indent = '  ' * depth
        lines.append(f"{indent}📁 {node['name']}/  ({node['total']})")
        for fn in node.get('filenames', []):
            lines.append(f"{indent}   · {fn}")
        for child in node.get('children', []):
            walk(child, depth + 1)
    for n in tree:
        walk(n, 0)
    return '\n'.join(lines)


def _build_link_graph(tree: list, max_files: int = 500) -> dict:
    """Walk every note, parse [[wikilinks]], emit a graph keyed by abs note path.

    Returns: { abs_path: {'title': str, 'out': [abs_path or title], 'in': [abs_path]} }
    Each link target is resolved to an abs note path if a matching title exists;
    otherwise the raw title is kept (so we still know about dangling links).
    """
    # First pass: collect title → abs_path so we can resolve [[Title]] to a file.
    title_to_path: dict[str, str] = {}
    notes: list[tuple[str, str]] = []  # (abs_path, title)
    def collect(node):
        for fn, title in zip(node.get('filenames', []), node.get('books', [])):
            ap = os.path.join(node['path'], fn)
            if ap not in title_to_path:
                title_to_path[title.lower()] = ap
            notes.append((ap, title))
        for c in node.get('children', []):
            collect(c)
    for n in tree:
        collect(n)

    graph: dict = {ap: {'title': t, 'out': [], 'in': []} for ap, t in notes}

    # Second pass: parse links from each note (cap to avoid blowing up huge vaults).
    for ap, _title in notes[:max_files]:
        try:
            with open(ap, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(40000)
        except Exception:
            continue
        for raw in _parse_wikilinks(content):
            tgt = title_to_path.get(raw.lower(), raw)  # resolved path or raw title
            if tgt not in graph[ap]['out']:
                graph[ap]['out'].append(tgt)
            if tgt in graph:
                if ap not in graph[tgt]['in']:
                    graph[tgt]['in'].append(ap)
    return graph


# ── Tool schemas for Sao's agent loop ────────────────────────────────────────
# Groq follows the OpenAI tool-call format.  These describe the tools Sao
# can invoke; the implementations live on SaoBridge as _tool_* methods.
# Safety contract: no overwrite, no delete.  Sao can only search, read, list,
# create-new, and append.  Improving an existing note means creating a fuller
# version + appending a wiki-link on the original.

class SaoBridge(QObject):
    # Vault tree / link graph — emitted after the bridge walks the
    # connected vault folders.  Used by the React Settings panel to
    # show note counts and the (now-vault-only) class list.
    vaultLoaded     = pyqtSignal(str)
    linkGraphLoaded = pyqtSignal(str)
    # Kept dormant — focusNote/clearFocus still emit this so any future
    # listener can observe the focused-note name, but no one subscribes
    # in the trimmed UI.
    focusChanged    = pyqtSignal(str)
    # Fires when a floating StickyWindow writes a change (text / color /
    # transparency / drag / resize) back to stickies.json.  React's Stickies
    # tab subscribes and re-reads the full list via getStickies so the
    # in-hub representation stays in sync with the on-desktop pinned ones.
    stickiesUpdated = pyqtSignal()

    def __init__(self, window: 'LibraryHubWindow', parent=None):
        super().__init__(parent)
        self._window = window
        # Groq / chat plumbing removed in the 2026-05-28 AI-rip.  The
        # bridge now does file I/O, window controls, and vault tree walks.
        self._vault_paths:  list[str] = []
        self._vault_context: str      = ''
        self._focus_name:    str      = ''
        self._focus_content: str      = ''
        self._link_graph:    dict     = {}

        if os.path.exists(_CONFIG_PATH):
            try:
                with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                paths = cfg.get('vault_paths')
                if not paths and cfg.get('vault_path'):
                    paths = [cfg['vault_path']]
                self._vault_paths = [p for p in (paths or []) if isinstance(p, str) and os.path.isdir(p)]
            except Exception:
                pass

    def _save_config(self) -> None:
        try:
            # Preserve any keys we don't manage here (canvas_url etc.)
            existing = {}
            if os.path.exists(_CONFIG_PATH):
                try:
                    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                        existing = json.load(f) or {}
                except Exception:
                    existing = {}
            existing['vault_paths'] = self._vault_paths
            with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2)
        except Exception:
            pass

    def _is_in_vault(self, abs_path: str) -> bool:
        try:
            ap = os.path.realpath(abs_path)
        except Exception:
            return False
        for vp in self._vault_paths:
            try:
                vp_real = os.path.realpath(vp)
            except Exception:
                continue
            if ap == vp_real or ap.startswith(vp_real + os.sep):
                return True
        return False

    def _ensure_sao_folder(self) -> str:
        """Return the path to Sao's writing folder, creating it if needed.
        Lives inside the FIRST connected vault, under ./Sao/.
        Returns '' if no vault is connected."""
        if not self._vault_paths:
            return ''
        root = os.path.join(self._vault_paths[0], _SAO_FOLDER)
        try:
            os.makedirs(os.path.join(root, _SAO_DRAFTS_SUB), exist_ok=True)
            os.makedirs(os.path.join(root, _SAO_JOURNAL_SUB), exist_ok=True)
        except Exception:
            pass
        return root


    # ── Vault ─────────────────────────────────────────────────────────────────

    def _emit_vault_tree(self) -> None:
        all_nodes: list = []
        for vp in list(self._vault_paths):
            if os.path.isdir(vp):
                all_nodes.extend(_read_vault_tree(vp))
        self._vault_context = _vault_summary(all_nodes)
        names = [os.path.basename(p) or p for p in self._vault_paths]
        payload = json.dumps({
            'hasVault':  len(self._vault_paths) > 0,
            'vaultName': ' · '.join(names),
            'tree':      all_nodes,
        })
        self.vaultLoaded.emit(payload)
        # link graph (sent separately so the UI loads fast first)
        try:
            graph = _build_link_graph(all_nodes)
            self._link_graph = graph
            self.linkGraphLoaded.emit(json.dumps(graph))
        except Exception:
            pass

    @pyqtSlot()
    def getVaultTree(self) -> None:
        self._emit_vault_tree()

    @pyqtSlot()
    def requestVaultFolder(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(
            None, "Choose a folder to add to your library",
            os.path.expanduser('~'), QFileDialog.Option.ShowDirsOnly,
        )
        if not path or path in self._vault_paths:
            return
        self._vault_paths.append(path)
        self._save_config()
        self._ensure_sao_folder()
        self._emit_vault_tree()

    @pyqtSlot(str)
    def setHighlightFlower(self, todo_id: str) -> None:
        """Hub hover over a to-do → highlight (yellow) its taskbar flower."""
        try:
            from desktop_cat import pin_registry
            o = pin_registry.get_overlay()
            if o is not None and hasattr(o, 'set_highlight_flower'):
                o.set_highlight_flower(todo_id or '')
        except Exception:
            pass

    @pyqtSlot(result=str)
    def getScreenSize(self) -> str:
        """Return the primary screen's logical size as JSON {w, h, floor}.

        The placement picker in the library uses this to render a
        proportionally-correct mini map of the desktop so the user can pick
        a real on-screen point to drop a potato block.  `floor` is the
        y-coordinate of the top of the taskbar — anything below it would
        spawn behind the taskbar and never be reachable.
        """
        try:
            from PyQt6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen()
            if scr is None:
                return json.dumps({'w': 1536, 'h': 1024, 'floor': 984})
            geo = scr.availableGeometry()   # excludes taskbar
            full = scr.geometry()
            return json.dumps({
                'w':     int(full.width()),
                'h':     int(full.height()),
                'floor': int(geo.y() + geo.height()),
            })
        except Exception:
            return json.dumps({'w': 1536, 'h': 1024, 'floor': 984})

    # ── Canvas iCal ──────────────────────────────────────────────────────
    # User pastes their Canvas calendar feed URL once.  We persist it in
    # library_config.json next to the vault paths.  Actual fetching is
    # done by syncCanvas() (parsing is in a future pass).
    @pyqtSlot(str)
    def setCanvasURL(self, url: str) -> None:
        try:
            cfg = {}
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
            cfg['canvas_url'] = (url or '').strip()
            with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    @pyqtSlot(result=str)
    def getCanvasURL(self) -> str:
        try:
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
                return (cfg.get('canvas_url') or '').strip()
        except Exception:
            pass
        return ''

    @pyqtSlot(result=str)
    def syncCanvas(self) -> str:
        """Fetch the Canvas iCal feed, parse/classify every VEVENT, and
        persist the result.  Returns a summary the settings card can show:
        how many events/todos/projects were added since the last sync,
        what the totals are now, and when the sync ran.

        Subscription URL — the user only pastes it once.  We can call this
        again later to pick up new assignments.
        """
        from desktop_cat import canvas_sync
        url = self.getCanvasURL()
        a_days, p_days = self._lookahead_days()
        return json.dumps(canvas_sync.run_sync(url, a_days, p_days))

    def _lookahead_days(self) -> tuple[int, int]:
        """(assignment_days, project_days) from config; sane defaults."""
        a, p = 7, 14
        try:
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
                a = int(cfg.get('lookahead_assignment_days', 7))
                p = int(cfg.get('lookahead_project_days', 14))
        except Exception:
            pass
        return max(1, min(120, a)), max(1, min(180, p))

    @pyqtSlot(result=str)
    def getLookahead(self) -> str:
        a, p = self._lookahead_days()
        return json.dumps({'assignment_days': a, 'project_days': p})

    @pyqtSlot(int, int)
    def setLookahead(self, assignment_days: int, project_days: int) -> None:
        try:
            cfg = {}
            if os.path.exists(_CONFIG_PATH):
                with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
            cfg['lookahead_assignment_days'] = max(1, min(120, int(assignment_days)))
            cfg['lookahead_project_days']    = max(1, min(180, int(project_days)))
            with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f'[setLookahead] {e}')

    @pyqtSlot(result=str)
    def getCanvasEvents(self) -> str:
        """All Canvas-sourced calendar events (kind='event')."""
        try:
            from desktop_cat import canvas_sync
            return json.dumps(canvas_sync.events_by_kind('event'))
        except Exception:
            return json.dumps([])

    @pyqtSlot(result=str)
    def getCanvasTodos(self) -> str:
        """All Canvas-sourced work items (assignments + projects) — the
        hub's to-do list is the only surface, so it gets both."""
        try:
            from desktop_cat import canvas_sync
            return json.dumps(canvas_sync.all_work_items())
        except Exception:
            return json.dumps([])

    @pyqtSlot(result=str)
    def getLibraryTodos(self) -> str:
        """Full list as last persisted to library_todos.json — the merged
        view (Canvas + manual additions) that the React UI works with.
        Added for the iOS port (xv5-ios-app.jsx) which uses this file as
        its single source of truth instead of merging in JS.
        """
        import os
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..',
            'library_todos.json',
        )
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return json.dumps(data if isinstance(data, list) else [])
        except (OSError, ValueError):
            return json.dumps([])

    @pyqtSlot(result=str)
    def getCanvasProjects(self) -> str:
        """All Canvas-sourced multi-day work (kind='project')."""
        try:
            from desktop_cat import canvas_sync
            return json.dumps(canvas_sync.events_by_kind('project'))
        except Exception:
            return json.dumps([])

    @pyqtSlot(result=str)
    def getIslandPrefs(self) -> str:
        """Return the dynamic-island prefs JSON for the Settings panel."""
        try:
            from desktop_cat import island_data
            return json.dumps(island_data.load())
        except Exception:
            return '{}'

    @pyqtSlot(str)
    def saveIslandPrefs(self, prefs_json: str) -> None:
        """Persist island prefs from the Settings panel.  The running
        island mtime-polls the file and reloads."""
        try:
            data = json.loads(prefs_json or '{}')
            if not isinstance(data, dict):
                return
            from desktop_cat import island_data
            island_data.save(data)
        except Exception as e:
            print(f'[saveIslandPrefs] failed: {e}')

    # ── World settings (flowers / rocks / Sao decor) ──────────────────
    # Stored in desktop_cat/world_settings.json.  main.py mtime-polls the
    # file and live-applies changes (flowers_hidden, rocks_hidden, etc.).
    def _world_settings_path(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'desktop_cat', 'world_settings.json',
        )

    # ── Window pinning (always-on-top for arbitrary OS windows) ───────
    @pyqtSlot()
    def armPinMode(self) -> None:
        """Arm 'pin next window' — the next left-click on any real window
        (or its taskbar button) pins it always-on-top.  Engine lives in
        main.py's PinManager.  We deliberately DO NOT close the hub here:
        the hub and Sao's own windows are ignored by the PinManager, so
        leaving it open is harmless, and the user can pin a target either
        by clicking its visible edge or by clicking its taskbar icon."""
        try:
            from desktop_cat import pin_registry
            pm = pin_registry.get_pin_manager()
            if pm is not None:
                pm.activate_pin_mode()
        except Exception as e:
            print(f'[armPinMode] {e}')

    @pyqtSlot()
    def feedMacaron(self) -> None:
        """Drop a macaron treat onto the desktop for Sao to chase + eat.
        (The overlay owns the treat; main spawns + animates it.)"""
        try:
            from desktop_cat import pin_registry
            ov = pin_registry.get_overlay()
            if ov is not None and hasattr(ov, 'request_feed'):
                ov.request_feed()
        except Exception as e:
            print(f'[feedMacaron] {e}')

    @pyqtSlot()
    def spawnBall(self) -> None:
        """Drop a bouncy beach ball onto the desktop for Sao to bat around."""
        try:
            from desktop_cat import pin_registry
            ov = pin_registry.get_overlay()
            if ov is not None and hasattr(ov, 'request_ball'):
                ov.request_ball()
        except Exception as e:
            print(f'[spawnBall] {e}')

    @pyqtSlot(result=str)
    def getPinnedWindows(self) -> str:
        """[{hwnd, title}, ...] of currently-pinned windows for Settings."""
        try:
            from desktop_cat import pin_registry
            pm = pin_registry.get_pin_manager()
            if pm is None:
                return '[]'
            return json.dumps(pm.pinned_list())
        except Exception:
            return '[]'

    @pyqtSlot(int)
    def removePin(self, hwnd: int) -> None:
        """Unpin a single window by hwnd."""
        try:
            from desktop_cat import pin_registry
            pm = pin_registry.get_pin_manager()
            if pm is not None:
                pm.unpin(int(hwnd))
        except Exception as e:
            print(f'[removePin] {e}')

    @pyqtSlot(result=str)
    def getWorldSettings(self) -> str:
        """Return world_settings.json for the Settings panel."""
        try:
            with open(self._world_settings_path(), 'r', encoding='utf-8') as f:
                return f.read() or '{}'
        except Exception:
            return '{}'

    @pyqtSlot(str)
    def saveWorldSettings(self, settings_json: str) -> None:
        """Merge + persist world settings from the Settings panel.  Merges
        into the existing file so we don't clobber keys the panel doesn't
        manage (personality, pomo_display_mode, etc.)."""
        try:
            patch = json.loads(settings_json or '{}')
            if not isinstance(patch, dict):
                return
            path = self._world_settings_path()
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cur = json.load(f)
                if not isinstance(cur, dict):
                    cur = {}
            except Exception:
                cur = {}
            cur.update(patch)
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cur, f, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            print(f'[saveWorldSettings] failed: {e}')

    @pyqtSlot(result=bool)
    def getLaunchAtLogin(self) -> bool:
        """Is Sao currently set to start when Windows logs in?"""
        return _is_run_on_startup()

    @pyqtSlot(bool)
    def setLaunchAtLogin(self, enabled: bool) -> None:
        """Add / remove the Windows startup entry for Sao."""
        _set_run_on_startup(bool(enabled))

    @pyqtSlot(result=str)
    def getStickies(self) -> str:
        """Return the on-disk sticky list as JSON.  React reads this on
        Stickies-tab mount + after stickiesUpdated fires (which Python
        emits whenever a floating sticky writes back an edit)."""
        try:
            from desktop_cat import stickies_data
            return json.dumps(stickies_data.load())
        except Exception:
            return '[]'

    @pyqtSlot(str)
    def saveStickies(self, stickies_json: str) -> None:
        """Persist the full sticky list (React → disk).  StickyManager in
        main.py polls mtime on stickies.json and reconciles floating
        windows whenever this fires."""
        try:
            data = json.loads(stickies_json or '[]')
        except Exception as e:
            print(f'[saveStickies] bad JSON: {e}')
            return
        if not isinstance(data, list):
            print(f'[saveStickies] expected list, got {type(data).__name__}')
            return
        try:
            from desktop_cat import stickies_data
            stickies_data.save(data)
        except Exception as e:
            print(f'[saveStickies] save threw: {e}')

    @pyqtSlot(str)
    def saveLibraryTodos(self, todos_json: str) -> None:
        """Persist the React Todo list to library_todos.json so main.py
        can reconcile it against task_flowers — when a new todo appears
        here, main.py queues Sao to walk over and plant a flower for it;
        when a todo flips done, the matching flower wilts; when one is
        deleted, the flower disappears.

        Format: a JSON array of slim todo records:
            [{id, name, due, done, source}, ...]
        """
        try:
            data = json.loads(todos_json or '[]')
            if not isinstance(data, list):
                return
            # Slim the payload — we only need a few fields on the Python side.
            slim = []
            for t in data:
                if not isinstance(t, dict) or not t.get('id'):
                    continue
                slim.append({
                    'id':       str(t.get('id')),
                    'name':     str(t.get('name') or ''),
                    'due':      str(t.get('due') or '') or None,
                    'done':     bool(t.get('done')),
                    'source':   str(t.get('source') or 'manual'),
                    'priority': str(t.get('priority') or 'normal'),
                    # Chosen flower variant (0..4) from the composer; -1 = random.
                    'flower':   (int(t['flower'])
                                 if isinstance(t.get('flower'), (int, float)) else -1),
                    # Completion day (YYYY-MM-DD) so "done today" survives reloads.
                    'completedAt': (str(t.get('completedAt'))
                                    if t.get('completedAt') else None),
                })
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(project_root, 'library_todos.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(slim, f, indent=2)
        except Exception:
            # Best-effort — never crash the chat over a sync write.
            pass

    @pyqtSlot(result=str)
    def getCanvasSyncSummary(self) -> str:
        """Persisted summary of the most recent sync, for the settings card.

        Returns last_sync timestamp + per-kind totals.  If we've never
        synced, returns {synced: False}.
        """
        try:
            from desktop_cat import canvas_sync
            state = canvas_sync.load_state()
            if not state.get('last_sync'):
                return json.dumps({'synced': False})
            evs = state.get('events', [])
            totals = {'event': 0, 'todo': 0, 'project': 0}
            for e in evs:
                k = e.get('kind', 'event')
                totals[k] = totals.get(k, 0) + 1
            return json.dumps({
                'synced':    True,
                'last_sync': state['last_sync'],
                'totals':    totals,
            })
        except Exception:
            return json.dumps({'synced': False})

    @pyqtSlot(str)
    def setSaoPrefs(self, _json_str: str) -> None:
        """No-op stub — Sao AI was removed in 2026-05-28.  Settings
        panel still calls this on save; we just accept and ignore."""
        return

    @pyqtSlot(str)
    def observeInterfaceEvent(self, _json_str: str) -> None:
        """No-op stub — used to feed events into Sao's context.  Kept so
        legacy JSX callers (e.g. on todo add) don't error out."""
        return

    @pyqtSlot(str, result=bool)
    def deleteNote(self, abs_path: str) -> bool:
        """Delete a single note from disk.  Only allowed inside a tracked
        vault.  Returns True on success.  Triggers a tree re-emit."""
        if not self._is_in_vault(abs_path):
            return False
        try:
            if os.path.isfile(abs_path):
                os.remove(abs_path)
                self._emit_vault_tree()
                return True
        except Exception:
            pass
        return False

    @pyqtSlot(str, result=bool)
    def deleteNotes(self, paths_json: str) -> bool:
        """Bulk-delete a list of notes — accepts a JSON-encoded list of
        absolute paths.  Returns True if at least one was deleted."""
        try:
            paths = json.loads(paths_json)
        except Exception:
            return False
        ok = False
        for p in paths or []:
            if not isinstance(p, str): continue
            if not self._is_in_vault(p): continue
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    ok = True
            except Exception:
                pass
        if ok:
            self._emit_vault_tree()
        return ok

    @pyqtSlot(result=str)
    def createNewNote(self) -> str:
        """Create an untitled-N.md file at the root of the FIRST vault and
        return its absolute path.  Front-end then focuses it.  Empty string
        if no vault is connected."""
        if not self._vault_paths:
            return ''
        root = self._vault_paths[0]
        # Find next free 'untitled-N.md'
        n = 1
        while True:
            candidate = os.path.join(root, f'untitled-{n}.md' if n > 1 else 'untitled.md')
            if not os.path.exists(candidate):
                break
            n += 1
        try:
            with open(candidate, 'w', encoding='utf-8') as f:
                f.write('# untitled\n\n')
            # refresh the tree so the new note shows up
            self._emit_vault_tree()
            return candidate
        except Exception:
            return ''

    @pyqtSlot()
    def clearSaoMemory(self) -> None:
        """No-op stub — chat history no longer exists.  Settings panel
        still wires a 'Clear sao memory' button that calls this."""
        return

    @pyqtSlot(str, result=bool)
    def removeVault(self, path: str) -> bool:
        """Forget one vault folder by path.  Files on disk are untouched.
        Returns True if the path was tracked."""
        try:
            target = os.path.realpath(path)
        except Exception:
            return False
        before = len(self._vault_paths)
        self._vault_paths = [
            p for p in self._vault_paths
            if (lambda r: r != target)(os.path.realpath(p) if os.path.exists(p) else p)
        ]
        if len(self._vault_paths) != before:
            self._save_config()
            self._emit_vault_tree()
            return True
        return False

    @pyqtSlot()
    def clearVaults(self) -> None:
        """Forget every connected vault folder.  Triggers a re-emit so the
        UI flips back to the onboarding screen.  Used by 'reset onboarding'
        actions from the front end.  The folders themselves are untouched."""
        self._vault_paths = []
        self._vault_context = ''
        self._save_config()
        self._emit_vault_tree()

    @pyqtSlot(str, result=str)
    def readNote(self, abs_path: str) -> str:
        if not self._is_in_vault(abs_path):
            return ''
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read(12000)
        except Exception:
            return ''

    @pyqtSlot(str)
    def openNote(self, abs_path: str) -> None:
        """Open a note in Obsidian if available, falling back to system default."""
        if not self._is_in_vault(abs_path):
            return
        # 1) Try the Obsidian URI scheme — opens in whichever vault contains the file.
        try:
            uri = 'obsidian://open?path=' + urllib.parse.quote(abs_path, safe='')
            opened = os.startfile  # marker — we use ShellExecute below
            # ShellExecuteW returns >32 on success.
            res = ctypes.windll.shell32.ShellExecuteW(None, 'open', uri, None, None, 1)
            if res > 32:
                return
        except Exception:
            pass
        # 2) Fall back to OS default app
        try:
            os.startfile(abs_path)
        except Exception:
            pass

    @pyqtSlot(str)
    def focusNote(self, abs_path: str) -> None:
        if not abs_path:
            self._focus_name = ''
            self._focus_content = ''
            self.focusChanged.emit('')
            return
        if not self._is_in_vault(abs_path):
            return
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                self._focus_content = f.read(12000)
            self._focus_name = os.path.basename(abs_path)
            self.focusChanged.emit(self._focus_name)
        except Exception:
            pass

    @pyqtSlot()
    def clearFocus(self) -> None:
        self.focusNote('')

    @pyqtSlot(str, str, result=str)
    def createNote(self, parent_abs_path: str, name: str) -> str:
        if not name.strip() or not self._is_in_vault(parent_abs_path) or not os.path.isdir(parent_abs_path):
            return ''
        name = name.strip()
        if not os.path.splitext(name)[1]:
            name += '.md'
        new_path = os.path.join(parent_abs_path, name)
        if os.path.exists(new_path):
            return ''
        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(f'# {os.path.splitext(name)[0]}\n\n')
            self._emit_vault_tree()
            return new_path
        except Exception:
            return ''

    @pyqtSlot(str, str, result=bool)
    def saveNote(self, abs_path: str, text: str) -> bool:
        """User-initiated save from the in-window editor. Writes anywhere
        inside any linked vault. Distinct from `writeNote` (Sao-only, restricted
        to Sao/ folder) — this one is gated only by `_is_in_vault`."""
        if not self._is_in_vault(abs_path):
            return False
        try:
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(text)
            # Don't re-emit the whole tree (would reset UI state) — link graph
            # may be stale until next refresh, which is an acceptable tradeoff.
            return True
        except Exception:
            return False

    @pyqtSlot(str, str, result=bool)
    def appendNote(self, abs_path: str, text: str) -> bool:
        if not self._is_in_vault(abs_path):
            return False
        try:
            with open(abs_path, 'a', encoding='utf-8') as f:
                f.write('\n' + text + '\n')
            return True
        except Exception:
            return False

    @pyqtSlot(str, str, result=bool)
    def writeNote(self, abs_path: str, text: str) -> bool:
        """Full replacement write — for when Sao authors / regenerates a note. Only
        valid inside Sao/ to prevent accidental clobbering of the user's notes."""
        if not self._is_in_vault(abs_path):
            return False
        sao_root = self._ensure_sao_folder()
        if not sao_root or not os.path.realpath(abs_path).startswith(os.path.realpath(sao_root) + os.sep):
            return False
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(text)
            self._emit_vault_tree()
            return True
        except Exception:
            return False

    @pyqtSlot(str, str, result=str)
    def createFolder(self, parent_abs_path: str, name: str) -> str:
        if not name.strip() or not self._is_in_vault(parent_abs_path) or not os.path.isdir(parent_abs_path):
            return ''
        new_path = os.path.join(parent_abs_path, name.strip())
        if os.path.exists(new_path):
            return ''
        try:
            os.makedirs(new_path)
            self._emit_vault_tree()
            return new_path
        except Exception:
            return ''

    @pyqtSlot(str, str, result=str)
    def draftLinkedNote(self, source_abs_path: str, title: str) -> str:
        """Create a new note in Sao/drafts/ that includes a [[backlink]] to source.
        Returns the new note's abs path on success, '' otherwise."""
        sao_root = self._ensure_sao_folder()
        if not sao_root:
            return ''
        drafts = os.path.join(sao_root, _SAO_DRAFTS_SUB)
        os.makedirs(drafts, exist_ok=True)
        clean = title.strip().replace('/', '-')
        if not clean:
            clean = 'untitled'
        if not os.path.splitext(clean)[1]:
            clean += '.md'
        new_path = os.path.join(drafts, clean)
        if os.path.exists(new_path):
            base, ext = os.path.splitext(new_path)
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            new_path = f'{base} {stamp}{ext}'
        backlink = ''
        if source_abs_path and self._is_in_vault(source_abs_path):
            src_title = os.path.splitext(os.path.basename(source_abs_path))[0]
            backlink = f'\n\n*linked from [[{src_title}]]*\n'
        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                heading = os.path.splitext(os.path.basename(new_path))[0]
                f.write(f'# {heading}\n{backlink}\n')
            self._emit_vault_tree()
            return new_path
        except Exception:
            return ''

    # ── Window controls ───────────────────────────────────────────────────────

    @pyqtSlot()
    def startWindowDrag(self) -> None:
        if sys.platform != 'win32':
            return
        hwnd = int(self._window.winId())
        pos = QCursor.pos()
        lParam = ctypes.c_long(pos.y() * 65536 + pos.x()).value
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.PostMessageW(hwnd, 0xA1, 2, lParam)

    @pyqtSlot()
    def windowMinimize(self) -> None:
        if sys.platform != 'win32':
            self._window.showMinimized()
            return
        hwnd = int(self._window.winId())
        ctypes.windll.user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE

    @pyqtSlot()
    def windowToggleMax(self) -> None:
        if sys.platform != 'win32':
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            return
        hwnd = int(self._window.winId())
        if ctypes.windll.user32.IsZoomed(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 3)   # SW_MAXIMIZE

    @pyqtSlot()
    def windowClose(self) -> None:
        self._window.close_animated()


# ── Event filter to swallow browser-zoom (Ctrl+wheel, Ctrl ± / 0) ─────────────

class _NoZoomEventFilter(QObject):
    """Block browser-level zoom (Ctrl ± / 0) but DO NOT swallow Ctrl+Wheel —
    the library map's JS canvas needs Ctrl+Wheel + trackpad pinch (which
    Chromium delivers as Ctrl+Wheel events) to zoom the bookshelf view."""
    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.KeyPress and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            k = event.key()
            if k in (Qt.Key.Key_Plus, Qt.Key.Key_Minus, Qt.Key.Key_Equal, Qt.Key.Key_0):
                return True
        return False


# ── Main window ───────────────────────────────────────────────────────────────

class LibraryHubWindow(QMainWindow):

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint,
        )
        self.setWindowTitle("Sao's Library")
        # Use the paw app icon for this window's taskbar entry (otherwise the
        # frameless window falls back to the default Python icon).
        try:
            from PyQt6.QtGui import QIcon
            _ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'app_icon.ico')
            if os.path.exists(_ico):
                self.setWindowIcon(QIcon(_ico))
        except Exception:
            pass
        # Compact widget size — the hub is intentionally small now (post the
        # 2026-05-28 trim).  Todo + Stickies live inside, everything else is
        # a corner-icon overlay.  Resizable but defaults narrow.
        self.resize(456, 668)
        self.setMinimumSize(400, 500)

        # Set background to theme color so the window doesn't flash white on open
        self.setStyleSheet(f"QMainWindow, QWidget#central {{ background: {_BG_HEX}; }}")

        self._closing     = False
        self._shadow_done = False

        self._bridge  = SaoBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject('saoBridge', self._bridge)

        central = QWidget()
        central.setObjectName('central')
        self.setCentralWidget(central)
        lo = QVBoxLayout(central)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._view = QWebEngineView()
        self._view.setStyleSheet(f"background: {_BG_HEX};")
        page = self._view.page()
        page.setBackgroundColor(QColor(_BG_HEX))

        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,   True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # Enable localStorage so xv3_prefs / xv3_todos / xv3_events / etc.
        # survive a relaunch.  Without this the in-memory default profile
        # wipes everything on close.
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        try:
            profile = page.profile()
            from PyQt6.QtWebEngineCore import QWebEngineProfile
            # Point the profile at a stable on-disk location next to library_config.json
            storage_dir = os.path.join(os.path.dirname(_CONFIG_PATH), 'webstorage')
            os.makedirs(storage_dir, exist_ok=True)
            profile.setPersistentStoragePath(storage_dir)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
            # Don't HTTP-cache the local hub assets — otherwise edited JSX/CSS
            # keeps serving a stale copy and changes never appear.  (localStorage
            # is separate and still persists.)
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
            try:
                profile.clearHttpCache()
            except Exception:
                pass
        except Exception:
            pass

        page.setWebChannel(self._channel)
        self._inject_qwebchannel_js(page)

        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        lo.addWidget(self._view)

        # Install zoom-blocker on the WebView's focus proxy (the underlying child widget).
        self._no_zoom = _NoZoomEventFilter(self)
        self._view.installEventFilter(self._no_zoom)
        QTimer.singleShot(0, self._install_zoom_filter_on_children)

        # Loading splash overlay — shown until the page reports loadFinished.
        # Just the gold mark; the in-page HTML splash takes over once index
        # mounts and provides the full halftone dither bar.
        self._splash = QLabel(self._view)
        self._splash.setText("✦")
        self._splash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._splash.setStyleSheet(
            f"background: {_BG_HEX}; color: #d4a050; "
            "font-family: 'Cascadia Mono', 'Consolas', monospace; "
            "font-size: 38px;"
        )
        self._splash.setGeometry(0, 0, self._view.width(), self._view.height())
        self._splash.show()
        self._view.installEventFilter(self)  # to resize the splash to match the view
        self._view.loadFinished.connect(self._on_load_finished)

        html_path = _pick_index_html()
        self._view.setUrl(QUrl.fromLocalFile(html_path))

    def _install_zoom_filter_on_children(self):
        try:
            for child in self._view.findChildren(QObject):
                child.installEventFilter(self._no_zoom)
        except Exception:
            pass

    def _on_load_finished(self, ok: bool) -> None:
        if self._splash:
            self._splash.hide()
            self._splash.deleteLater()
            self._splash = None

    def eventFilter(self, obj, event):
        if obj is self._view and event.type() == QEvent.Type.Resize and self._splash:
            self._splash.setGeometry(0, 0, self._view.width(), self._view.height())
        return super().eventFilter(obj, event)

    @staticmethod
    def _inject_qwebchannel_js(page) -> None:
        qf = QFile(':/qtwebchannel/qwebchannel.js')
        if not qf.open(QIODevice.OpenModeFlag.ReadOnly):
            print('[LibraryHubWindow] warning: could not open qwebchannel.js from Qt resources')
            return
        js_src = bytes(qf.readAll()).decode('utf-8')
        qf.close()

        script = QWebEngineScript()
        script.setName('qwebchannel-init')
        script.setSourceCode(js_src)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        page.scripts().insert(script)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if sys.platform != 'win32' or self._shadow_done:
            return
        try:
            hwnd = int(self.winId())
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33; value 2 = round (Win11)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            # Extend frame into client → gives the window a real native drop-shadow
            # even though it's frameless. (1px margin is enough to trigger it.)
            margins = (ctypes.c_int * 4)(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, margins)
            self._shadow_done = True
        except Exception:
            pass

    def show_animated(self, x: int, y: int) -> None:
        self._closing = False
        self.move(x, y)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            self._open_anim = QPropertyAnimation(self, b"windowOpacity")
            self._open_anim.setDuration(220)
            self._open_anim.setStartValue(0.0)
            self._open_anim.setEndValue(1.0)
            self._open_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._open_anim.start()
        except Exception:
            self.setWindowOpacity(1.0)

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
            self._fade_anim.setDuration(180)
            self._fade_anim.setStartValue(1.0)
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_anim.finished.connect(self.close)
            self._fade_anim.start()
        except Exception:
            self.close()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close_animated()
        else:
            super().keyPressEvent(e)
