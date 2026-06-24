// xv5-ios-app.jsx — verbatim port of tend-ios-export/ios-app.jsx, wired to
// the saoBridge so it reads real Canvas + library todos and real stickies
// from disk instead of the reference's seed data.  Replaces Direction3v3
// as the React mount.  Exposes window.IOSApp.
//
// The look IS the reference — same .ios-* class names, same CSS literal,
// same component structure.  Only the data layer changed.

// ───────────────────── styles (verbatim from reference) ─────────────────
(function () {
  if (document.getElementById('ios-styles')) return;
  const s = document.createElement('style');
  s.id = 'ios-styles';
  s.textContent = `
  .ios{--accent:#6f8cd6;--done:#5fc2a6;
       --bg:#1a1b20;--bar:#202229;--card:#262932;--cardhi:#2e313c;--well:#16171b;
       --label:#e9eaf0;--sec:#9a9eae;--ter:#6b6f80;--line:rgba(255,255,255,.07);--line2:rgba(255,255,255,.045);
       position:absolute;inset:0;display:flex;flex-direction:column;overflow:hidden;background:var(--bg);
       color:var(--label);-webkit-font-smoothing:antialiased;
       font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",system-ui,sans-serif;
       font-size:15px;line-height:1.42;letter-spacing:-.2px;}
  /* Light theme — overrides the design tokens; toggled in Settings. */
  .ios.light{--accent:#5a78d0;--done:#3fa98a;
       --bg:#f4f5f8;--bar:#ffffff;--card:#ffffff;--cardhi:#eaeef6;--well:#e7ebf2;
       --label:#1b1c22;--sec:#5b5f6c;--ter:#9498a6;
       --line:rgba(0,0,0,.10);--line2:rgba(0,0,0,.05);}
  .ios.light .ios-win{background:#e7ebf2;}
  .ios *{box-sizing:border-box;}
  .ios ::-webkit-scrollbar{width:11px;height:11px;}
  .ios ::-webkit-scrollbar-track{background:transparent;}
  .ios ::-webkit-scrollbar-thumb{background:rgba(255,255,255,.11);border-radius:8px;border:3px solid transparent;background-clip:padding-box;}
  .ios ::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.2);background-clip:padding-box;}
  @keyframes flowIn{from{opacity:0;transform:translateX(-12px) scale(.9);}to{opacity:1;transform:none;}}
  @keyframes cardLeave{0%,52%{opacity:1;transform:none;max-height:240px;}100%{opacity:0;transform:translateX(40px) scale(.96);max-height:0;margin-bottom:-10px;padding-top:0;padding-bottom:0;}}
  @keyframes ckpop{0%{transform:scale(1);}42%{transform:scale(1.2);}100%{transform:scale(1);}}
  .ios-card.leaving{animation:cardLeave .9s cubic-bezier(.4,0,.2,1) forwards;pointer-events:none;overflow:hidden;}
  .ios-card.leaving .ios-ck{animation:ckpop .38s ease;}
  /* window bar */
  .ios-win{height:38px;flex:none;display:flex;align-items:center;justify-content:flex-end;background:#15161a;border-bottom:1px solid var(--line);}
  .ios-win button{width:52px;height:38px;border:0;background:transparent;color:var(--sec);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.1s;}
  .ios-win button:hover{background:rgba(255,255,255,.08);color:var(--label);}
  .ios-win button.cl:hover{background:#e0495a;color:#fff;}
  /* nav */
  .ios-nav{flex:none;display:flex;align-items:center;gap:8px;height:50px;padding:0 12px;background:var(--bar);border-bottom:1px solid var(--line);}
  .ios-nav .nbtn{width:38px;height:36px;border:0;background:transparent;color:var(--sec);cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:9px;transition:.12s;}
  .ios-nav .nbtn:hover{background:var(--cardhi);color:var(--label);}
  .ios-nav .nbtn.wide{width:auto;padding:0 11px;gap:6px;font-family:inherit;font-size:14px;font-weight:500;color:var(--accent);}
  .ios-seg{margin:0 auto;display:flex;background:var(--well);border-radius:10px;padding:3px;gap:3px;width:210px;}
  .ios-seg button{flex:1;border:0;background:transparent;font-family:inherit;font-size:13.5px;font-weight:500;color:var(--sec);padding:6px 0;border-radius:7px;cursor:pointer;transition:.15s;}
  .ios-seg button.on{background:var(--cardhi);color:var(--label);box-shadow:0 1px 3px rgba(0,0,0,.3);font-weight:600;}
  .ios-navtitle{margin:0 auto;font-size:15.5px;font-weight:600;}
  /* body */
  .ios-body{flex:1;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.16) transparent;}
  .ios-lt{padding:14px 20px 4px;}
  .ios-lt h1{font-size:28px;font-weight:700;letter-spacing:-.7px;margin:0;}
  .ios-lt .sub{font-size:13.5px;color:var(--ter);margin-top:3px;font-weight:500;}
  /* control row */
  .ios-ctrl{display:flex;align-items:center;gap:10px;padding:12px 20px 8px;}
  .ios-seg2,.ios-hist{display:flex;background:var(--well);border-radius:9px;padding:3px;}
  .ios-seg2 button{border:0;background:transparent;font-family:inherit;font-size:13px;color:var(--sec);padding:6px 13px;border-radius:6px;cursor:pointer;font-weight:500;transition:.12s;}
  .ios-seg2 button.on{background:var(--cardhi);color:var(--label);box-shadow:0 1px 2px rgba(0,0,0,.3);font-weight:600;}
  .ios-hist{margin-left:auto;}
  .ios-hist button{border:0;background:transparent;font-family:inherit;font-size:13px;color:var(--sec);padding:6px 13px;border-radius:6px;cursor:pointer;font-weight:500;display:flex;align-items:center;gap:6px;transition:.12s;}
  .ios-hist button.on{background:var(--accent);color:#fff;font-weight:600;box-shadow:0 1px 6px color-mix(in oklab,var(--accent) 50%,transparent);}
  /* section header */
  .ios-sec{padding:0 20px;margin:16px 0 9px;display:flex;align-items:baseline;gap:9px;}
  .ios-sec h2{font-size:18px;font-weight:700;letter-spacing:-.4px;margin:0;}
  .ios-sec .cnt{font-size:13px;color:var(--ter);font-weight:700;}
  .ios-sec .sub{font-size:12.5px;color:var(--ter);margin-left:auto;font-weight:500;}
  .ios-sec .clr{margin-left:auto;border:0;background:transparent;color:var(--accent);font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:5px;padding:4px 8px;border-radius:7px;}
  .ios-sec .clr:hover{background:var(--cardhi);}
  /* cards */
  .ios-cards{padding:0 16px;display:flex;flex-direction:column;gap:10px;}
  .ios-card{background:var(--card);border-radius:15px;padding:16px 8px 14px 15px;border:1px solid var(--line2);position:relative;overflow:hidden;
            box-shadow:0 2px 10px rgba(0,0,0,.18);display:flex;gap:11px;align-items:stretch;cursor:pointer;transition:background .12s,transform .08s;}
  .ios-card:not(.open):hover{background:var(--cardhi);}
  .ios-card:not(.open):active{transform:scale(.995);}
  .ios-card.open{cursor:default;background:var(--cardhi);}
  /* Due today → soft lavender ring so it stands out in the list. */
  .ios-card.today{border-color:#b9a8ee;box-shadow:0 0 0 1px #b9a8ee,0 2px 12px color-mix(in oklab,#b9a8ee 30%,transparent);}
  .ios-card.today:not(.open):hover{box-shadow:0 0 0 1px #c7b9f2,0 2px 14px color-mix(in oklab,#b9a8ee 38%,transparent);}
  .ios-progwrap{position:absolute;top:0;left:0;right:0;height:3px;background:rgba(255,255,255,.06);}
  .ios-progwrap i{display:block;height:100%;background:var(--accent);box-shadow:0 0 8px color-mix(in oklab,var(--accent) 55%,transparent);transition:width .3s;}
  .ios-bars{display:inline-flex;align-items:flex-end;gap:2px;height:13px;}
  .ios-bars i{width:3.5px;border-radius:2px;}
  .ios-compose{box-shadow:0 0 0 1.5px var(--accent),0 8px 22px rgba(0,0,0,.4);}
  .ios-actions{display:flex;gap:8px;margin-top:8px;}
  .ios-addbtn{flex:1;border:0;background:var(--accent);color:#fff;font-family:inherit;font-weight:700;font-size:14px;padding:9px;border-radius:10px;cursor:pointer;box-shadow:0 2px 12px color-mix(in oklab,var(--accent) 45%,transparent);transition:.12s;}
  .ios-addbtn:hover{filter:brightness(1.07);}
  /* Timer Start button — a chunkier accent pill (turns green while running). */
  .ios-start{font-size:12.5px;font-weight:700;border:0;cursor:pointer;border-radius:10px;padding:6px 14px;
             background:var(--accent);color:#fff;display:inline-flex;align-items:center;gap:6px;font-family:inherit;
             box-shadow:0 2px 9px color-mix(in oklab,var(--accent) 42%,transparent);
             transition:background .4s ease,box-shadow .18s,transform .1s,filter .12s;white-space:nowrap;}
  .ios-start:hover{filter:brightness(1.08);box-shadow:0 3px 13px color-mix(in oklab,var(--accent) 55%,transparent);}
  .ios-start:active{transform:scale(.95);}
  .ios-start.run{background:#3ea06d;box-shadow:0 2px 9px color-mix(in oklab,#3ea06d 45%,transparent);}
  .ios-start svg{flex:none;}
  .ios-cancel{border:0;background:rgba(255,255,255,.07);color:var(--sec);font-family:inherit;font-weight:600;font-size:14px;padding:9px 14px;border-radius:10px;cursor:pointer;transition:.12s;}
  .ios-cancel:hover{background:rgba(255,255,255,.12);color:var(--label);}
  .ios-compose .ios-title:empty::before{content:'New task…';color:var(--ter);}
  .ios-ck{width:23px;height:23px;border-radius:50%;border:2px solid var(--ckc,#52566a);flex:none;margin-top:1px;position:relative;cursor:pointer;transition:.15s;}
  .ios-ck:hover{border-color:var(--ckc,#7a7f96);}
  .ios-ck.on{background:var(--ckc,#5fc2a6);border-color:var(--ckc,#5fc2a6);}
  .ios-ck.on::after{content:'';position:absolute;inset:0;margin:auto;width:5.5px;height:9.5px;border:2px solid #fff;border-top:0;border-left:0;transform:translateY(-1px) rotate(42deg);}
  .ios-cmain{flex:1;min-width:0;align-self:center;}
  .ios-title{font-size:16px;font-weight:600;letter-spacing:-.3px;outline:none;}
  .ios-title[contenteditable]:focus{box-shadow:0 1px 0 var(--accent);}
  .ios-card.done .ios-title{color:var(--ter);text-decoration:line-through;}
  .ios-right{display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:5px;flex:none;
             align-self:stretch;min-width:72px;padding:0 6px;}
  .ios-when{font-size:22px;font-weight:700;letter-spacing:-.6px;color:var(--sec);font-variant-numeric:tabular-nums;white-space:nowrap;min-width:64px;text-align:right;}
  .ios-when.soon{color:var(--accent);}
  .ios-when.over{color:#e0859e;}
  .ios-badges{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px;}
  .ios-pri{font-size:13px;font-weight:800;letter-spacing:-1px;}
  .ios-tag{font-size:12px;font-weight:600;color:var(--sec);background:rgba(255,255,255,.06);border-radius:7px;padding:2px 8px;}
  .ios-rep{font-size:12px;color:var(--sec);display:flex;align-items:center;gap:4px;font-weight:500;}
  .ios-ldot{width:9px;height:9px;border-radius:50%;flex:none;}
  .ios-detail{margin-top:11px;padding-top:11px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:11px;}
  .ios-note{font-size:14px;color:var(--sec);line-height:1.5;outline:none;min-height:20px;letter-spacing:-.1px;}
  .ios-note:empty::before{content:'Add a note…';color:var(--ter);}
  .ios-note:focus{color:var(--label);}
  .ios-frow{display:flex;align-items:flex-start;gap:10px;font-size:13.5px;min-height:30px;}
  .ios-frow .k{color:var(--ter);width:60px;flex:none;font-weight:500;padding-top:6px;}
  .ios-flow{display:flex;gap:7px;flex-wrap:wrap;flex:1;}
  .ios-flow>*{animation:flowIn .22s both;}
  .ios-pick{font-size:12.5px;font-weight:600;border:0;cursor:pointer;border-radius:8px;padding:5px 11px;background:rgba(255,255,255,.06);color:var(--sec);display:flex;align-items:center;gap:6px;font-family:inherit;transition:.12s;}
  .ios-pick:hover{background:rgba(255,255,255,.12);color:var(--label);}
  .ios-pick.sel{box-shadow:inset 0 0 0 1.5px var(--accent);color:var(--label);background:color-mix(in oklab,var(--accent) 16%,transparent);}
  /* stickies — masonry via columns */
  .ios-notes{padding:14px 16px 22px;column-width:var(--nmin,150px);column-gap:13px;}
  .ios-snote{break-inside:avoid;-webkit-column-break-inside:avoid;width:100%;margin:0 0 13px;
             border-radius:16px;padding:10px 12px 9px;max-height:340px;display:flex;flex-direction:column;position:relative;box-shadow:0 6px 18px rgba(0,0,0,.3);}
  .ios-snote .stop{display:flex;align-items:center;justify-content:flex-end;gap:4px;margin-bottom:5px;}
  .ios-snote .sbtn{width:28px;height:28px;border-radius:50%;border:0;background:transparent;cursor:pointer;color:inherit;
                   display:flex;align-items:center;justify-content:center;opacity:.6;transition:.12s;}
  .ios-snote .sbtn:hover{opacity:1;background:rgba(0,0,0,.1);}
  .ios-snote .sbtn.pin.on{opacity:1;}
  .ios-snote .sbody{flex:1;font-size:14.5px;line-height:1.45;font-weight:600;white-space:pre-line;outline:none;letter-spacing:-.2px;overflow-y:auto;}
  .ios-snote .sbody::-webkit-scrollbar-thumb{background:rgba(0,0,0,.2);}
  .ios-snote .sctrl{margin-top:9px;padding-top:8px;border-top:1px solid rgba(0,0,0,.13);display:flex;align-items:center;gap:8px;position:relative;}
  .ios-cbtn{width:20px;height:20px;border-radius:50%;cursor:pointer;border:2px solid rgba(0,0,0,.2);flex:none;transition:transform .1s;}
  .ios-cbtn:hover{transform:scale(1.12);}
  .ios-cpop{position:absolute;left:-2px;bottom:30px;background:#23252c;border:1px solid rgba(255,255,255,.1);border-radius:13px;
            padding:9px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;box-shadow:0 10px 30px rgba(0,0,0,.5);z-index:20;}
  .ios-cpop i{width:20px;height:20px;border-radius:50%;cursor:pointer;border:1px solid rgba(0,0,0,.25);animation:flowIn .2s both;}
  .ios-cpop i.on{box-shadow:0 0 0 2px #23252c,0 0 0 3.5px #fff;}
  .ios-op{margin-left:auto;display:flex;align-items:center;gap:6px;}
  .ios-op label{font-size:12px;opacity:.55;font-style:italic;}
  .ios-op input[type=range]{-webkit-appearance:none;appearance:none;width:54px;height:3px;border-radius:3px;background:rgba(0,0,0,.25);outline:none;}
  .ios-op input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:currentColor;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.4);}
  /* settings */
  .ios-grp{margin:10px 18px 22px;}
  .ios-grp .glab{font-size:12px;color:var(--ter);text-transform:uppercase;letter-spacing:.6px;font-weight:700;margin:0 4px 8px;}
  .ios-grp .box{background:var(--card);border-radius:14px;overflow:hidden;border:1px solid var(--line2);}
  .ios-set{display:flex;align-items:center;gap:12px;padding:13px 15px;border-bottom:1px solid var(--line2);min-height:50px;}
  .ios-set:last-child{border-bottom:0;}
  .ios-set .k{flex:1;font-size:15.5px;}
  .ios-set .k small{display:block;font-size:12.5px;color:var(--ter);margin-top:2px;}
  .ios-sw2{width:44px;height:25px;border-radius:25px;background:rgba(255,255,255,.08);position:relative;flex:none;
           transition:.22s;cursor:pointer;box-shadow:inset 0 0 0 1px rgba(255,255,255,.07);}
  .ios-sw2.on{background:var(--accent);box-shadow:inset 0 0 0 1px transparent,0 0 11px color-mix(in oklab,var(--accent) 45%,transparent);}
  .ios-sw2 i{position:absolute;top:3px;left:3px;width:19px;height:19px;border-radius:50%;background:#cfd2dc;
             transition:.24s cubic-bezier(.4,1.35,.5,1);box-shadow:0 1px 3px rgba(0,0,0,.45);}
  .ios-sw2.on i{left:22px;background:#fff;}
  .ios-val{color:var(--sec);font-size:14.5px;display:flex;align-items:center;gap:5px;}
  .ios-empty{text-align:center;color:var(--ter);padding:48px 20px;font-size:14px;}
  /* Empty-state inside the masonry columns must span every column, else it
     gets trapped in one ~150px column and the text wraps/misaligns. */
  .ios-notes .ios-empty{column-span:all;-webkit-column-span:all;}
  /* Kill Chromium's default number-input spinner arrows (the timer/pomodoro
     minute boxes) — they don't match the app's styling. */
  input[type=number]{-moz-appearance:textfield;}
  input[type=number]::-webkit-inner-spin-button,
  input[type=number]::-webkit-outer-spin-button{-webkit-appearance:none;margin:0;}
  /* Task-complete sparkle — soft golden motes that drift out and fade. */
  .ios-spark{position:fixed;width:6px;height:6px;border-radius:50%;pointer-events:none;z-index:9999;
    background:radial-gradient(circle,#fff7cf 0%,#ffd86b 70%,rgba(255,216,107,0) 100%);
    box-shadow:0 0 7px #ffd86b;transform:translate(-50%,-50%);animation:iosSpark .72s ease-out forwards;}
  @keyframes iosSpark{
    0%{opacity:0;transform:translate(-50%,-50%) translate(0,0) scale(.35);}
    25%{opacity:1;}
    100%{opacity:0;transform:translate(-50%,-50%) translate(var(--dx),var(--dy)) scale(1);}
  }
  /* Flower picker — crisp pixel-art icons of the fully-grown task flowers. */
  .ios-fpick{padding:5px 8px;min-height:30px;}
  .ios-fimg{width:22px;height:22px;display:block;image-rendering:pixelated;image-rendering:crisp-edges;}
  /* Dark-themed native date picker for the composer's Custom day. */
  .ios-date{background:rgba(255,255,255,.06);color:var(--label);border:0;border-radius:8px;
            padding:5px 9px;font-family:inherit;font-size:12.5px;color-scheme:dark;outline:none;cursor:pointer;}
  /* "New task / new sticky" button — a pop of blue so the primary action
     reads at a glance instead of blending into the toolbar. */
  .ios-nav .nbtn.add{color:#fff;background:#4a90e2;box-shadow:0 2px 11px rgba(74,144,226,.5);}
  .ios-nav .nbtn.add:hover{background:#5b9ce8;color:#fff;}
  .ios-nav .nbtn.add:active{transform:scale(.94);}
  /* Pinned-window name marquee — clip to its lane, gently scroll long
     titles so they never run under the Remove button. */
  .pin-name{position:relative;flex:1;min-width:0;overflow:hidden;white-space:nowrap;
            -webkit-mask-image:linear-gradient(90deg,#000 86%,transparent);mask-image:linear-gradient(90deg,#000 86%,transparent);}
  .pin-name>span{display:inline-block;white-space:nowrap;will-change:transform;}
  .pin-name.scroll>span{animation:pinScroll 7s ease-in-out infinite alternate;}
  @keyframes pinScroll{0%,12%{transform:translateX(0);}88%,100%{transform:translateX(var(--pin-shift,0));}}
  `;
  document.head.appendChild(s);
})();

// ───────────────────── icons (verbatim) ─────────────────────────────────
const ios_svg = (d, { size = 20, sw = 1.8, fill = 'none' } = {}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">{d}</svg>
);
const IOS_IC = {
  settings: <><path d="M4 8h8" /><path d="M18 8h2" /><circle cx="15" cy="8" r="2.4" /><path d="M4 16h2" /><path d="M12 16h8" /><circle cx="9" cy="16" r="2.4" /></>,
  compose: <><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" /><path d="M17.6 3.6a2 2 0 0 1 2.8 2.8L12 14.8l-3.6 1 1-3.6 8.2-8.6z" /></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 4v4h4" /><path d="M12 8.5v4l3 1.8" /></>,
  back: <><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></>,
  chev: <path d="M9 6l6 6-6 6" />,
  rep: <><path d="M17 3l3.2 3.2L17 9.4" /><path d="M3.5 11V9.2a3 3 0 0 1 3-3h13.7" /><path d="M7 21l-3.2-3.2L7 14.6" /><path d="M20.5 13v1.8a3 3 0 0 1-3 3H3.8" /></>,
  pin: <><path d="M12 16.5v4.5" /><path d="M8.5 3h7l-1 6.2 2.8 2.8H6.7L9.5 9.2 8.5 3z" /></>,
  trash: <><path d="M4 7h16" /><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" /><path d="M10 11v6M14 11v6" /></>,
  x: <path d="M5.5 5.5l13 13M18.5 5.5l-13 13" />,
};

// ───────────────────── data tables (verbatim) ───────────────────────────
const IOS_LISTS = { Work: '#7b91e8', Home: '#5fc2a6', School: '#e0b15f', Money: '#d6a45f', Art: '#a98be0', Health: '#e0859e', Self: '#67b6c9', Fun: '#cf86b6', None: '#7c8190' };
// Flower sprite variants (0..4) — icons rendered from the game sprite sheet
// into web/library/flowers/.  Index = TaskFlower.variant.  -1 = random.
const IOS_FLOWERS = ['green flower', 'blue flower', 'red flower', 'white flower', 'tall blue flower'];

// ── Task-complete celebration: a calm chime + a soft sparkle burst ───────
// Mirrored from world_settings.sound_effects (set in IOSApp); the sparkle
// always shows, only the chime is muted.
let IOS_SOUND_ENABLED = true;
let _iosAudioCtx = null;
function ios_playChime() {
  if (!IOS_SOUND_ENABLED) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = _iosAudioCtx || (_iosAudioCtx = new AC());
    if (ctx.state === 'suspended') ctx.resume();
    const now = ctx.currentTime;
    // A gentle rising triad (C5–E5–G5) on soft sine voices with a slow
    // bell-like decay — warm and cute, nothing like a sharp "ding".
    [523.25, 659.25, 783.99].forEach((f, i) => {
      const t = now + i * 0.085;
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = f;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.13, t + 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t + 0.6);
    });
  } catch (e) { /* audio is polish only */ }
}
function ios_sparkle(el) {
  try {
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const N = 7;
    for (let i = 0; i < N; i++) {
      const s = document.createElement('div');
      s.className = 'ios-spark';
      const ang = (i / N) * Math.PI * 2 + Math.random() * 0.6;
      const dist = 15 + Math.random() * 15;
      s.style.left = cx + 'px'; s.style.top = cy + 'px';
      s.style.setProperty('--dx', Math.cos(ang) * dist + 'px');
      s.style.setProperty('--dy', Math.sin(ang) * dist + 'px');
      s.style.animationDelay = (Math.random() * 0.05) + 's';
      document.body.appendChild(s);
      setTimeout(() => s.remove(), 760);
    }
  } catch (e) { /* sparkle is polish only */ }
}
function ios_celebrate(el) { ios_sparkle(el); ios_playChime(); }
const IOS_LIST_KEYS = Object.keys(IOS_LISTS);
const IOS_PRI = { 3: { c: '#e0859e', l: 'High' }, 2: { c: '#d6a45f', l: 'Medium' }, 1: { c: '#7f93c9', l: 'Low' } };
const IOS_NOTE_TONES = [
  { key: 'butter', paper: '#ffe1a0' }, { key: 'plain', paper: '#e9eaf0' }, { key: 'blush', paper: '#ffc4d4' }, { key: 'lilac', paper: '#dcc8fb' },
  { key: 'sky', paper: '#bcdcff' }, { key: 'mint', paper: '#b6ecc0' }, { key: 'peach', paper: '#ffcda6' }, { key: 'fog', paper: '#cdd0da' },
];
const ios_inkFor = (hex) => { const n = parseInt(hex.slice(1), 16); const L = (.299 * ((n >> 16) & 255) + .587 * ((n >> 8) & 255) + .114 * (n & 255)); return L > 150 ? '#33312c' : '#1c1c22'; };
const ios_toneOf = (k) => IOS_NOTE_TONES.find(t => t.key === k) || IOS_NOTE_TONES[1];
const ios_hexA = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`; };

// ───────────────────── bridge ↔ iOS data adapters ───────────────────────
// My library_todos shape: { id, name, due (ISO yyyy-mm-dd), done, source }
// iOS shape: { id, title, note, pri, day, time, list, rec, made, prog }
//
// Day-bucketing turns the ISO date into one of:
//   'Past due' | 'Today' | 'Tomorrow' | weekday name | 'Next week' | 'Later' | null
// based on diff against today.  These match (or extend) DAY_ORDER below.

const IOS_DAY_ORDER = ['Past due', 'Today', 'Tomorrow',
                       'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'Monday', 'Tuesday',
                       'Next week', 'Later'];
const IOS_WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const IOS_MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function ios_parseIso(s) {
  if (!s || typeof s !== 'string') return null;
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3]);
}
function ios_today() { const d = new Date(); d.setHours(0,0,0,0); return d; }
function ios_diffDays(a, b) { return Math.round((a - b) / 86400000); }

// "Today's weekday" → so we don't bucket today as e.g. 'Wednesday' in addition to 'Today'.
function ios_bucketForDue(iso) {
  const d = ios_parseIso(iso);
  if (!d) return null;
  const td = ios_today();
  const diff = ios_diffDays(d, td);
  if (diff < 0)  return 'Past due';
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff <= 6) return IOS_WEEKDAYS[d.getDay()];  // Wed / Thu / Fri etc — distinct from Today/Tomorrow
  if (diff <= 13) return 'Next week';
  return 'Later';
}

function ios_subFor(bucket, iso) {
  if (bucket === 'Past due') return 'overdue';
  const d = ios_parseIso(iso);
  if (!d) return '';
  return IOS_WEEKDAYS[d.getDay()].slice(0,3) + ' · ' + IOS_MONTHS[d.getMonth()] + ' ' + d.getDate();
}

// Pull subject-code out of "Hw Ch. 13 [PHIL 120 A]" → "PHIL 120"
function ios_subjectFromName(name) {
  if (!name) return null;
  const m = name.match(/\[([A-Z]{2,5})\s*(\d{1,4})/);
  return m ? (m[1] + ' ' + m[2]) : null;
}

// Bridge todo → iOS task.  Past-due bumps priority to High so user notices.
function ios_taskFromBridge(t) {
  const bucket = ios_bucketForDue(t.due);
  const overdue = bucket === 'Past due';
  return {
    id:    t.id,
    title: t.name || '(untitled)',
    note:  t.note || '',
    pri:   t.pri || (overdue ? 3 : (t.source === 'canvas' ? 2 : 1)),
    day:   bucket,
    iso:   t.due || null,             // kept for the right-edge mini-date
    time:  t.time || null,
    list:  t.list || (t.source === 'canvas' ? 'Work' : 'Home'),
    rec:   t.rec || null,
    made:  null,
    prog:  null,
    canvas: t.source === 'canvas',
    raw:   t,                         // round-trip the unknown fields on save
  };
}
function ios_taskToBridge(it) {
  // Preserve raw fields, overlay iOS-edited values back.
  const out = Object.assign({}, it.raw || {}, {
    id:     it.id,
    name:   it.title,
    due:    it.iso,
    done:   false,
    source: (it.raw && it.raw.source) || 'manual',
  });
  // Extra iOS fields piggyback so we don't lose them on round-trip.
  out.pri  = it.pri;
  out.list = it.list;
  if (it.note) out.note = it.note;
  return out;
}

// Bridge sticky → iOS note.  My stickies have separate title + body;
// concatenate so the iOS body field shows everything.
function ios_noteFromBridge(s, idx) {
  const body = (s.title ? s.title + '\n' : '') + (s.body || '');
  return {
    id:      s.id || ('s' + idx),
    body:    body,
    tone:    ios_toneFromColor(s.color),
    opacity: 1 - Math.max(0, Math.min(100, s.fade_strength || 0)) / 100,
    pinned:  !!s.pinned,
    raw:     s,
  };
}
function ios_noteToBridge(n) {
  // First line of body → title; rest → body.  Keeps the existing Python
  // sticky_data schema intact so the floating sticky windows still work.
  const body = n.body || '';
  const nl = body.indexOf('\n');
  const title = nl > -1 ? body.slice(0, nl) : '';
  const rest  = nl > -1 ? body.slice(nl + 1) : body;
  const fade  = Math.round((1 - n.opacity) * 100);
  const tone  = ios_toneOf(n.tone);
  const raw   = n.raw || {};
  return Object.assign({}, raw, {
    id:           n.id,
    title:        title,
    body:         rest,
    body_html:    '',          // floating window will regen from body
    body_font_pt: raw.body_font_pt || 12,
    color:        tone.paper,
    fade_strength: fade,
    pinned:       !!n.pinned,
  });
}
// Color → nearest tone key.  Cheap RGB distance.
function ios_toneFromColor(hex) {
  if (!hex || typeof hex !== 'string') return 'butter';
  let best = 'butter', bestD = Infinity;
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  for (const t of IOS_NOTE_TONES) {
    const m = parseInt(t.paper.slice(1), 16);
    const dr = ((m >> 16) & 255) - r, dg = ((m >> 8) & 255) - g, db = (m & 255) - b;
    const d = dr*dr + dg*dg + db*db;
    if (d < bestD) { bestD = d; best = t.key; }
  }
  return best;
}

// ───────────────────── small UI pieces (verbatim) ───────────────────────
function IOSPriBars({ pri }) {
  const c = IOS_PRI[pri].c;
  return <span className="ios-bars" title={IOS_PRI[pri].l + ' priority'}>{[1, 2, 3].map(i => <i key={i} style={{ height: 4 + i * 3.5, background: i <= pri ? c : 'rgba(255,255,255,.16)' }} />)}</span>;
}

function IOSEditable({ html, onCommit, className, style, oneLine }) {
  return (
    <div className={className} style={style} contentEditable suppressContentEditableWarning
      onClick={e => e.stopPropagation()}
      onBlur={e => onCommit(e.currentTarget.innerText)}
      onKeyDown={e => { if (oneLine && e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur(); } }}>
      {html}
    </div>
  );
}

// ───────────────────── TaskCard (port) ──────────────────────────────────
function IOSTaskCard({ t, setTask, complete }) {
  const [open, setOpen] = React.useState(false);
  const [pick, setPick] = React.useState(null);
  const [leaving, setLeaving] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const off = e => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setPick(null); } };
    document.addEventListener('pointerdown', off, true);
    return () => document.removeEventListener('pointerdown', off, true);
  }, [open]);

  const overdue = t.day === 'Past due';
  const soon    = t.day === 'Today';
  const pm = IOS_PRI[t.pri];
  const lc = IOS_LISTS[t.list] || IOS_LISTS.Work;
  const subj = ios_subjectFromName(t.title);
  const handleComplete = (e) => {
    e.stopPropagation();
    if (leaving) return;
    ios_celebrate(e.currentTarget);   // sparkle burst + calm chime
    setLeaving(true);
    setTimeout(() => complete(t.id), 900);
  };

  // Display title with the subject bracket stripped so "[PHYS 121 B]"
  // appears as a tag below instead of cluttering the title.
  const displayTitle = subj ? t.title.replace(/\s*\[[^\]]+\]\s*$/, '') : t.title;
  // Right-edge time/date: prefer t.time; else short date for past-due / week-ahead.
  const rightDate = (() => {
    if (t.time) return t.time;
    if (!t.iso) return '';
    const d = ios_parseIso(t.iso);
    if (!d) return '';
    return IOS_MONTHS[d.getMonth()] + ' ' + d.getDate();
  })();
  const whenCls = 'ios-when' + (overdue ? ' over' : soon ? ' soon' : '');

  // Hovering a to-do highlights its flower (if planted) on the taskbar.
  const hi = (on) => {
    try { if (window.__saoBridge && window.__saoBridge.setHighlightFlower)
            window.__saoBridge.setHighlightFlower(on ? String(t.id) : ''); } catch (e) {}
  };

  return (
    <div ref={ref} className={'ios-card' + (open ? ' open' : '') + (leaving ? ' leaving' : '') + (soon ? ' today' : '')}
         onMouseEnter={() => hi(true)} onMouseLeave={() => hi(false)}
         onClick={() => { if (!open && !leaving) setOpen(true); }}>
      <span className={'ios-ck' + (leaving ? ' on' : '')} style={{ '--ckc': lc }} onClick={handleComplete} />
      <div className="ios-cmain">
        {open
          ? <IOSEditable className="ios-title" oneLine html={displayTitle} onCommit={v => setTask(t.id, { title: v.trim() || displayTitle })} />
          : <div className="ios-title">{displayTitle}</div>}
        {!open && (
          <div className="ios-badges">
            <IOSPriBars pri={t.pri} />
            {subj && <span className="ios-tag">{subj}</span>}
            {t.canvas && !subj && <span className="ios-tag">canvas</span>}
            {t.rec && <span className="ios-rep">{ios_svg(IOS_IC.rep, { size: 12, sw: 2 })}{t.rec}</span>}
          </div>
        )}
        {open && (
          <div className="ios-detail" onClick={e => e.stopPropagation()}>
            <IOSEditable className="ios-note" html={t.note} onCommit={v => setTask(t.id, { note: v })} />
            <div className="ios-frow"><span className="k">List</span>
              {pick === 'list'
                ? <div className="ios-flow">{IOS_LIST_KEYS.map((k, i) => (
                    <button key={k} className={'ios-pick' + (k === t.list ? ' sel' : '')} style={{ animationDelay: i * 0.03 + 's' }}
                      onClick={() => { setTask(t.id, { list: k }); setPick(null); }}><span className="ios-ldot" style={{ background: IOS_LISTS[k] }} />{k}</button>))}</div>
                : <button className="ios-pick" onClick={() => setPick('list')}><span className="ios-ldot" style={{ background: lc }} />{t.list}</button>}
            </div>
            <div className="ios-frow"><span className="k">Priority</span>
              {pick === 'pri'
                ? <div className="ios-flow">{[3, 2, 1].map((p, i) => (
                    <button key={p} className={'ios-pick' + (p === t.pri ? ' sel' : '')} style={{ animationDelay: i * 0.03 + 's' }}
                      onClick={() => { setTask(t.id, { pri: p }); setPick(null); }}><IOSPriBars pri={p} />{IOS_PRI[p].l}</button>))}</div>
                : <button className="ios-pick" onClick={() => setPick('pri')}><IOSPriBars pri={t.pri} />{pm.l}</button>}
            </div>
            <div className="ios-frow"><span className="k">Due</span>
              <span style={{ color: 'var(--ter)', fontSize: 13, paddingTop: 6 }}>{t.iso || (t.day || 'No date')}</span></div>
          </div>
        )}
      </div>
      <div className="ios-right">
        {rightDate && <span className={whenCls}>{rightDate}</span>}
      </div>
    </div>
  );
}

// ───────────────────── Composer (port, simplified) ──────────────────────
function ios_fmtIso(iso) {
  if (!iso) return '';
  const p = String(iso).split('-').map(Number);
  if (p.length < 3 || !p[1]) return iso;
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][p[1] - 1] || '';
  return mo + ' ' + p[2];
}
function ios_dayLabel(d) {
  if (d.day === 'Custom') return d.iso ? ios_fmtIso(d.iso) : 'Pick a date…';
  return d.day || 'No date';
}
function IOSComposer({ addTask, cancel }) {
  const [d, setD] = React.useState({ title: '', note: '', pri: 2, day: 'Today', time: null, iso: null, list: 'Home', flower: -1 });
  const [pick, setPick] = React.useState(null);
  const tRef = React.useRef(null);
  React.useEffect(() => { tRef.current && tRef.current.focus(); }, []);
  const set = p => setD(s => ({ ...s, ...p }));
  const DAYS = ['Today', 'Tomorrow', 'Next week', 'Custom', null];
  return (
    <div className="ios-cards" style={{ marginBottom: 2 }}>
      <div className="ios-card open ios-compose" onClick={e => e.stopPropagation()}>
        <span className="ios-ck" style={{ '--ckc': IOS_LISTS[d.list] }} />
        <div className="ios-cmain">
          <div ref={tRef} className="ios-title" contentEditable suppressContentEditableWarning
            onInput={e => set({ title: e.currentTarget.innerText })} />
          <div className="ios-detail" style={{ borderTop: 0, paddingTop: 9, marginTop: 8 }}>
            <IOSEditable className="ios-note" html={d.note} onCommit={v => set({ note: v })} />
            <div className="ios-frow"><span className="k">List</span>
              {pick === 'list'
                ? <div className="ios-flow">{IOS_LIST_KEYS.map((k, i) => <button key={k} className={'ios-pick' + (k === d.list ? ' sel' : '')} style={{ animationDelay: i * .03 + 's' }} onClick={() => { set({ list: k }); setPick(null); }}><span className="ios-ldot" style={{ background: IOS_LISTS[k] }} />{k}</button>)}</div>
                : <button className="ios-pick" onClick={() => setPick('list')}><span className="ios-ldot" style={{ background: IOS_LISTS[d.list] }} />{d.list}</button>}</div>
            <div className="ios-frow"><span className="k">Priority</span>
              {pick === 'pri'
                ? <div className="ios-flow">{[3, 2, 1].map((p, i) => <button key={p} className={'ios-pick' + (p === d.pri ? ' sel' : '')} style={{ animationDelay: i * .03 + 's' }} onClick={() => { set({ pri: p }); setPick(null); }}><IOSPriBars pri={p} />{IOS_PRI[p].l}</button>)}</div>
                : <button className="ios-pick" onClick={() => setPick('pri')}><IOSPriBars pri={d.pri} />{IOS_PRI[d.pri].l}</button>}</div>
            <div className="ios-frow"><span className="k">Day</span>
              {pick === 'day'
                ? <div className="ios-flow">
                    {DAYS.map((dy, i) => <button key={dy || 'none'} className={'ios-pick' + (dy === d.day ? ' sel' : '')} style={{ animationDelay: i * .03 + 's' }}
                        onClick={() => { if (dy === 'Custom') { set({ day: 'Custom' }); } else { set({ day: dy, iso: null }); setPick(null); } }}>
                        {dy === 'Custom' ? 'Custom…' : (dy || 'No date')}</button>)}
                    {d.day === 'Custom' &&
                      <input type="date" className="ios-date" value={d.iso || ''} autoFocus
                        onChange={e => set({ iso: e.target.value })}
                        onKeyDown={e => { if (e.key === 'Enter' && d.iso) setPick(null); }} />}
                  </div>
                : <button className="ios-pick" onClick={() => setPick('day')}>{ios_dayLabel(d)}</button>}</div>
            <div className="ios-frow"><span className="k">Flower</span>
              {pick === 'flower'
                ? <div className="ios-flow">
                    {[0, 1, 2, 3, 4].map((v, i) => (
                      <button key={v} title={IOS_FLOWERS[v]}
                        className={'ios-pick ios-fpick' + (v === d.flower ? ' sel' : '')}
                        style={{ animationDelay: i * .03 + 's' }}
                        onClick={() => { set({ flower: v }); setPick(null); }}>
                        <img className="ios-fimg" src={'flowers/flower_' + v + '.png'} alt={IOS_FLOWERS[v]} />
                      </button>))}
                    <button key="rnd" title="Random flower"
                      className={'ios-pick ios-fpick' + (d.flower < 0 ? ' sel' : '')}
                      style={{ animationDelay: '.15s' }}
                      onClick={() => { set({ flower: -1 }); setPick(null); }}>🎲</button>
                  </div>
                : <button className="ios-pick ios-fpick" onClick={() => setPick('flower')}>
                    {d.flower >= 0
                      ? <img className="ios-fimg" src={'flowers/flower_' + d.flower + '.png'} alt={IOS_FLOWERS[d.flower]} />
                      : <span style={{ fontSize: 15 }}>🎲</span>}
                  </button>}</div>
            <div className="ios-actions">
              <button className="ios-addbtn" onClick={() => addTask(d)}>Add task</button>
              <button className="ios-cancel" onClick={cancel}>Cancel</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ───────────────────── Stickies (port) ──────────────────────────────────
function IOSSNote({ n, setNote, onDel }) {
  const paper = ios_toneOf(n.tone).paper;
  const ink = ios_inkFor(paper);
  const [palette, setPalette] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!palette) return;
    const off = e => { if (ref.current && !ref.current.contains(e.target)) setPalette(false); };
    document.addEventListener('pointerdown', off, true);
    return () => document.removeEventListener('pointerdown', off, true);
  }, [palette]);
  return (
    <div className="ios-snote" style={{ background: ios_hexA(paper, n.opacity), color: ink }}>
      <div className="stop">
        <button className={'sbtn pin' + (n.pinned ? ' on' : '')} onClick={() => setNote(n.id, { pinned: !n.pinned })} title="Pin">{ios_svg(IOS_IC.pin, { size: 17, sw: 1.7, fill: n.pinned ? 'currentColor' : 'none' })}</button>
        <button className="sbtn" onClick={() => onDel(n.id)} title="Delete">{ios_svg(IOS_IC.x, { size: 17, sw: 1.7 })}</button>
      </div>
      <div className="sbody" contentEditable suppressContentEditableWarning onBlur={e => setNote(n.id, { body: e.currentTarget.innerText })}>{n.body}</div>
      <div className="sctrl" style={{ color: ink }} ref={ref}>
        <span className="ios-cbtn" style={{ background: paper }} title="Colour" onClick={() => setPalette(p => !p)} />
        {palette && (
          <div className="ios-cpop">
            {IOS_NOTE_TONES.map((tn, i) => (
              <i key={tn.key} className={tn.key === n.tone ? 'on' : ''} style={{ background: tn.paper, animationDelay: i * 0.03 + 's' }}
                onClick={() => { setNote(n.id, { tone: tn.key }); setPalette(false); }} />
            ))}
          </div>
        )}
        <span className="ios-op" style={{ color: ink }}><label>α</label><input type="range" min="0.4" max="1" step="0.05" value={n.opacity} onChange={e => setNote(n.id, { opacity: +e.target.value })} /></span>
      </div>
    </div>
  );
}

// ───────────────────── Screens ──────────────────────────────────────────
function IOSTodoScreen({ tasks, doneTasks, doneToday, setTask, complete, deleteTodo, clearHistory,
                        composing, addTask, cancelCompose }) {
  const [mode, setMode] = React.useState('day');
  const open = tasks.length;

  // ── History view: completed tasks, each deletable; clear-all button. ──
  if (mode === 'history') {
    return (
      <div className="ios-body">
        <div className="ios-lt">
          <h1>History</h1>
          <div className="sub">{doneTasks.length} completed</div>
        </div>
        <div className="ios-ctrl">
          {/* Back + Clear-all grouped together on the right (back to the
              left of Clear all). */}
          <div className="ios-hist" style={{ marginLeft: 'auto', gap: 4 }}>
            <button onClick={() => setMode('day')}>
              {ios_svg(IOS_IC.back, { size: 15, sw: 1.8 })}To-Do
            </button>
            <button onClick={clearHistory} disabled={!doneTasks.length}
              style={{ color: doneTasks.length ? '#e0726a' : 'var(--ter)' }}>Clear all</button>
          </div>
        </div>
        <div className="ios-cards">
          {doneTasks.map(t => (
            <div key={t.id} className="ios-card done" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="ios-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</div>
              </div>
              {/* Restore (un-complete) */}
              <button className="nbtn" title="Restore" onClick={() => complete(t.id)}
                style={{ color: 'var(--sec)' }}>↩</button>
              {/* Permanently delete */}
              <button className="nbtn" title="Delete forever" onClick={() => deleteTodo(t.id)}
                style={{ color: '#e0726a' }}>✕</button>
            </div>
          ))}
          {!doneTasks.length && <div className="ios-empty">No completed tasks yet.</div>}
        </div>
        <div style={{ height: 24 }} />
      </div>
    );
  }

  return (
    <div className="ios-body">
      <div className="ios-lt">
        <h1>To-Do</h1>
        <div className="sub">{open} open{doneToday ? <span style={{ color: 'var(--accent)', fontWeight: 600 }}> · {doneToday} done today 🌸</span> : ''}</div>
      </div>
      {(() => {
        const done = doneTasks.length, total = tasks.length + done;
        const pct = total ? Math.round(done / total * 100) : 0;
        return total > 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 20px 12px' }}>
            <div style={{ flex: 1, minWidth: 0, height: 6, borderRadius: 4, background: 'rgba(255,255,255,.08)', overflow: 'hidden' }}>
              <div style={{ width: pct + '%', height: '100%', borderRadius: 4,
                            background: 'var(--accent)', transition: 'width .3s' }} />
            </div>
            <span style={{ fontSize: 12, color: 'var(--sec)', whiteSpace: 'nowrap', fontWeight: 600 }}>
              {done}/{total} done
            </span>
          </div>
        ) : null;
      })()}
      <div className="ios-ctrl">
        <div className="ios-seg2">
          <button className={mode === 'day' ? 'on' : ''} onClick={() => setMode('day')}>By day</button>
          <button className={mode === 'all' ? 'on' : ''} onClick={() => setMode('all')}>All</button>
        </div>
        <div className="ios-hist">
          <button title="History" onClick={() => setMode('history')}>
            {ios_svg(IOS_IC.history || IOS_IC.back, { size: 15, sw: 1.8 })}
            History{doneTasks.length ? ` (${doneTasks.length})` : ''}
          </button>
        </div>
      </div>

      {composing && <IOSComposer addTask={addTask} cancel={cancelCompose} />}

      {mode === 'all' ? (
        <>
          <div className="ios-sec"><h2>All</h2><span className="cnt">{open}</span><span className="sub">everything</span></div>
          <div className="ios-cards">
            {tasks.map(t => <IOSTaskCard key={t.id} t={t} setTask={setTask} complete={complete} />)}
            {!tasks.length && <div className="ios-empty">No open tasks — nice.</div>}
          </div>
          <div style={{ height: 24 }} />
        </>
      ) : (
        <>
          {IOS_DAY_ORDER.map(d => {
            const items = tasks.filter(t => t.day === d);
            if (!items.length) return null;
            const sub = d === 'Past due' ? `${items.length} overdue` : (items[0] && ios_subFor(d, items[0].iso));
            return (
              <div key={d}>
                <div className="ios-sec"><h2>{d}</h2><span className="cnt">{items.length}</span><span className="sub">{sub}</span></div>
                <div className="ios-cards">{items.map(t => <IOSTaskCard key={t.id} t={t} setTask={setTask} complete={complete} />)}</div>
              </div>
            );
          })}
          {!tasks.length && <div className="ios-empty">No open tasks — nice.</div>}
          <div style={{ height: 24 }} />
        </>
      )}
    </div>
  );
}

function IOSStickiesScreen({ notes, setNote, onDel }) {
  const ordered = [...notes].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  return (
    <div className="ios-body">
      <div className="ios-lt"><h1>Stickies</h1><div className="sub">{notes.length} note{notes.length !== 1 ? 's' : ''}</div></div>
      <div className="ios-notes">{ordered.map(n => <IOSSNote key={n.id} n={n} setNote={setNote} onDel={onDel} />)}
        {!ordered.length && <div className="ios-empty">No stickies yet — tap ✎ above to add one.</div>}
      </div>
    </div>
  );
}

// A pinned-window name that clips to its lane and, only when the title is
// too long to fit, slowly marquee-scrolls so it never runs under Remove.
function IOSPinTitle({ text }) {
  const wrapRef = React.useRef(null);
  const txtRef  = React.useRef(null);
  const [shift, setShift] = React.useState(0);
  React.useLayoutEffect(() => {
    const w = wrapRef.current, t = txtRef.current;
    if (!w || !t) return;
    const over = t.scrollWidth - w.clientWidth;
    setShift(over > 6 ? over + 6 : 0);   // +6 so the last glyph fully clears
  }, [text]);
  return (
    <span ref={wrapRef} className={'pin-name' + (shift ? ' scroll' : '')}
          style={{ '--pin-shift': (-shift) + 'px' }}>
      <span ref={txtRef}>{text}</span>
    </span>
  );
}

// Settings building blocks — MODULE-LEVEL so their identities are stable.
// (Defining them inside IOSSettingsScreen made every keystroke re-create the
// component types, which remounted the subtree and kicked focus out of the
// number inputs after a single edit.)
const SetTog    = ({ on }) => <span className={'ios-sw2' + (on ? ' on' : '')}><i /></span>;
const SetRow    = ({ k, sub, children }) => <div className="ios-set"><span className="k">{k}{sub && <small>{sub}</small>}</span>{children}</div>;
const SetGrp    = ({ label, children }) => <div className="ios-grp">{label && <div className="glab">{label}</div>}<div className="box">{children}</div></div>;
const SetSwitch = ({ on, onClick }) => (
  <span className={'ios-sw2' + (on ? ' on' : '')} onClick={onClick}
    style={{ cursor: 'pointer' }}><i /></span>
);

function IOSSettingsScreen({ bridge, onSyncCanvas, syncMsg, light, setLight }) {
  // Local aliases so the JSX below reads the same as before.
  const Tog = SetTog, Row = SetRow, Grp = SetGrp, Switch = SetSwitch;

  // ── Canvas iCal feed URL ──
  const [canvasUrl, setCanvasUrl] = React.useState('');
  const [savedUrl,  setSavedUrl]  = React.useState('');
  const [saving,    setSaving]    = React.useState(false);
  React.useEffect(() => {
    if (!bridge || !bridge.getCanvasURL) return;
    try { bridge.getCanvasURL((u) => { setCanvasUrl(u || ''); setSavedUrl(u || ''); }); }
    catch (e) {}
  }, [bridge]);
  const saveUrl = () => {
    if (!bridge || !bridge.setCanvasURL) return;
    setSaving(true);
    try {
      bridge.setCanvasURL(canvasUrl.trim());
      setSavedUrl(canvasUrl.trim());
    } catch (e) {}
    setTimeout(() => setSaving(false), 400);
  };
  const dirty = canvasUrl.trim() !== savedUrl.trim();
  const connected = !!savedUrl.trim();

  // ── Timer settings (dynamic-island pill) — pomodoro length, quick
  //    timer length, and Start buttons that launch the timer ON the pill.
  const [pomo, setPomo]   = React.useState(25);
  const [pomoSaved, setPomoSaved] = React.useState(25);
  const [qmin, setQmin]   = React.useState(5);
  const [qminSaved, setQminSaved] = React.useState(5);
  const [islandPrefs, setIslandPrefs] = React.useState(null);
  React.useEffect(() => {
    if (!bridge || !bridge.getIslandPrefs) return;
    try {
      bridge.getIslandPrefs((j) => {
        let p = {}; try { p = JSON.parse(j || '{}'); } catch (e) {}
        setIslandPrefs(p);
        const pm = parseInt(p.pomodoro_minutes, 10);
        const pv = (pm >= 1 && pm <= 180) ? pm : 25;
        setPomo(pv); setPomoSaved(pv);
        const tm = parseInt(p.timer_minutes, 10);
        const tv = (tm >= 1 && tm <= 180) ? tm : 5;
        setQmin(tv); setQminSaved(tv);
      });
    } catch (e) {}
  }, [bridge]);
  // Merge a partial change into island prefs + persist.  Guarded on a
  // loaded prefs object so we never clobber the island's other settings.
  const patchIsland = (patch) => {
    if (!bridge || !bridge.saveIslandPrefs || islandPrefs == null) return null;
    const next = Object.assign({}, islandPrefs || {}, patch);
    try { bridge.saveIslandPrefs(JSON.stringify(next)); } catch (e) {}
    setIslandPrefs(next);
    return next;
  };
  const savePomo = () => {
    const v = Math.max(1, Math.min(180, parseInt(pomo, 10) || 25));
    if (patchIsland({ pomodoro_minutes: v })) { setPomoSaved(v); setPomo(v); }
  };
  const saveQmin = () => {
    const v = Math.max(1, Math.min(180, parseInt(qmin, 10) || 5));
    if (patchIsland({ timer_minutes: v })) { setQminSaved(v); setQmin(v); }
  };
  // Which Start button just fired ('' | 'pomodoro' | 'timer'), so the
  // button can flash "Started ✓" for a moment as visual feedback.
  const [started, setStarted] = React.useState('');   // mode currently running (persists)
  const [flash, setFlash]     = React.useState('');   // mode just-confirmed (transient ✓)
  const startedTO = React.useRef(null);
  // Start a timer ON the pill: set its mode + length, then bump the
  // start token so the running pill (re)starts a fresh countdown.
  const startTimer = (mode) => {
    if (islandPrefs == null) return;
    const mins = mode === 'timer'
      ? Math.max(1, Math.min(180, parseInt(qmin, 10) || 5))
      : Math.max(1, Math.min(180, parseInt(pomo, 10) || 25));
    const tok = (parseInt(islandPrefs.timer_start_token, 10) || 0) + 1;
    const patch = mode === 'timer'
      ? { timer_mode: 'timer', timer_minutes: mins, timer_start_token: tok }
      : { timer_mode: 'pomodoro', pomodoro_minutes: mins, timer_start_token: tok };
    patchIsland(patch);
    if (mode === 'timer') { setQminSaved(mins); } else { setPomoSaved(mins); }
    // This mode is now running — keep it marked (button becomes "Reset",
    // doesn't snap back to "Start") and flash a slow "Started ✓" confirm.
    setStarted(mode);
    setFlash(mode);
    if (startedTO.current) clearTimeout(startedTO.current);
    startedTO.current = setTimeout(() => setFlash(''), 1800);
  };
  // Reset → tell the pill to stop + reset its countdown, and revert the
  // button back to "Start".
  const resetTimer = (mode) => {
    if (islandPrefs != null) {
      const tok = (parseInt(islandPrefs.timer_stop_token, 10) || 0) + 1;
      patchIsland({ timer_stop_token: tok });
    }
    if (startedTO.current) clearTimeout(startedTO.current);
    setStarted(''); setFlash('');
  };
  const pomoDirty = parseInt(pomo, 10) !== pomoSaved;
  const qminDirty = parseInt(qmin, 10) !== qminSaved;
  // Start → confirms with a slow green "Started ✓", then settles to a green
  // "Reset".  Clicking Reset stops the timer and returns to "Start".
  const StartBtn = ({ mode }) => {
    const isOn    = started === mode;
    const isFlash = flash === mode;
    const onClick = () => { if (isOn && !isFlash) resetTimer(mode); else startTimer(mode); };
    const play = <svg width="9" height="11" viewBox="0 0 9 11" aria-hidden="true"><path d="M0 0l9 5.5L0 11z" fill="currentColor" /></svg>;
    return (
      <button className={'ios-start' + ((isOn || isFlash) ? ' run' : '')} onClick={onClick}>
        {isFlash ? '✓ Started' : isOn ? 'Reset' : <>{play}Start</>}
      </button>
    );
  };

  // ── World decor settings (flowers / rocks) + pill on/off ──────────────
  const [world, setWorld] = React.useState(null);   // world_settings.json
  React.useEffect(() => {
    if (!bridge || !bridge.getWorldSettings) return;
    const fetchWorld = () => {
      try { bridge.getWorldSettings((j) => {
        let w = {}; try { w = JSON.parse(j || '{}'); } catch (e) {}
        setWorld(w);
      }); } catch (e) {}
    };
    fetchWorld();
    // Re-poll so changes made outside the hub show up here — e.g. pressing Esc
    // to leave block mode writes block_mode=false and flips the toggle.
    const id = setInterval(fetchWorld, 1500);
    return () => clearInterval(id);
  }, [bridge]);
  // Run-on-startup (Windows HKCU\...\Run entry), read/written via the bridge.
  const [launchLogin, setLaunchLogin] = React.useState(false);
  React.useEffect(() => {
    if (!bridge || !bridge.getLaunchAtLogin) return;
    try { bridge.getLaunchAtLogin((on) => setLaunchLogin(!!on)); } catch (e) {}
  }, [bridge]);
  const toggleLaunchLogin = () => {
    const next = !launchLogin;
    setLaunchLogin(next);
    try { bridge.setLaunchAtLogin(next); } catch (e) {}
  };
  const patchWorld = (patch) => {
    if (!bridge || !bridge.saveWorldSettings || world == null) return;
    const next = Object.assign({}, world, patch);
    setWorld(next);
    try { bridge.saveWorldSettings(JSON.stringify(patch)); } catch (e) {}
  };
  // Pill on/off lives in island prefs (enabled).
  const pillOn = islandPrefs ? islandPrefs.enabled !== false : true;
  const togglePill = () => patchIsland({ enabled: !pillOn });
  // ── Window pinning ────────────────────────────────────────────────
  const [pins, setPins] = React.useState([]);
  const [armed, setArmed] = React.useState(false);
  const refreshPins = React.useCallback(() => {
    if (!bridge || !bridge.getPinnedWindows) return;
    try { bridge.getPinnedWindows((j) => {
      let list = []; try { list = JSON.parse(j || '[]'); } catch (e) {}
      setPins(Array.isArray(list) ? list : []);
    }); } catch (e) {}
  }, [bridge]);
  React.useEffect(() => {
    refreshPins();
    // Poll while the settings screen is open so a freshly-pinned window
    // shows up in the list a moment after the user clicks it.
    const iv = setInterval(refreshPins, 1500);
    return () => clearInterval(iv);
  }, [refreshPins]);
  const addPin = () => {
    if (!bridge || !bridge.armPinMode) return;
    try { bridge.armPinMode(); } catch (e) {}
    setArmed(true);
    setTimeout(() => setArmed(false), 6000);
  };
  const removePin = (hwnd) => {
    if (!bridge || !bridge.removePin) return;
    try { bridge.removePin(hwnd); } catch (e) {}
    setPins(pins.filter(p => p.hwnd !== hwnd));
    setTimeout(refreshPins, 200);
  };

  return (
    <div className="ios-body" style={{ paddingTop: 6 }}>
      <Grp label="Canvas">
        {/* iCal feed URL — paste once, hit Save, then Sync any time. */}
        <div className="ios-set" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8, paddingBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="k" style={{ flex: 1 }}>
              iCal feed URL
              <small>{connected
                ? (<span style={{ color: '#5fc2a6' }}>✓ Connected · paste a different link to change</span>)
                : 'Canvas → Calendar → Calendar Feed (bottom-right)'}</small>
            </span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={canvasUrl}
              onChange={(e) => setCanvasUrl(e.target.value)}
              placeholder="https://canvas.<school>.edu/feeds/calendars/user_xxxxx.ics"
              spellCheck={false}
              style={{
                flex: 1, padding: '8px 12px', background: 'var(--well)',
                border: '1px solid var(--line)', borderRadius: 9,
                color: 'var(--label)', fontFamily: 'inherit',
                fontSize: 12.5, outline: 'none',
              }}
            />
            <button className="ios-pick" onClick={saveUrl}
              style={{ background: dirty ? 'var(--accent)' : 'rgba(255,255,255,.06)',
                       color: dirty ? '#fff' : 'var(--sec)',
                       opacity: dirty ? 1 : 0.6 }}
              disabled={!dirty}>
              {saving ? 'Saved' : 'Save'}
            </button>
          </div>
        </div>
        <Row k="Sync now"
             sub={syncMsg || (connected
                              ? 'Pull the latest from your Canvas iCal feed'
                              : 'Save a feed URL above first')}>
          <button className="ios-pick" onClick={onSyncCanvas} disabled={!connected}
            style={{ opacity: connected ? 1 : 0.5 }}>Sync</button>
        </Row>
      </Grp>
      <Grp label="Timer island">
        {/* Show / hide the floating pill, plus the fullscreen auto-hide —
            kept here alongside the two timer options it drives. */}
        <Row k="Show timer island" sub="The floating timer pill at the top of the screen">
          <Switch on={pillOn} onClick={togglePill} />
        </Row>
        <Row k="Hide pill in fullscreen" sub="Tuck the pill away during games / video">
          <Switch on={islandPrefs ? islandPrefs.hide_fullscreen !== false : true}
            onClick={() => patchIsland({ hide_fullscreen: !(islandPrefs ? islandPrefs.hide_fullscreen !== false : true) })} />
        </Row>
        {/* Pomodoro: set the focus length, Save to keep it, Start to run
            it on the dynamic-island pill right now. */}
        <Row k="Pomodoro" sub="Focus length in minutes — shows + runs on the pill">
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="number" min={1} max={180} value={pomo}
              onChange={(e) => setPomo(e.target.value)}
              style={{
                width: 52, padding: '6px 8px', textAlign: 'center',
                background: 'var(--well)', border: '1px solid var(--line)',
                borderRadius: 9, color: 'var(--label)', fontFamily: 'inherit',
                fontSize: 13, outline: 'none',
              }}
            />
            <button className="ios-pick" onClick={savePomo}
              style={{ background: pomoDirty ? 'var(--accent)' : 'rgba(255,255,255,.06)',
                       color: pomoDirty ? '#fff' : 'var(--sec)',
                       opacity: pomoDirty ? 1 : 0.6 }}
              disabled={!pomoDirty}>Save</button>
            <StartBtn mode="pomodoro" />
          </div>
        </Row>
        {/* Quick timer: a plain countdown of N minutes. */}
        <Row k="Quick timer" sub="A simple countdown — shows + runs on the pill">
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="number" min={1} max={180} value={qmin}
              onChange={(e) => setQmin(e.target.value)}
              style={{
                width: 52, padding: '6px 8px', textAlign: 'center',
                background: 'var(--well)', border: '1px solid var(--line)',
                borderRadius: 9, color: 'var(--label)', fontFamily: 'inherit',
                fontSize: 13, outline: 'none',
              }}
            />
            <button className="ios-pick" onClick={saveQmin}
              style={{ background: qminDirty ? 'var(--accent)' : 'rgba(255,255,255,.06)',
                       color: qminDirty ? '#fff' : 'var(--sec)',
                       opacity: qminDirty ? 1 : 0.6 }}
              disabled={!qminDirty}>Save</button>
            <StartBtn mode="timer" />
          </div>
        </Row>
        {/* Focus mode — one switch to clear the screen of Sao + critters +
            flowers + rocks while you work, without losing your per-item prefs. */}
        <Row k="Focus mode" sub="Reduce distractions: hide Sao, critters, flowers & rocks">
          <Switch on={!!(world && world.focus_mode)}
            onClick={() => patchWorld({ focus_mode: !(world && world.focus_mode) })} />
        </Row>
      </Grp>

      <Grp label="Desktop & decor">
        <Row k="Sao" sub="The cat who lives on your taskbar">
          <Switch on={!(world && world.cat_hidden)}
            onClick={() => patchWorld({ cat_hidden: !(world && world.cat_hidden) })} />
        </Row>
        <Row k="Ladybugs" sub="The occasional ladybug that wanders by">
          <Switch on={!(world && world.ladybugs_hidden)}
            onClick={() => patchWorld({ ladybugs_hidden: !(world && world.ladybugs_hidden) })} />
        </Row>
        <Row k="Butterflies" sub="Butterflies that flutter past">
          <Switch on={!(world && world.butterflies_hidden)}
            onClick={() => patchWorld({ butterflies_hidden: !(world && world.butterflies_hidden) })} />
        </Row>
        <Row k="Friend bugs" sub="Little pastel bugs that land on a still cursor">
          <Switch on={!(world && world.friendbugs_hidden)}
            onClick={() => patchWorld({ friendbugs_hidden: !(world && world.friendbugs_hidden) })} />
        </Row>
        <Row k="Flowers" sub="Task flowers + garden plants on the taskbar">
          <Switch on={!(world && world.flowers_hidden)}
            onClick={() => patchWorld({ flowers_hidden: !(world && world.flowers_hidden) })} />
        </Row>
        <Row k="Rocks" sub="Decorative rocks scattered on the ground">
          <Switch on={!(world && world.rocks_hidden)}
            onClick={() => patchWorld({ rocks_hidden: !(world && world.rocks_hidden) })} />
        </Row>
        <Row k="Grass" sub="How many grass tufts — sways on a breeze & when you brush past">
          <input type="range" className="ios-range" min="0" max="100" step="5"
            style={{ width: 128 }}
            value={world && world.grass_density != null ? world.grass_density : 35}
            onChange={e => patchWorld({ grass_density: +e.target.value })} />
        </Row>
        <Row k="Grass bed" sub="Short backing grass that fills the gaps into a full lawn">
          <input type="range" className="ios-range" min="0" max="100" step="5"
            style={{ width: 128 }}
            value={world && world.grass_bed != null ? world.grass_bed : 0}
            onChange={e => patchWorld({ grass_bed: +e.target.value })} />
        </Row>
        <Row k="Extra tall grass" sub="Makes ~30% of the grass tufts grow extra tall for variation">
          <Switch on={!!(world && world.extra_tall_grass)}
            onClick={() => patchWorld({ extra_tall_grass: !(world && world.extra_tall_grass) })} />
        </Row>
        <Row k="Extra rocks" sub="Scatter a few more pebbles across the ground">
          <input type="range" className="ios-range" min="0" max="100" step="5"
            style={{ width: 128 }}
            value={world && world.rock_density != null ? world.rock_density : 0}
            onChange={e => patchWorld({ rock_density: +e.target.value })} />
        </Row>
        <Row k="Gween bean 🫛" sub="Green bugs, mossy rocks & Sao stays her usual self">
          <Switch on={!!(world && world.greenbeans)}
            onClick={() => patchWorld({ greenbeans: !(world && world.greenbeans) })} />
        </Row>
        <Row k="Feed Sao" sub="Press & drag this macaron onto the desktop — she'll chase it & eat it">
          <div
            title="Drag me onto the desktop!"
            onMouseDown={() => { try { bridge && bridge.feedMacaron && bridge.feedMacaron(); } catch (e) {} }}
            style={{ width: 34, cursor: 'grab', userSelect: 'none' }}>
            <div style={{ height: 9, background: 'linear-gradient(#f4b9d6,#e58fb6)',
                          borderRadius: '9px 9px 4px 4px' }} />
            <div style={{ height: 5, background: '#ffe4be', margin: '0 1px' }} />
            <div style={{ height: 9, background: 'linear-gradient(#e58fb6,#d97fa9)',
                          borderRadius: '4px 4px 9px 9px' }} />
          </div>
        </Row>
        <Row k="Block mode 🧱" sub="Click to place/erase blocks, right-click removes, R switches dirt/grass, Esc exits">
          <Switch on={!!(world && world.block_mode)}
            onClick={() => patchWorld({ block_mode: !(world && world.block_mode) })} />
        </Row>
        <Row k="Beach ball 🏖️" sub="Drop a bouncy ball — Sao bats it around with her paw. Pick its colour →">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="color"
              value={(world && world.ball_color) || '#eb5a5a'}
              onChange={e => patchWorld({ ball_color: e.target.value })}
              style={{ width: 28, height: 24, border: 'none', background: 'none', cursor: 'pointer' }} />
            <button
              onClick={() => { try { bridge && bridge.spawnBall && bridge.spawnBall(); } catch (e) {} }}
              style={{ background: 'linear-gradient(135deg,#7fc5e8,#4aa3d6)', color: '#0c2a3a',
                       border: 'none', borderRadius: 10, padding: '6px 14px', fontWeight: 700,
                       fontSize: 13, cursor: 'pointer' }}>
              Drop ball
            </button>
          </div>
        </Row>
      </Grp>

      <Grp label="Window pinning">
        <Row k="Pin a window"
             sub={armed ? 'Now click any window to keep it on top…'
                        : 'Keep any window always on top of others'}>
          <button className="ios-pick" onClick={addPin}
            style={{ background: armed ? '#3ea06d' : 'var(--accent)', color: '#fff' }}>
            {armed ? 'Click a window' : 'Add pin'}
          </button>
        </Row>
        {pins.map((p, i) => (
          <div key={p.hwnd} className="ios-set" style={{ gap: 8 }}>
            <span className="k" style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
              <span style={{ width: 9, height: 9, borderRadius: '50%',
                             background: '#6f8cd6', flex: '0 0 auto' }} />
              <IOSPinTitle text={p.title || `Pin ${i + 1}`} />
            </span>
            <button className="ios-pick" onClick={() => removePin(p.hwnd)}
              style={{ background: 'rgba(255,255,255,.06)', color: '#e0726a', flex: '0 0 auto' }}>Remove</button>
          </div>
        ))}
        {!pins.length && (
          <Row k="No pinned windows" sub="Pinned windows show a small dot near their close button" />
        )}
      </Grp>

      <Grp label="General">
        <Row k="Launch at login" sub="Start Sao automatically when Windows starts">
          <Switch on={launchLogin} onClick={toggleLaunchLogin} />
        </Row>
        <Row k="Sound effects" sub="Task chime, timer bell & Sao's little blips">
          <Switch on={!!world && world.sound_effects !== false}
            onClick={() => {
              const next = !(world && world.sound_effects !== false);
              patchWorld({ sound_effects: next });
              IOS_SOUND_ENABLED = next;   // task-complete chime, live
            }} />
        </Row>
        <Row k="Light mode" sub={light ? 'Light theme' : 'Dark theme (default)'}>
          <Switch on={light} onClick={() => setLight(!light)} />
        </Row>
      </Grp>
    </div>
  );
}

// ───────────────────── Root wrapper ─────────────────────────────────────
function IOSApp({ bridge, onWinMin, onWinClose, onWinMax }) {
  const [view, setView] = React.useState('todo');
  const [prev, setPrev] = React.useState('todo');
  const [composing, setComposing] = React.useState(false);
  const [rawTodos, setRawTodos] = React.useState([]);
  const [rawStickies, setRawStickies] = React.useState([]);
  const [syncMsg, setSyncMsg] = React.useState(null);
  const [light, setLight] = React.useState(() => {
    try { return localStorage.getItem('sao_light') === '1'; } catch (e) { return false; }
  });
  React.useEffect(() => {
    try { localStorage.setItem('sao_light', light ? '1' : '0'); } catch (e) {}
  }, [light]);

  // Initial load + bridge subscriptions.  Source of truth = library_todos.json
  // via getLibraryTodos (already merged Canvas + manual on the Python side).
  // syncCanvas refreshes the Canvas portion + we re-pull to pick up new items.
  React.useEffect(() => {
    if (!bridge) return;
    const loadTodos = () => {
      try {
        const cb = (json) => {
          try { const arr = JSON.parse(json || '[]'); if (Array.isArray(arr)) setRawTodos(arr); }
          catch (e) { /* ignore */ }
        };
        if (bridge.getLibraryTodos) bridge.getLibraryTodos(cb);
        else if (bridge.getCanvasTodos) bridge.getCanvasTodos(cb);
      } catch (e) { /* ignore */ }
    };
    const loadStickies = () => {
      try {
        bridge.getStickies((json) => {
          try { const arr = JSON.parse(json || '[]'); if (Array.isArray(arr)) setRawStickies(arr); }
          catch (e) { /* ignore */ }
        });
      } catch (e) { /* ignore */ }
    };
    loadTodos(); loadStickies();
    // Listen for sticky updates pushed from Python (floating window edits).
    try { bridge.stickiesUpdated && bridge.stickiesUpdated.connect(loadStickies); } catch (e) {}
  }, [bridge]);

  // Mirror the global sound_effects toggle so the task-complete chime
  // honours it (the user may have sound effects muted).
  React.useEffect(() => {
    if (!bridge || !bridge.getWorldSettings) return;
    try {
      bridge.getWorldSettings((j) => {
        try { const w = JSON.parse(j || '{}'); IOS_SOUND_ENABLED = !!w && w.sound_effects !== false; }
        catch (e) {}
      });
    } catch (e) {}
  }, [bridge]);

  const persistTodos = (next) => {
    setRawTodos(next);
    if (bridge && bridge.saveLibraryTodos) {
      try { bridge.saveLibraryTodos(JSON.stringify(next)); } catch (e) {}
    }
  };
  const persistStickies = (next) => {
    setRawStickies(next);
    if (bridge && bridge.saveStickies) {
      try { bridge.saveStickies(JSON.stringify(next)); } catch (e) {}
    }
  };

  // ── derive iOS-shape tasks from raw bridge data ──
  const tasks = React.useMemo(
    () => rawTodos.filter(t => !t.done).map(ios_taskFromBridge),
    [rawTodos]
  );
  // Completed tasks, for the History view.
  const doneTasks = React.useMemo(
    () => rawTodos.filter(t => t.done).map(ios_taskFromBridge),
    [rawTodos]
  );
  // How many tasks were completed *today* (for the To-Do header).
  const doneToday = React.useMemo(() => {
    const todayIso = ios_today().toISOString().slice(0, 10);
    return rawTodos.filter(t => t.done && t.completedAt === todayIso).length;
  }, [rawTodos]);
  const notes = React.useMemo(
    () => rawStickies.map(ios_noteFromBridge),
    [rawStickies]
  );

  // ── mutations ──
  const setTask = (id, patch) => {
    const next = rawTodos.map(t => {
      if (t.id !== id) return t;
      const it = ios_taskFromBridge(t);
      Object.assign(it, patch);
      return ios_taskToBridge(it);
    });
    persistTodos(next);
  };
  // Completing a task now MARKS it done (keeps it for history) instead
  // of deleting it.  The open views filter !done; the History view shows
  // the done ones.  Toggling done on a history item un-completes it.
  const complete = (id) => {
    const todayIso = ios_today().toISOString().slice(0, 10);
    persistTodos(rawTodos.map(t => {
      if (t.id !== id) return t;
      const nowDone = !t.done;
      // Stamp the completion day so "done today" survives reloads.
      return { ...t, done: nowDone, completedAt: nowDone ? todayIso : null };
    }));
  };
  // Permanently remove a single todo (used by History → delete).
  const deleteTodo = (id) => {
    persistTodos(rawTodos.filter(t => t.id !== id));
  };
  // Permanently clear all completed todos.
  const clearHistory = () => {
    persistTodos(rawTodos.filter(t => !t.done));
  };
  const addTask = (d) => {
    // Translate composer fields → bridge shape.  Day → iso (best-effort).
    const td = ios_today();
    let iso = null;
    if (d.day === 'Custom' && d.iso) iso = d.iso;
    else if (d.day === 'Today') iso = td.toISOString().slice(0,10);
    else if (d.day === 'Tomorrow') { const x = new Date(td); x.setDate(x.getDate()+1); iso = x.toISOString().slice(0,10); }
    else if (d.day === 'Next week') { const x = new Date(td); x.setDate(x.getDate()+7); iso = x.toISOString().slice(0,10); }
    const rec = {
      id:     'manual:' + Date.now(),
      name:   (d.title || '').trim() || 'Untitled task',
      due:    iso,
      done:   false,
      source: 'manual',
      pri:    d.pri,
      list:   d.list,
      note:   d.note || '',
      flower: (typeof d.flower === 'number') ? d.flower : -1,
    };
    persistTodos([rec, ...rawTodos]);
    setComposing(false);
  };

  const setNote = (id, patch) => {
    const next = rawStickies.map((s, i) => {
      const cur = ios_noteFromBridge(s, i);
      if (cur.id !== id) return s;
      Object.assign(cur, patch);
      return ios_noteToBridge(cur);
    });
    persistStickies(next);
  };
  const delNote = (id) => {
    const next = rawStickies.filter((s, i) => (s.id || ('s' + i)) !== id);
    persistStickies(next);
  };
  const newNote = () => {
    const rec = {
      id: 'sticky:' + Date.now(),
      title: '',
      body: '',
      body_html: '',
      body_font_pt: 12,
      color: '#ffe1a0',
      fade_strength: 0,
      pinned: false,
    };
    persistStickies([rec, ...rawStickies]);
  };

  const goSettings = () => { setPrev(view === 'settings' ? prev : view); setView('settings'); };
  const onSyncCanvas = () => {
    if (!bridge || !bridge.syncCanvas) { setSyncMsg('No bridge connection.'); return; }
    setSyncMsg('Syncing…');
    try {
      bridge.syncCanvas((msg) => {
        setSyncMsg(msg || 'Synced.');
        // After Canvas refresh, merge the new Canvas items into rawTodos.
        try {
          bridge.getCanvasTodos((cjson) => {
            try {
              const canvasItems = JSON.parse(cjson || '[]');
              if (!Array.isArray(canvasItems)) return;
              // De-dupe by id: keep manual items + replace any existing
              // canvas:* ids with the freshly-synced ones.  Preserve the
              // done state of canvas items we already had (so completing
              // a Canvas todo survives a re-sync).
              const manual = rawTodos.filter(t => !String(t.id).startsWith('canvas:'));
              const prevDone = {};
              rawTodos.forEach(t => { if (t.done) prevDone[t.id] = true; });
              const mapped = canvasItems.map(c => {
                // Canvas records use uid / title / start_iso; the due date
                // is the ISO start trimmed to YYYY-MM-DD.
                const id = 'canvas:' + (c.uid || c.id || c.title);
                const iso = c.start_iso || c.due || '';
                return {
                  id,
                  name: c.title || c.name || '(untitled)',
                  due: iso ? iso.slice(0, 10) : null,
                  done: !!prevDone[id],
                  source: 'canvas',
                  priority: c.priority || 'normal',
                  kind: c.kind || 'todo',
                };
              });
              const merged = [...mapped, ...manual];
              persistTodos(merged);
            } catch (e) {}
          });
        } catch (e) {}
      });
    } catch (e) { setSyncMsg('Sync failed.'); }
  };

  // Window drag — wire to bridge.startWindowDrag if it exists; else no-op.
  const onBarMouseDown = (e) => {
    if (e.button !== 0 || !bridge) return;
    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
    try { bridge.startWindowDrag && bridge.startWindowDrag(); } catch (err) {}
  };

  return (
    <div className={'ios' + (light ? ' light' : '')}>
      <div className="ios-win" onMouseDown={onBarMouseDown}
        onDoubleClick={() => { try { bridge && bridge.windowToggleMax && bridge.windowToggleMax(); } catch (e) {} }}>
        <button className="cl" title="Close" onClick={onWinClose}>
          <svg width="17" height="17" viewBox="0 0 17 17" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4.5 4.5l8 8M12.5 4.5l-8 8" />
          </svg>
        </button>
      </div>

      <div className="ios-nav">
        {view === 'settings'
          ? <button className="nbtn wide" onClick={() => setView(prev)}>{ios_svg(IOS_IC.back, { size: 19 })}Back</button>
          : <button className="nbtn" title="Settings" onClick={goSettings}>{ios_svg(IOS_IC.settings, { size: 21, sw: 1.9 })}</button>}
        {view === 'settings'
          ? <span className="ios-navtitle">Settings</span>
          : <div className="ios-seg">
              <button className={view === 'todo' ? 'on' : ''} onClick={() => setView('todo')}>To-Do</button>
              <button className={view === 'stickies' ? 'on' : ''} onClick={() => setView('stickies')}>Stickies</button>
            </div>}
        {view === 'settings' ? <span style={{ width: 38 }} />
          : <button className="nbtn add" title="New" onClick={() => view === 'todo' ? setComposing(true) : newNote()}>{ios_svg(IOS_IC.compose, { size: 19 })}</button>}
      </div>

      {view === 'todo' && <IOSTodoScreen tasks={tasks} doneTasks={doneTasks} doneToday={doneToday}
        setTask={setTask} complete={complete} deleteTodo={deleteTodo} clearHistory={clearHistory}
        composing={composing} addTask={addTask} cancelCompose={() => setComposing(false)} />}
      {view === 'stickies' && <IOSStickiesScreen notes={notes} setNote={setNote} onDel={delNote} />}
      {view === 'settings' && <IOSSettingsScreen bridge={bridge} onSyncCanvas={onSyncCanvas} syncMsg={syncMsg} light={light} setLight={setLight} />}
    </div>
  );
}

Object.assign(window, { IOSApp });
