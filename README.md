# Sao — Desktop Cat

A transparent **PyQt6** desktop companion: **Sao**, a pixel cat who lives on your
Windows taskbar. She walks across your open windows, hops between them, ducks into
your taskbar apps to "work," tends a small garden of flowers tied to your to‑dos,
and is wrapped around a tiny productivity hub.

> Windows only. Tuned for a single monitor.

<!-- Demo GIF: drop a short screen recording at docs/demo.gif and it shows here. -->
![Sao walking across the taskbar](docs/demo.gif)

## ⬇️ Download

Grab the latest build from the **[Releases page](../../releases)** — unzip it
anywhere and run `Sao.exe`. No Python install needed. Windows only.

> Windows SmartScreen may warn about an unknown publisher (normal for unsigned
> apps): click **More info → Run anyway**.

## What it does

- **Sao** wanders the taskbar and the tops of your open windows, chases the
  occasional butterfly, and ducks into running apps to "work" (she only pops back
  out when you click that app's icon).
- **Task flowers** — each to‑do is planted as a flower on the taskbar that blooms
  as its due date approaches. You pick the flower when you create the task, and
  Sao cheers you on with a little speech bubble when you finish one.
- **Library Hub** — a small dark/light productivity window with:
  - a **to‑do list** (priorities, lists, custom due dates, a "done today" count)
    that can sync from a **Canvas iCal feed**,
  - **sticky notes** that float on your desktop,
  - a **timer / pomodoro** that runs on a floating **Timer Island** pill, with an
    auto work → break cycle and gentle chimes.
- **Focus mode** — one switch hides Sao, the critters, and the décor so you can
  knuckle down.
- **Window pinning** — keep any window always‑on‑top (click its edge or its
  taskbar icon), marked with a small dot near its close button.

## Run from source

Requires **Python 3.12** on Windows.

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 main.py
```

The app runs windowless — control it from the **paw icon in the system tray**
(left‑click opens the hub, right‑click for the menu). You can also right‑click
Sao herself for **Open window / Quit**.

To connect Canvas: open the hub → **Settings** → paste your
*Canvas → Calendar → Calendar Feed* URL → **Save**, then **Sync**.

## Build a standalone app (Windows)

To produce a double‑click app that doesn't need Python installed:

```bash
py -3.12 -m pip install pyinstaller
py -3.12 -m PyInstaller Sao.spec
```

This creates a self‑contained folder at **`dist/Sao/`** — run `dist/Sao/Sao.exe`.
Zip the whole `dist/Sao` folder to share it.

> It's a one‑folder build (not a single `.exe`) because bundling Qt WebEngine —
> which powers the hub UI — into one file is unreliable. The folder build is the
> dependable path. Use PyInstaller ≥ 6 so the Qt WebEngine files are collected
> automatically; if the hub window comes up blank in the built app, that's the
> thing to check.

## Development

```bash
py -3.12 -m pytest tests/        # all tests must pass before commit
```

- Physics & collision are pure functions (easy to test).
- Cross‑module messaging goes through an `EventBus`.
- Window scanning is event‑driven (only sweeps when the desktop could change).
- The hub UI is React (loaded into a `QWebEngineView`); the Python side talks to
  it over a `QWebChannel` bridge.

## Status

Active hobby project. Grab a ready‑to‑run build from the
[Releases page](../../releases), or run from source as above.

## Credits

- **Sao character sprites** (idle / walk / run / jump / interact / attack) by
  **ErisEsra** — https://x.com/ErisEsra_

  > Feel free to use these assets in commercial and non-commercial projects.
  > Credit is appreciated, but not required! All I ask is that you don't
  > directly resell these assets! If you end up using them, feel free to tag
  > me on Twitter or Bluesky.

## License

The code is MIT — see [LICENSE](LICENSE). The **art assets** in
`desktop_cat/sprites/` are by their respective creators (see Credits) and are
**not** covered by the MIT license — please follow the artists' terms (e.g.
don't resell the sprites).
