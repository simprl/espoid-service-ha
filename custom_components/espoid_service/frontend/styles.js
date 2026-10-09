export const styles = `
:host { display:block; height:100%; overflow:auto; color:var(--primary-text-color,#202628); background:var(--primary-background-color,#f5f7f6); font:14px/1.5 system-ui,sans-serif; letter-spacing:0; }
* { box-sizing:border-box; } [hidden] { display:none !important; }
header { position:sticky; top:0; z-index:2; display:flex; align-items:center; gap:12px; min-height:64px; padding:8px 24px; border-bottom:1px solid var(--divider-color,#d7dfdb); background:var(--card-background-color,#fff); }
h1 { font-size:22px; font-weight:600; line-height:1.25; margin:0; } .header-actions { display:flex; gap:4px; margin-left:auto; }
main { max-width:1050px; margin:auto; padding:24px; } .device-bar { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
.device-bar label { margin:0; } .device-bar select { flex:1; min-width:180px; max-width:500px; } .address { font-family:ui-monospace,monospace; color:var(--secondary-text-color,#63716c); overflow-wrap:anywhere; margin:8px 0 18px; }
.connection { font-size:12px; font-weight:600; padding:3px 0; } .online { color:#168255; } .offline { color:var(--secondary-text-color,#737a78); }
nav { display:flex; gap:4px; overflow:auto; border-bottom:1px solid var(--divider-color,#d7dfdb); margin-bottom:22px; }
nav button { border:0; border-radius:0; background:none; white-space:nowrap; border-bottom:3px solid transparent; padding:12px 15px; }
nav button[aria-selected=true] { border-color:#168255; color:#168255; }
section { min-width:0; } button,select,input,textarea { font:inherit; color:inherit; letter-spacing:0; }
button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:40px; padding:8px 12px; border:1px solid var(--divider-color,#ccd6d0); border-radius:4px; background:var(--card-background-color,#fff); cursor:pointer; font-weight:500; }
button span { overflow-wrap:anywhere; } button:hover { border-color:#168255; } button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible { outline:2px solid #168255; outline-offset:2px; }
button:disabled { opacity:.45; cursor:default; } button.primary { background:#168255; border-color:#168255; color:white; }
button.icon { width:40px; height:40px; flex:0 0 40px; padding:8px; border-color:transparent; background:transparent; }
ha-icon { --mdc-icon-size:20px; width:20px; height:20px; flex:0 0 20px; }
label { display:block; font-weight:500; margin-bottom:8px; } input,select,textarea { display:block; background:var(--card-background-color,#fff); border:1px solid var(--divider-color,#ccd6d0); border-radius:4px; padding:9px 10px; min-height:42px; max-width:100%; width:100%; }
input[type=file] { font-size:13px; } textarea { min-height:330px; resize:vertical; font:13px/1.55 ui-monospace,monospace; tab-size:2; }
dl { display:grid; grid-template-columns:minmax(145px,1fr) minmax(0,2fr); margin:0 0 22px; border-top:1px solid var(--divider-color,#d7dfdb); }
dt,dd { margin:0; padding:9px 10px; border-bottom:1px solid var(--divider-color,#d7dfdb); overflow-wrap:anywhere; }
dt { color:var(--secondary-text-color,#63716c); } dd { font-variant-numeric:tabular-nums; }
.commands,.toolbar { display:flex; flex-wrap:wrap; gap:10px; margin:16px 0; align-items:center; }
.commands button { justify-content:flex-start; } .upload-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
.notice { padding:12px 14px; margin:0 0 18px; border-left:3px solid #168255; background:var(--card-background-color,#fff); overflow-wrap:anywhere; }
.notice.error { border-color:#c94848; } pre { max-height:600px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.6 ui-monospace,monospace; margin:0; }
@media(max-width:600px) { header { padding:8px 12px; gap:4px; } h1 { font-size:19px; } main { padding:16px 12px; } .device-bar { gap:8px; } .device-bar label { width:100%; } .connection { width:100%; } nav { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; overflow:visible; } nav button { font-size:12px; padding:10px 4px; white-space:normal; overflow-wrap:anywhere; } dl { grid-template-columns:minmax(115px,1fr) minmax(0,1fr); } dt,dd { padding:9px 5px; } .upload-grid { grid-template-columns:1fr; gap:12px; } .commands { display:grid; grid-template-columns:1fr; } .commands button { width:100%; } }
@media(prefers-reduced-motion:no-preference) { button { transition:border-color .12s,background-color .12s; } }
`;
