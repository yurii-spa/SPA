#!/usr/bin/env python3
"""Studio View — VISUAL DIRECTION prototype (isometric operations building).

Direction check ONLY (not the production renderer): an isometric floorplan of the studio
as *rooms with depth*, not flat cards. Every agent/task token is bound to the REAL current
read model (`read_model.json`) — real work items by zone, real owner decisions in the
Command Center; empty rooms are shown quiet (dimmed), never faked. Pure DOM/CSS/SVG so it
renders headless and on mobile with no build. Variants: desktop | wide | mobile (mobile is a
distinct mini-map + Owner-Home model, not stacked desktop rooms).

Emits studio_shell/studio_proto_<variant>.html. This is a mock to let Owner/ARB judge the
SPATIAL direction before committing a renderer (see STUDIO_VISUAL_V1_ARCHITECTURE_REPORT §E/F).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>Studio OS — Studio View direction</title>
<style>
:root{
  --bg:#080b12; --bg1:#0c1120; --ink:#e8edf7; --ink2:#9aa7c2; --ink3:#5c6885; --line:#20304e;
  --blue:#6ea8fe; --cyan:#4fd1c5; --violet:#8f7bff; --green:#3ecf8e; --gold:#f2c14e; --red:#ff6b6b; --amber:#ff9f6b;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Segoe UI",system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:
   radial-gradient(1400px 800px at 72% -8%, #142138 0%, transparent 60%),
   radial-gradient(1000px 700px at 20% 110%, #101a2e 0%, transparent 55%),
   var(--bg); color:var(--ink); font-family:var(--font); overflow:hidden}
.wrap{position:relative;width:100vw;height:100vh;overflow:hidden}
.hdr{position:absolute;top:0;left:0;right:0;z-index:6;display:flex;align-items:center;gap:14px;
  padding:16px 22px;pointer-events:none}
.hdr .logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--blue),var(--violet));
  box-shadow:0 6px 20px rgba(110,168,254,.4);position:relative;flex:none}
.hdr .logo::after{content:"";position:absolute;inset:7px;border-radius:4px;background:rgba(8,11,18,.6)}
.hdr .ttl{font-weight:700;letter-spacing:.2px}
.hdr .ttl small{display:block;font-weight:400;font-size:11px;color:var(--ink3)}
.chips{margin-left:auto;display:flex;gap:8px}
.chip{font-size:11px;font-weight:700;letter-spacing:.4px;padding:4px 10px;border-radius:999px;
  border:1px solid var(--line);color:var(--ink2);background:rgba(10,16,30,.6);backdrop-filter:blur(6px)}
.chip.ro{color:var(--cyan);border-color:rgba(79,209,197,.4)}
.chip.safe{color:var(--gold);border-color:rgba(242,193,78,.4)}
.chip.disp{color:var(--amber);border-color:rgba(255,159,107,.4)}

.scene{position:absolute;inset:0}
.floor{position:absolute;left:0;top:0;width:100%;height:100%}
.grid-bg{position:absolute;inset:0;opacity:.16;
  background-image:linear-gradient(rgba(110,168,254,.12) 1px,transparent 1px),
    linear-gradient(90deg,rgba(110,168,254,.12) 1px,transparent 1px);
  background-size:46px 46px; mask:radial-gradient(1200px 700px at 50% 45%,#000 30%,transparent 75%)}
svg.paths{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none}
.iso{position:absolute;z-index:3}
.iso .base,.iso .top{position:absolute;left:0;top:0;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%)}
.iso .base{background:linear-gradient(180deg,#0b1striped,#070b13);filter:brightness(.5)}
.room{position:absolute;z-index:4;pointer-events:auto}
.room .plate{position:absolute;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);
  border:1px solid rgba(120,150,200,.25);
  box-shadow:0 30px 60px rgba(0,0,0,.5)}
.room .wall{position:absolute;clip-path:polygon(0 50%,50% 100%,50% 100%,0 50%);}
.room .glow{position:absolute;border-radius:50%;filter:blur(26px);opacity:.5}
.room.quiet .plate{opacity:.5}
.room.quiet .label{opacity:.55}
.label{position:absolute;z-index:5;transform:translate(-50%,-100%);
  display:flex;align-items:center;gap:8px;white-space:nowrap;
  background:rgba(9,14,26,.78);border:1px solid var(--line);border-radius:10px;
  padding:5px 10px;backdrop-filter:blur(8px);box-shadow:0 8px 22px rgba(0,0,0,.4)}
.label .dot{width:8px;height:8px;border-radius:50%}
.label .nm{font-size:12px;font-weight:650}
.label .ct{font-size:11px;color:var(--ink3);background:rgba(0,0,0,.3);border-radius:6px;padding:0 6px}
.tokens{position:absolute;z-index:5;transform:translate(-50%,-50%)}
.tok{position:absolute;width:14px;height:14px;border-radius:50%;transform:translate(-50%,-50%);
  box-shadow:0 0 0 2px rgba(8,11,18,.7), 0 0 12px 1px currentColor; animation:rise .5s ease both}
.tok.big{width:18px;height:18px}
.tok.more{width:auto;height:auto;border-radius:8px;padding:1px 6px;font-size:10px;font-weight:800;
  color:#0a0d14;background:var(--ink2);box-shadow:none}
@keyframes rise{from{opacity:0;transform:translate(-50%,-30%) scale(.5)}to{opacity:1;transform:translate(-50%,-50%) scale(1)}}
@keyframes flow{to{stroke-dashoffset:-40}}
.pulse{animation:pl 2.2s ease-in-out infinite}
@keyframes pl{0%,100%{box-shadow:0 0 0 2px rgba(8,11,18,.7),0 0 10px 1px currentColor}
  50%{box-shadow:0 0 0 2px rgba(8,11,18,.7),0 0 22px 5px currentColor}}
body.rm .tok,body.rm path{animation:none!important}

/* contextual panel (desktop/wide) */
.panel{position:absolute;right:22px;top:74px;z-index:6;width:300px;
  background:linear-gradient(180deg,rgba(18,24,40,.92),rgba(10,14,26,.92));
  border:1px solid var(--line);border-radius:16px;padding:16px;backdrop-filter:blur(10px);
  box-shadow:0 20px 60px rgba(0,0,0,.5)}
.panel h3{font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:var(--ink3);margin-bottom:10px}
.panel .kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.panel .k{background:rgba(8,12,22,.6);border:1px solid var(--line);border-radius:10px;padding:9px 10px}
.panel .k .v{font-size:20px;font-weight:750}
.panel .k .l{font-size:11px;color:var(--ink3)}
.panel .row{display:flex;gap:9px;align-items:flex-start;font-size:12px;color:var(--ink2);padding:7px 0;border-top:1px solid var(--line)}
.panel .row .d{width:8px;height:8px;border-radius:50%;background:var(--gold);margin-top:4px;flex:none}
.legend{font-size:11px;color:var(--ink3);margin-top:12px;line-height:1.5}
.foot{position:absolute;left:22px;bottom:16px;z-index:6;font-size:11px;color:var(--ink3);max-width:60vw}

/* mobile: mini-map + owner home */
.mhome{display:none}
.mobile .panel,.mobile .foot{display:none}
.mobile .hdr{padding:12px 16px}
.mobile .scene{top:56px;bottom:auto;height:44vh}
.mobile .mhome{display:block;position:absolute;left:0;right:0;bottom:0;z-index:6;height:56vh;overflow:auto;
  background:linear-gradient(180deg,rgba(10,14,26,.4),rgba(8,11,18,.98) 22%);padding:16px 14px calc(16px + env(safe-area-inset-bottom));
  border-top:1px solid var(--line)}
.mobile .mhome h2{font-size:16px;margin-bottom:2px}
.mobile .mhome .sub{font-size:12px;color:var(--ink3);margin-bottom:14px}
.mhome .strip{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px}
.mhome .s{background:rgba(18,24,40,.7);border:1px solid var(--line);border-radius:12px;padding:10px 6px;text-align:center}
.mhome .s .v{font-size:20px;font-weight:750}
.mhome .s .l{font-size:10px;color:var(--ink3);margin-top:2px}
.mhome .card{background:linear-gradient(180deg,rgba(20,26,43,.9),rgba(12,16,28,.9));border:1px solid var(--line);
  border-radius:14px;padding:12px 13px;margin-bottom:10px;display:flex;gap:10px;align-items:flex-start}
.mhome .card .pin{width:9px;height:9px;border-radius:50%;background:var(--gold);margin-top:5px;flex:none}
.mhome .card .t{font-size:13px;font-weight:600;line-height:1.35}
.mhome .card .m{font-size:11px;color:var(--ink3);margin-top:3px}
.mnav{position:fixed;left:0;right:0;bottom:0;z-index:7;display:flex;justify-content:space-around;
  background:rgba(9,13,22,.96);border-top:1px solid var(--line);padding:6px 4px calc(6px + env(safe-area-inset-bottom))}
.mnav b{font-size:10px;color:var(--ink3);display:flex;flex-direction:column;align-items:center;gap:3px;font-weight:500}
.mnav b.on{color:var(--blue)} .mnav b i{font-style:normal;font-size:16px}
.mobile .mnav{display:flex}.mnav{display:none}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div class="logo"></div>
    <div class="ttl">Studio OS<small class="t-sub"></small></div>
    <div class="chips">
      <span class="chip ro t-ro"></span>
      <span class="chip safe t-safe"></span>
      <span class="chip disp t-disp"></span>
    </div>
  </div>
  <div class="scene">
    <div class="grid-bg"></div>
    <svg class="paths"></svg>
    <div class="floor"></div>
  </div>
  <div class="panel">
    <h3 class="t-planhead"></h3>
    <div class="kpis"></div>
    <div class="waiting"></div>
    <div class="legend t-legend"></div>
  </div>
  <div class="foot t-foot"></div>

  <div class="mhome"></div>
  <div class="mnav"></div>
</div>
<script>
const MODEL = __MODEL__;
const LANG = "__LANG__";
const VARIANT = "__VARIANT__";
const RU = LANG==='ru';
const L = {
  sub: RU?'Живой план студии':'Live studio floorplan',
  ro: 'READ ONLY', safe:'SAFE MODE', disp: RU?'ДИСПЕТЧ. ЗАКРЫТА':'DISPATCH CLOSED',
  planhead: RU?'Студия — состояние':'Studio — state',
  legend: RU?'Каждый огонёк — реальная задача или решение из леджера. Тусклая комната — тихая (работы нет). Ничего не выдумано.'
             :'Each light is a real task or decision from the ledger. A dim room is quiet (no work). Nothing is fabricated.',
  foot: RU?'Прототип визуального направления · данные из read_model.json · не финальный рендер'
          :'Visual-direction prototype · data from read_model.json · not the final renderer',
  owner:RU?'Что требует тебя':'What needs you', running:RU?'В работе':'Running',
  blocked:RU?'Заблок.':'Blocked', failed:RU?'Ошибки':'Failed', done:RU?'Готово':'Done',
  home:RU?'Owner Home':'Owner Home', homesub:RU?'Открой Студию, чтобы увидеть план':'Open Studio to see the floor',
};
const ROOMS = [
 {key:'intake', ru:'Приём', en:'Intake', col:0,row:0, accent:'#6ea8fe'},
 {key:'research', ru:'Research Lab', en:'Research Lab', col:1,row:0, accent:'#4fd1c5'},
 {key:'product', ru:'Product Studio', en:'Product Studio', col:2,row:0, accent:'#8f7bff'},
 {key:'engineering', ru:'Инженерия', en:'Engineering', col:0,row:1, accent:'#6ea8fe'},
 {key:'review', ru:'Проверка / QA', en:'Review / QA', col:1,row:1, accent:'#4fd1c5'},
 {key:'sandbox', ru:'Песочница', en:'Sandbox', col:2,row:1, accent:'#5ad1a0'},
 {key:'reliability', ru:'Надёжность', en:'Reliability', col:0,row:2, accent:'#ff6b6b'},
 {key:'memory', ru:'Память', en:'Memory', col:1,row:2, accent:'#3ecf8e'},
 {key:'owner', ru:'Командный центр', en:'Owner Command', col:2,row:2, accent:'#f2c14e', big:true},
];
const STATE_COLOR = {running:'#6ea8fe',review:'#4fd1c5',owner_wait:'#f2c14e',blocked:'#ff9f6b',
  failed:'#ff6b6b',done:'#3ecf8e',planned:'#9aa7c2',queued:'#9aa7c2',decision:'#f2c14e'};
const FLOW = [['intake','research'],['research','product'],['product','engineering'],
  ['intake','engineering'],['engineering','review'],['review','owner'],['review','memory'],
  ['engineering','reliability']];

// bind real tasks to rooms
function bind(){
  const byRoom={}; ROOMS.forEach(r=>byRoom[r.key]=[]);
  (MODEL.work||[]).forEach(w=>{
    let z=w.zone; if(z==='blocked') z='reliability';
    if(!byRoom[z]) z='intake';
    byRoom[z].push({state:w.ui_state,title:w.title});
  });
  (MODEL.decisions&&MODEL.decisions.items||[]).forEach(d=>byRoom.owner.push({state:'decision',title:d.title}));
  return byRoom;
}

const cfg = VARIANT==='wide' ? {tw:360,th:180,ox:0.5,oy:360,scale:1}
          : VARIANT==='mobile' ? {tw:118,th:59,ox:0.5,oy:74,scale:1}
          : {tw:250,th:125,ox:0.5,oy:300,scale:1};

function project(col,row,W){
  const ox = W*cfg.ox;
  return {x: ox + (col-row)*(cfg.tw/2), y: cfg.oy + (col+row)*(cfg.th/2)};
}

function render(){
  document.querySelector('.t-sub').textContent=L.sub;
  document.querySelector('.t-ro').textContent=L.ro;
  document.querySelector('.t-safe').textContent=L.safe;
  const disp = MODEL.overview && MODEL.overview.dispatch_open;
  document.querySelector('.t-disp').textContent=L.disp;
  document.querySelector('.t-disp').style.display = disp?'none':'';
  document.querySelector('.t-planhead').textContent=L.planhead;
  document.querySelector('.t-legend').textContent=L.legend;
  document.querySelector('.t-foot').textContent=L.foot;
  if(VARIANT==='mobile') document.body.classList.add('mobile');

  const W = window.innerWidth;
  const byRoom = bind();
  const floor=document.querySelector('.floor');
  const svg=document.querySelector('.paths');
  const centers={};

  // paths first (under rooms)
  ROOMS.forEach(r=>{centers[r.key]=project(r.col,r.row,W);});
  let pd='';
  FLOW.forEach(([a,b])=>{const p1=centers[a],p2=centers[b];
    pd+=`<path d="M ${p1.x} ${p1.y} L ${p2.x} ${p2.y}" stroke="rgba(110,168,254,.28)" stroke-width="2" fill="none" stroke-dasharray="5 7" style="animation:flow 3.5s linear infinite"/>`;});
  svg.innerHTML=pd;

  ROOMS.forEach(r=>{
    const c=centers[r.key]; const tw=cfg.tw*(r.big?1.14:1), th=cfg.th*(r.big?1.14:1);
    const items=byRoom[r.key]||[]; const quiet=items.length===0;
    // room plate (diamond) + wall thickness
    const room=document.createElement('div'); room.className='room'+(quiet?' quiet':'');
    room.style.left=(c.x-tw/2)+'px'; room.style.top=(c.y-th/2)+'px'; room.style.width=tw+'px'; room.style.height=th+'px';
    const wallH=r.big?20:15;
    room.innerHTML=
      `<div class="plate" style="left:0;top:${wallH}px;width:${tw}px;height:${th}px;`
      +`background:linear-gradient(160deg, rgba(${hex(r.accent)},.20), rgba(12,17,30,.9) 60%);"></div>`
      +`<div class="plate" style="left:0;top:0;width:${tw}px;height:${th}px;`
      +`background:linear-gradient(160deg, rgba(${hex(r.accent)},.32), rgba(16,22,38,.92) 62%);`
      +`border:1px solid rgba(${hex(r.accent)},.5);"></div>`
      +`<div class="glow" style="left:${tw*0.2}px;top:${th*0.1}px;width:${tw*0.6}px;height:${th*0.7}px;background:${r.accent}"></div>`;
    floor.appendChild(room);

    // label
    const lab=document.createElement('div'); lab.className='label';
    lab.style.left=c.x+'px'; lab.style.top=(c.y-th/2-2)+'px';
    lab.innerHTML=`<span class="dot" style="background:${r.accent}"></span>`
      +`<span class="nm">${RU?r.ru:r.en}</span><span class="ct">${items.length}</span>`;
    floor.appendChild(lab);

    // tokens: cluster inside diamond
    const cap=8; const shown=items.slice(0,cap);
    const tc=document.createElement('div'); tc.className='tokens'; tc.style.left=c.x+'px'; tc.style.top=(c.y+th*0.08)+'px';
    shown.forEach((it,i)=>{
      const ang=(i/Math.max(1,shown.length))*Math.PI*2; const rad=Math.min(tw,th)*0.22;
      const dx=Math.cos(ang)*rad*1.6, dy=Math.sin(ang)*rad*0.8;
      const col=STATE_COLOR[it.state]||'#9aa7c2';
      const t=document.createElement('div'); t.className='tok'+(r.big?' big':'')+((it.state==='running')?' pulse':'');
      t.style.left=dx+'px'; t.style.top=dy+'px'; t.style.color=col; t.style.background=col;
      t.style.animationDelay=(i*0.05)+'s';
      tc.appendChild(t);
    });
    if(items.length>cap){const m=document.createElement('div');m.className='tok more';m.style.left='0px';m.style.top='0px';m.textContent='+'+(items.length-cap);tc.appendChild(m);}
    floor.appendChild(tc);
  });

  // panel kpis
  const ov=MODEL.overview||{}; const c=ov.counts||{};
  const kp=document.querySelector('.panel .kpis');
  [[L.owner,ov.owner_waiting||0,'#f2c14e'],[L.running,c.running||0,'#6ea8fe'],
   [L.failed,c.failed||0,'#ff6b6b'],[L.done,c.done||0,'#3ecf8e']].forEach(([l,v,col])=>{
    const d=document.createElement('div');d.className='k';d.innerHTML=`<div class="v" style="color:${col}">${v}</div><div class="l">${l}</div>`;kp.appendChild(d);});
  const wq=document.querySelector('.panel .waiting');
  (MODEL.decisions&&MODEL.decisions.items||[]).slice(0,3).forEach(d=>{
    const r=document.createElement('div');r.className='row';r.innerHTML=`<span class="d"></span><span>${esc(d.title)}</span>`;wq.appendChild(r);});

  // mobile owner home
  if(VARIANT==='mobile'){
    const mh=document.querySelector('.mhome');
    mh.innerHTML=`<h2>${L.home}</h2><div class="sub">${MODEL.generated_at?new Date(MODEL.generated_at).toLocaleString(RU?'ru-RU':'en-US'):''}</div>`;
    const strip=document.createElement('div');strip.className='strip';
    [[L.owner,ov.owner_waiting||0,'#f2c14e'],[L.running,c.running||0,'#6ea8fe'],[L.blocked,c.blocked||0,'#ff9f6b'],[L.failed,c.failed||0,'#ff6b6b'],[L.done,c.done||0,'#3ecf8e']]
      .forEach(([l,v,col])=>{const s=document.createElement('div');s.className='s';s.innerHTML=`<div class="v" style="color:${col}">${v}</div><div class="l">${l}</div>`;strip.appendChild(s);});
    mh.appendChild(strip);
    (MODEL.decisions&&MODEL.decisions.items||[]).forEach(d=>{
      const cd=document.createElement('div');cd.className='card';cd.innerHTML=`<span class="pin"></span><div><div class="t">${esc(d.title)}</div><div class="m">${RU?'Ждёт вашего решения':'Waiting for your decision'}</div></div>`;mh.appendChild(cd);});
    const nav=document.querySelector('.mnav');
    const items=RU?['Обзор','Работа','Решения','Роли','Студия']:['Overview','Work','Decisions','Roles','Studio'];
    const icons=['◎','▤','◆','◇','◊'];
    nav.innerHTML=items.map((t,i)=>`<b class="${i===4?'on':''}"><i>${icons[i]}</i>${t}</b>`).join('');
  }
}
function hex(h){h=h.replace('#','');return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)].join(',');}
function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', choices=['desktop', 'wide', 'mobile'], default='desktop')
    ap.add_argument('--lang', default='ru')
    ap.add_argument('--out', default=None)
    ns = ap.parse_args()
    model = json.loads((HERE / 'read_model.json').read_text(encoding='utf-8'))
    html = (TEMPLATE
            .replace('__MODEL__', json.dumps(model, ensure_ascii=False))
            .replace('__LANG__', ns.lang)
            .replace('__VARIANT__', ns.variant))
    out = HERE / (ns.out or f'studio_proto_{ns.variant}.html')
    out.write_text(html, encoding='utf-8')
    print(f'wrote {out} ({len(html)} bytes)')


if __name__ == '__main__':
    main()
