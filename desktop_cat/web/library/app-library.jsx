// app-library.jsx — Fullscreen entry point for Sao's Library.
// Connects to the Python QWebChannel bridge (saoBridge) and passes it
// into Direction3v3 so the chat input can call Groq via Python.

function App() {
  const [bridge, setBridge] = React.useState(null);
  // Tick re-render until window.IOSApp shows up — defensive against a
  // race where Babel-standalone is still processing xv5-ios-app.jsx
  // when this script renders.  Also surfaces any global JS error to
  // the on-screen loading area so we can diagnose stuck loads.
  const [iosTick, setIosTick] = React.useState(0);
  const [loadErr, setLoadErr] = React.useState(null);
  React.useEffect(() => {
    const onErr = (e) => {
      try {
        const msg = (e && (e.error ? (e.error.stack || e.error.message) : e.message)) || String(e);
        setLoadErr(prev => prev || msg);
      } catch (x) {}
    };
    window.addEventListener('error', onErr);
    let n = 0;
    const t = setInterval(() => {
      if (window.IOSApp || n++ > 40) { setIosTick(x => x + 1); clearInterval(t); }
    }, 50);
    return () => { clearInterval(t); window.removeEventListener('error', onErr); };
  }, []);

  // ── Window animation ─────────────────────────────────────────────────
  // Animate the root div before telling Python to minimize / close.
  // The CSS transform plays in the browser; then Python's native call
  // (or close_animated) takes over once the JS anim finishes.
  const rootRef = React.useRef(null);

  const _flash = (type) => {
    const el = rootRef.current;
    if (!el) return;
    el.style.transition = 'transform 140ms ease-in, opacity 140ms ease-in';
    if (type === 'min') {
      el.style.transform = 'scale(0.96) translateY(8px)';
    } else {
      el.style.transform = 'scale(0.97)';
    }
    el.style.opacity = '0';
  };
  const _resetStyle = () => {
    const el = rootRef.current;
    if (!el) return;
    el.style.transition = 'none';
    el.style.transform  = '';
    el.style.opacity    = '1';
  };

  const onWinMin   = () => {
    if (!bridge) return;
    _flash('min');
    setTimeout(() => { bridge.windowMinimize(); setTimeout(_resetStyle, 350); }, 130);
  };
  const onWinClose = () => {
    if (!bridge) return;
    _flash('close');
    setTimeout(() => bridge.windowClose(), 130);
  };
  const onWinMax   = () => { if (bridge) bridge.windowToggleMax(); };

  // Global zoom guard.  The Python event filter already blocks Ctrl+±/0
  // keyboard zoom, but Ctrl+Wheel passes through so the library map's
  // pinch zoom works.  Anywhere ELSE in the app, Ctrl+Wheel should NOT
  // zoom the browser content.  We install a capture-phase listener so
  // any wheel event with the ctrl modifier is swallowed UNLESS it's
  // happening over a <canvas> (the library map).
  React.useEffect(() => {
    const onWheel = (e) => {
      if (!e.ctrlKey) return;
      if (e.target && e.target.closest && e.target.closest('canvas')) return;
      e.preventDefault();
    };
    window.addEventListener('wheel', onWheel, { passive: false, capture: true });
    return () => window.removeEventListener('wheel', onWheel, { capture: true });
  }, []);

  React.useEffect(() => {
    // Clear the HTML splash now that React has mounted.
    const sp = document.getElementById('splash');
    if (sp) sp.style.opacity = '0';
    setTimeout(() => { if (sp && sp.parentNode) sp.parentNode.removeChild(sp); }, 240);
    // Add fade-out transition before removal
    if (sp) sp.style.transition = 'opacity 220ms ease-out';

    if (typeof QWebChannel === 'undefined' || !window.qt) return;
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      window.__saoBridge = channel.objects.saoBridge;   // global for lightweight hover calls
      setBridge(channel.objects.saoBridge);
    });
  }, []);

  // Use the iOS port (xv5-ios-app.jsx) as the entire window.  It owns
  // its own window chrome (.ios-win), nav (.ios-nav segmented control),
  // and screens (To-Do / Stickies / Settings) — modelled exactly after
  // tend-ios-export/ios-app.jsx with the data layer wired to saoBridge.
  const Ios = (typeof window !== 'undefined') ? window.IOSApp : null;
  void iosTick;   // referenced so React knows to re-render when ticked
  return (
    <div ref={rootRef} style={{ width: '100vw', height: '100vh', overflow: 'hidden', willChange: 'transform, opacity', position: 'relative' }}>
      {Ios
        ? <Ios bridge={bridge}
            onWinMin={onWinMin} onWinClose={onWinClose} onWinMax={onWinMax} />
        : <div style={{ color: '#9a9eae', padding: 20, fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {loadErr ? ('iOS app failed to load:\n\n' + loadErr) : 'Loading iOS app…'}
          </div>}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
