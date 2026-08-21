# -*- coding: utf-8 -*-
"""
사내 대시보드 생성
data/clippings/*.json 을 모두 읽어, 데이터를 통째로 품은 자체완결형 dashboard.html 생성.
- 서버 불필요: 파일을 그대로 열면 동작(사내 공유드라이브 등)
- 기능: 날짜 아카이브 + 키워드 검색 + 카테고리 필터
"""

import glob
import json
import os
from datetime import datetime

import config

CLIP_DIR = os.path.join("data", "clippings")
# GitHub Pages 공개용: docs/index.html 로 생성 (루트 URL로 바로 열림)
# 원본 JSON(data/)은 공개하지 않고 자체완결형 HTML만 노출
PUBLISH_DIR = os.environ.get("PUBLISH_DIR", "docs")
OUT = os.path.join(PUBLISH_DIR, "index.html")


def _load_all() -> list:
    days = []
    for path in sorted(glob.glob(os.path.join(CLIP_DIR, "*.json")), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                days.append(json.load(f))
        except Exception as e:
            print(f"  [대시보드] 읽기 실패 {path}: {e}")
    return days


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>아이즈비전 뉴스 클리핑 대시보드</title>
<style>
  :root{
    --navy:#0C447C; --navy2:#185FA5; --accent:#185FA5;
    --bg:#eef0f3; --card:#fff; --border:#e4e7eb;
    --t1:#1a1d21; --t2:#4b5158; --t3:#8b9199;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--t1);
    font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
  header{background:var(--navy);color:#fff;padding:16px 24px;position:sticky;top:0;z-index:10;}
  header .ttl{font-size:19px;font-weight:600;letter-spacing:-0.3px;}
  header .sub{font-size:12px;color:#85B7EB;margin-top:3px;}
  .wrap{display:flex;max-width:1200px;margin:0 auto;gap:16px;padding:16px;}
  .side{width:220px;flex:0 0 220px;}
  .side .box{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:12px;}
  .side h3{font-size:12px;color:var(--t3);margin:0 0 8px;font-weight:600;}
  .daybtn{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;
    background:none;border:none;padding:7px 8px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--t1);
    font-family:inherit;}
  .daybtn:hover{background:#f2f5f9;}
  .daybtn.on{background:var(--navy);color:#fff;}
  .daybtn .cnt{font-size:11px;color:var(--t3);}
  .daybtn.on .cnt{color:#cfe0f2;}
  .main{flex:1;min-width:0;}
  .search{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:12px;}
  .search input{width:100%;border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-size:14px;
    font-family:inherit;outline:none;}
  .search input:focus{border-color:var(--accent);}
  .chips{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;}
  .chip{font-size:12px;padding:5px 12px;border-radius:16px;border:1px solid var(--border);background:#fff;
    cursor:pointer;color:var(--t2);font-family:inherit;}
  .chip.on{background:var(--navy2);color:#fff;border-color:var(--navy2);}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:14px;}
  .card .hd{background:var(--navy);color:#fff;padding:14px 18px;}
  .card .hd .d{font-size:16px;font-weight:600;}
  .card .hd .m{font-size:12px;color:#85B7EB;margin-top:2px;}
  .top5{padding:14px 18px;border-bottom:8px solid var(--bg);}
  .top5 .lb{font-size:12px;font-weight:600;color:var(--accent);margin-bottom:8px;}
  .top5 .row{font-size:14px;line-height:1.6;}
  .top5 .n{color:var(--accent);font-weight:600;margin-right:6px;}
  .top5 .tag{font-size:11px;color:var(--t3);}
  .sec{padding:14px 18px;border-top:1px solid var(--border);}
  .sec .sh{font-size:14px;font-weight:600;color:var(--navy);margin-bottom:8px;}
  .sec .subh{font-size:13px;font-weight:600;color:var(--t1);margin:12px 0 6px;}
  .sec .dg{background:#f6f7f9;border-left:3px solid var(--accent);border-radius:6px;padding:9px 11px;
    font-size:12.5px;color:var(--t2);line-height:1.6;margin-bottom:10px;}
  .art{padding:8px 0;border-bottom:1px solid #f0f2f4;}
  .art:last-child{border-bottom:none;}
  .art .at{font-size:14px;font-weight:600;color:var(--t1);line-height:1.5;}
  .art .as{font-size:13px;color:var(--t2);line-height:1.6;margin:3px 0;}
  .art .am{font-size:12px;color:var(--t3);}
  .art .am a{color:var(--accent);text-decoration:none;}
  .bdg{font-size:10px;font-weight:600;padding:1px 7px;border-radius:10px;margin-right:6px;}
  .bdg.자사{color:#26215C;background:#CECBF6;} .bdg.산업{color:#663806;background:#FAC775;}
  .empty{padding:40px;text-align:center;color:var(--t3);font-size:14px;}
  .hit{font-size:11px;color:var(--t3);margin-left:6px;}
  @media(max-width:820px){.wrap{flex-direction:column}.side{width:auto;flex:auto;display:flex;gap:12px;overflow-x:auto}}
</style></head>
<body>
<header>
  <div class="ttl">아이즈비전 뉴스 클리핑 대시보드</div>
  <div class="sub" id="hsub"></div>
</header>
<div class="wrap">
  <div class="side">
    <div class="box"><h3>날짜</h3><div id="days"></div></div>
  </div>
  <div class="main">
    <div class="search">
      <input id="q" placeholder="키워드 검색 (제목·요약·언론사) — 전체 날짜 대상">
      <div class="chips" id="chips"></div>
    </div>
    <div id="view"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const CATS = [["all","전체"],["industry","산업"],["own","자사"],["competitor","경쟁사"],["group","그룹"]];
let curDay = DATA.length ? DATA[0].date : null;
let curCat = "all";
let query = "";

const esc = s => (s||"").replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function renderDays(){
  document.getElementById("days").innerHTML = DATA.map(d=>
    `<button class="daybtn ${d.date===curDay&&!query?'on':''}" onclick="pickDay('${d.date}')">
      <span>${d.date}</span><span class="cnt">${d.total}건</span></button>`).join("") || '<div class="hit">데이터 없음</div>';
}
function renderChips(){
  document.getElementById("chips").innerHTML = CATS.map(([id,nm])=>
    `<button class="chip ${curCat===id?'on':''}" onclick="pickCat('${id}')">${nm}</button>`).join("");
}
function pickDay(d){ curDay=d; query=""; document.getElementById("q").value=""; render(); }
function pickCat(c){ curCat=c; render(); }

function artHTML(a){
  const bdg = a.badge ? `<span class="bdg ${a.badge}">${a.badge}</span>` : "";
  const link = a.link ? `<a href="${esc(a.link)}" target="_blank">원문보기 ↗</a>` : "";
  return `<div class="art"><div class="at">${bdg}${esc(a.title)}</div>
    <div class="as">${esc(a.summary)}</div>
    <div class="am">${esc(a.press)} · ${esc(a.date)} ${link?'· '+link:''}</div></div>`;
}

function renderDay(){
  const d = DATA.find(x=>x.date===curDay);
  if(!d){ document.getElementById("view").innerHTML='<div class="empty">선택한 날짜 데이터가 없습니다.</div>'; return; }
  let h = `<div class="card"><div class="hd"><div class="d">${d.date} 뉴스 클리핑</div>
    <div class="m">생성 ${esc(d.generated_at)} · 총 ${d.total}건</div></div>`;
  if(d.top5 && d.top5.length){
    h += `<div class="top5"><div class="lb">🔥 오늘의 핵심 Top 5</div>`;
    h += d.top5.map(t=>`<div class="row"><span class="n">${t.rank}</span>${
      t.link?`<a href="${esc(t.link)}" target="_blank" style="color:var(--t1);text-decoration:none">${esc(t.headline)}</a>`:esc(t.headline)
    } <span class="tag">[${esc(t.category)}]</span></div>`).join("");
    h += `</div>`;
  }
  d.sections.forEach(s=>{
    if(curCat!=="all" && s.id!==curCat) return;
    if(!s.articles.length) return;
    h += `<div class="sec"><div class="sh">${s.num} ${esc(s.title)} · ${s.articles.length}건</div>`;
    if(s.subgroups && s.subgroups.length){
      // 회사별 소그룹
      s.subgroups.forEach(sg=>{
        const list = s.articles.filter(a=>a.subgroup===sg.id);
        if(!list.length) return;
        h += `<div class="subh">${esc(sg.label)} <span class="hit">${list.length}건</span></div>`;
        const dg = (s.digest && typeof s.digest==="object") ? (s.digest[sg.id]||"") : "";
        if(dg) h += `<div class="dg">${esc(dg)}</div>`;
        h += list.map(artHTML).join("");
      });
    } else {
      if(s.digest && typeof s.digest==="string") h += `<div class="dg">${esc(s.digest)}</div>`;
      h += s.articles.map(artHTML).join("");
    }
    h += `</div>`;
  });
  h += `</div>`;
  document.getElementById("view").innerHTML = h;
}

function renderSearch(){
  const q = query.toLowerCase();
  let rows = [];
  DATA.forEach(d=>d.sections.forEach(s=>{
    if(curCat!=="all" && s.id!==curCat) return;
    s.articles.forEach(a=>{
      const hay = (a.title+" "+a.summary+" "+a.press).toLowerCase();
      if(hay.includes(q)) rows.push({d:d.date, s:s.title, a});
    });
  }));
  let h = `<div class="card"><div class="hd"><div class="d">검색 결과</div>
    <div class="m">"${esc(query)}" · ${rows.length}건</div></div><div class="sec">`;
  h += rows.length ? rows.map(r=>`<div class="art">
      <div class="at">${esc(r.a.title)} <span class="hit">${r.d} · ${esc(r.s)}</span></div>
      <div class="as">${esc(r.a.summary)}</div>
      <div class="am">${esc(r.a.press)} · ${esc(r.a.date)} ${r.a.link?'· <a href="'+esc(r.a.link)+'" target="_blank">원문보기 ↗</a>':''}</div>
    </div>`).join("") : '<div class="empty">일치하는 기사가 없습니다.</div>';
  h += `</div></div>`;
  document.getElementById("view").innerHTML = h;
}

function render(){
  renderDays(); renderChips();
  if(query.trim()) renderSearch(); else renderDay();
}
document.getElementById("q").addEventListener("input", e=>{ query=e.target.value; render(); });
document.getElementById("hsub").textContent =
  DATA.length ? `${DATA.length}일치 아카이브 · 최신 ${DATA[0].date}` : "데이터 없음";
render();
</script>
</body></html>"""


def build() -> str:
    days = _load_all()
    html = TEMPLATE.replace("__DATA__", json.dumps(days, ensure_ascii=False))
    os.makedirs(PUBLISH_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[대시보드] {OUT} 생성 ({len(days)}일치)")
    return OUT


if __name__ == "__main__":
    build()
