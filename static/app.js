const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const won = (n) => `${Math.round(n).toLocaleString("ko-KR")}원`;
const num = (n) => Math.round(n).toLocaleString("ko-KR");
const short = (n) => (n >= 10000 ? `${(n / 10000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, "")}만` : num(n));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = (id) => `<svg><use href="#${id}"/></svg>`;

// 카테고리 색·이모지는 서버(설정에서 사용자가 바꾸거나 추가한 것)에서 받는다. 받은 돈 줄에만 쓰는 '입금'은 고정
const CATS = { 기타: { c: "#cfc4e0", e: "📦" }, 입금: { c: "#ece4fb", e: "💜" } };
function applyCategories(info) {
  for (const k of Object.keys(CATS)) if (!["기타", "입금"].includes(k)) delete CATS[k];
  info.forEach((c) => { CATS[c.name] = { c: c.color, e: c.emoji }; });
}
const cat = (name) => CATS[name || "기타"] || CATS.기타;
const CONFIDENCE = { high: "확실해요", medium: "그럴듯해요", low: "단서가 부족해요" };
const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

const state = { meta: null, month: null, view: "home", prev: "home", reports: [], week: null, chart: null, home: null, autoReport: null };

async function api(path, opts = {}) {
  if (opts.json !== undefined) {
    opts = { ...opts, body: JSON.stringify(opts.json), headers: { "Content-Type": "application/json" } };
  }
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `요청 실패 (${res.status})`);
  return body;
}
const showError = (e) => alert(e.message || e);

const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const mondayOf = (d) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const md = (s) => `${Number(s.slice(5, 7))}.${Number(s.slice(8, 10))}`;

// ---------- 화면 이동 ----------
const loaders = {
  home: loadHome, txns: loadTransactions, day: loadDay, settle: loadSettlements, report: loadReport,
  upload: async () => {}, budget: loadBudgets, policy: loadPolicy,
};
// 탭바에 없는 화면: 뒤로 가기로 돌아갈 곳을 바꾸지 않는다
const SUB_VIEWS = ["upload", "budget", "settle", "policy"];

function go(name) {
  if (name !== state.view) state.prev = SUB_VIEWS.includes(state.view) ? state.prev : state.view;
  state.view = name;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  $$(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  window.scrollTo({ top: 0 });
  loaders[name]().catch(showError);
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-tab],[data-go],[data-back]");
  if (!t) return;
  if (t.dataset.back !== undefined) go(state.prev || "home");
  else go(t.dataset.tab || t.dataset.go);
});

function setMonth(value) {
  state.month = value;
  const [y, m] = value.split("-").map(Number);
  const current = value === state.meta.today.slice(0, 7);
  $$(".month-label").forEach((s) => (s.textContent = current ? "이번 달" : `${y}년 ${m}월`));
  // 아직 오지 않은 달은 볼 게 없으니 '다음 달'은 이번 달에서 멈춘다
  $$('[data-month-step="1"]').forEach((b) => b.classList.toggle("at-end", current));
}

// 이전·다음 달 버튼. 홈과 거래 화면이 같은 달을 보여준다
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-month-step]");
  if (!b) return;
  const [y, m] = state.month.split("-").map(Number);
  const d = new Date(y, m - 1 + Number(b.dataset.monthStep), 1);
  const next = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  if (next > state.meta.today.slice(0, 7)) return;
  setMonth(next);
  loaders[state.view]().catch(showError);
});

// ---------- 배지 ----------
async function refreshBadges() {
  const [s, review] = await Promise.all([api("/api/settlements"), api("/api/review")]);
  const set = (el, n) => { el.hidden = !n; el.textContent = n; };
  set($("#pending-badge"), s.pending.length);
  set($("#review-badge"), review.length);
  return { settlements: s, review };
}

// ---------- 홈 ----------
async function loadHome() {
  const [s, badges] = await Promise.all([api(`/api/summary?month=${state.month}`), refreshBadges()]);
  const isThisMonth = state.month === state.meta.today.slice(0, 7);
  const budgetTotal = Object.entries(s.budgets).filter(([c]) => c !== "제외").reduce((a, [, v]) => a + v, 0);
  const cats = Object.entries(s.by_category).filter(([, v]) => v > 0);

  renderPie($("#cat-cols"), cats, s.total, "이 달의 지출이 아직 없어요.");

  $("#total").textContent = num(s.total);
  const back = s.gross - s.total;
  $("#total-detail").innerHTML = (back > 0
    ? `토스 기준 ${won(s.gross)}에서<br><b>${won(back)}</b>을 돌려받았어요`
    : `토스 기준 ${won(s.gross)}`)
    + (budgetTotal ? `<br>한 달 예산 ${won(budgetTotal)} 중 <b>${Math.round((s.total / budgetTotal) * 100)}%</b> 썼어요` : "");
  $("#hero-foot").hidden = s.projected_total === s.total;
  $("#projected").textContent = `대기 중인 정산을 확정하면 ${won(s.projected_total)}`;

  const elapsed = isThisMonth ? new Date().getDate() : daysIn(state.month);
  $("#today").textContent = isThisMonth ? short(s.today) : "-";
  $("#avg").textContent = short(s.total / Math.max(1, elapsed));
  $("#income").textContent = short(s.income);
  $("#review-num").textContent = `${badges.review.length}건`;

  state.home = { s, badges };
  renderFeature(s, badges);
  renderPolicyCard();
  renderWeek(s, budgetTotal);
  renderTiles(s, cats);
  $("#top-list").innerHTML = s.top.length ? s.top.slice(0, 6).map((t) => row({
    category: t.category, title: t.description, meta: `${md(t.date)} · ${t.category}`,
    right: `${t.net !== t.amount ? `<span class="strike">${won(t.amount)}</span>` : ""}<div class="amt">${won(t.net)}</div>`,
  })).join("") : `<div class="empty">이 달의 지출이 없어요.</div>`;
}

const daysIn = (month) => { const [y, m] = month.split("-").map(Number); return new Date(y, m, 0).getDate(); };

// 카테고리를 옆으로 나란히, 큰 순서대로 세로 막대 (홈과 하루 화면이 같이 쓴다)
function renderCols(box, cats, total, emptyText) {
  const max = cats.length ? cats[0][1] : 0;
  box.style.gridTemplateColumns = `repeat(${Math.max(cats.length, 1)}, minmax(0, 1fr))`;
  box.setAttribute("aria-label", cats.map(([c, v]) => `${c} ${won(v)}`).join(", ") || "카테고리별 지출 없음");
  box.innerHTML = cats.length ? cats.map(([c, v]) => `<div>
      <div class="v">${short(v)}</div>
      <div class="bar" style="height:${Math.max(6, Math.round((v / max) * 110))}px;--c:${cat(c).c}"></div>
      <div class="n">${esc(c)}</div><div class="p">${Math.round((v / total) * 100)}%</div>
    </div>`).join("") : (emptyText ? `<div class="empty">${emptyText}</div>` : "");
}

// 카테고리별 실지출 원그래프 (가운데가 빈 도넛) + 옆에 범례
function renderPie(box, cats, total, emptyText) {
  box.className = "cat-pie";
  box.setAttribute("aria-label", cats.map(([c, v]) => `${c} ${won(v)}`).join(", ") || "카테고리별 지출 없음");
  if (!cats.length) { box.innerHTML = `<div class="empty">${emptyText}</div>`; return; }
  let at = 0;
  const stops = [], labels = [];
  cats.forEach(([c, v]) => {
    const from = at, pct = Math.round((v / total) * 100);
    at += (v / total) * 360;
    stops.push(`${cat(c).c} ${from}deg ${at}deg`);
    // 조각 가운데(도넛 띠 한가운데)에 비율을 적는다. 너무 얇은 조각은 범례로만 보여준다
    if (pct >= 4) {
      const rad = (((from + at) / 2) - 90) * Math.PI / 180;
      labels.push(`<span class="pct" style="left:${50 + 38 * Math.cos(rad)}%;top:${50 + 38 * Math.sin(rad)}%">${pct}%</span>`);
    }
  });
  box.innerHTML = `<div class="pie" style="background:conic-gradient(${stops.join(", ")})">${labels.join("")}<div class="hole"><b>${cats.length}</b><span>카테고리</span></div></div>
    <ul class="legend">${cats.map(([c, v]) => `<li><i style="--c:${cat(c).c}"></i><span class="n">${cat(c).e} ${esc(c)}</span>
      <span class="v">${short(v)}</span><span class="p">${Math.round((v / total) * 100)}%</span></li>`).join("")}</ul>`;
}

// ---------- 지난 주 보고서 자동 작성 ----------
// 본 보고서는 브라우저에 기억해 두고 홈 카드를 다시 띄우지 않는다 (저장이 막힌 환경이면 매번 보일 뿐)
const seenKey = (week) => `seen-report-${week}`;
function reportSeen(week) { try { return localStorage.getItem(seenKey(week)) === "1"; } catch { return false; } }
function markReportSeen(week) { try { localStorage.setItem(seenKey(week), "1"); } catch { /* 무시 */ } }

async function autoReport() {
  try {
    state.autoReport = await api("/api/reports/auto", { method: "POST" });
  } catch {
    return;
  }
  if (state.view === "home" && state.home) renderFeature(state.home.s, state.home.badges);
}

function unseenReport() {
  const r = state.autoReport;
  return r && ["created", "exists"].includes(r.status) && !reportSeen(r.week_start) ? r.week_start : null;
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-open-report]");
  if (!b) return;
  state.week = b.dataset.openReport;
  markReportSeen(state.week);
  go("report");
});

function renderFeature(s, { settlements, review }) {
  let html;
  const reportWeek = unseenReport();
  if (reportWeek) {
    const end = isoDate(addDays(parseDate(reportWeek), 6));
    html = `<div class="feature calm"><p class="kicker">주간 보고서 · ${md(reportWeek)} – ${md(end)}</p>
      <h3>지난 주 보고서가 나왔어요</h3>
      <p>예산과 그 전 주를 비교해서 줄일 수 있었던 곳을 AI가 정리했어요.</p>
      <button class="btn btn-ink" data-open-report="${reportWeek}">보고서 보기 ${svg("i-arrow")}</button></div>`;
  } else if (!s.gross && !s.income) {
    html = `<div class="feature calm"><p class="kicker">처음이라면</p><h3>토스 거래내역서를 올려 볼까요</h3>
      <p>PDF를 올리면 AI가 카테고리를 나누고 친구들의 정산을 찾아요.</p>
      <button class="btn btn-ink" data-go="upload">거래내역 올리기 ${svg("i-arrow")}</button></div>`;
  } else if (settlements.pending.length) {
    const sum = settlements.pending.reduce((a, p) => a + p.incoming.amount, 0);
    html = `<div class="feature"><p class="kicker">정산 확인</p><h3>친구들이 보낸 ${won(sum)}, 어디에 쓴 돈일까요</h3>
      <p>AI가 ${settlements.pending.length}건을 결제에 연결해 봤어요. 맞는지만 눌러 주세요.</p>
      <button class="btn btn-ink" data-go="settle">정산 확인하기 ${svg("i-arrow")}</button></div>`;
  } else if (review.length) {
    html = `<div class="feature"><p class="kicker">분류 확인</p><h3>용도를 정할 거래가 ${review.length}건 남았어요</h3>
      <p>친구 송금과 페이 결제는 직접 골라 줘야 정확해져요.</p>
      <button class="btn btn-ink" data-go="txns">분류하러 가기 ${svg("i-arrow")}</button></div>`;
  } else {
    html = `<div class="feature calm"><p class="kicker">주간 보고서</p><h3>이번 주, 어디서 줄일 수 있었을까요</h3>
      <p>예산과 지난 주를 비교해서 AI가 짚어 줘요.</p>
      <button class="btn btn-ink" data-go="report">보고서 보기 ${svg("i-arrow")}</button></div>`;
  }
  $("#feature").innerHTML = html;
}

function renderWeek(s, budgetTotal) {
  const today = state.meta.today;
  const isThisMonth = state.month === today.slice(0, 7);
  const anchor = isThisMonth ? parseDate(today) : parseDate(`${state.month}-${String(daysIn(state.month)).padStart(2, "0")}`);
  const start = mondayOf(anchor);
  const days = WEEKDAYS.map((w, i) => {
    const iso = isoDate(addDays(start, i));
    return { w, iso, v: s.daily[iso], future: iso > today };
  });
  const max = Math.max(1, ...days.map((d) => d.v || 0));
  const dailyBudget = budgetTotal / daysIn(state.month);
  $("#week-range").textContent = `${md(days[0].iso)} – ${md(days[6].iso)}`;
  $("#week").innerHTML = days.map((d) => {
    const ok = dailyBudget && d.v !== undefined && !d.future && d.v <= dailyBudget;
    const cls = d.v === undefined ? "out" : d.iso === today ? "today" : d.v ? "" : "zero";
    return `<div class="${d.future ? "" : "tap"}" ${d.future ? "" : `data-open-day="${d.iso}" role="button" tabindex="0" aria-label="${md(d.iso)} 하루 보기"`}><div class="d">${d.w}</div>
      <div class="dot ${ok ? "ok" : ""}">${ok ? svg("i-check") : ""}</div>
      <div class="bar-wrap"><div class="bar ${cls}" style="height:${d.v ? Math.max(8, (d.v / max) * 92) : 6}px" title="${won(d.v || 0)}"></div></div>
      <div class="amt">${d.v ? short(d.v) : "·"}</div></div>`;
  }).join("");
  const spent = days.filter((d) => d.v);
  const top = spent.sort((a, b) => b.v - a.v)[0];
  const okDays = days.filter((d) => dailyBudget && d.v !== undefined && !d.future && d.v <= dailyBudget).length;
  $("#week-note").textContent = dailyBudget
    ? `하루 예산 ${won(dailyBudget)} 안에서 쓴 날이 ${okDays}일이에요.`
    : top ? `가장 많이 쓴 날은 ${top.w}요일, ${won(top.v)}이에요. 예산을 정하면 날마다 체크해 줘요.` : "이번 주는 아직 지출이 없어요.";
}

function renderTiles(s, cats) {
  $("#cat-aside").textContent = cats.length ? `${cats.length}개` : "";
  $("#tiles").innerHTML = cats.length ? cats.map(([c, v]) => {
    const b = s.budgets[c];
    const budget = b ? `<div class="budget ${v > b ? "over" : ""}">${v > b ? `예산보다 ${short(v - b)} 더` : `예산 ${short(b)} 중 ${Math.round((v / b) * 100)}%`}</div>` : "";
    return `<div class="tile" style="--c:${cat(c).c}"><div class="em">${cat(c).e}</div>
      <div class="name">${esc(c)}</div><div class="share">${Math.round((v / s.total) * 100)}%</div>
      <div class="amt">${won(v)}</div>${budget}</div>`;
  }).join("") : `<div class="empty" style="padding:0 4px">카테고리별 지출이 여기에 모여요.</div>`;
}

// ---------- 하루 ----------
function dayLabel(iso) {
  const today = state.meta.today;
  if (iso === today) return "오늘";
  if (iso === isoDate(addDays(parseDate(today), -1))) return "어제";
  return `${Number(iso.slice(5, 7))}월 ${Number(iso.slice(8, 10))}일 (${WEEKDAYS[(parseDate(iso).getDay() + 6) % 7]})`;
}

async function loadDay() {
  state.day ||= state.meta.today;
  const iso = state.day, d = await api(`/api/day?date=${iso}`);
  const label = dayLabel(iso);
  $(".day-label").textContent = label;
  $('[data-day-step="1"]').classList.toggle("at-end", iso >= state.meta.today);
  $("#day-title").textContent = label.length <= 2 ? `${label} 쓴 돈` : "이날 쓴 돈";
  $("#day-total").textContent = num(d.total);

  const back = d.gross - d.total;
  const lines = [];
  if (back > 0) lines.push(`결제 ${won(d.gross)} 중 <b>${won(back)}</b>을 돌려받았어요`);
  if (d.daily_budget) {
    const diff = d.daily_budget - d.total;
    lines.push(`하루 예산 ${won(d.daily_budget)}보다 <b>${won(Math.abs(diff))}</b> ${diff >= 0 ? "적게" : "많이"} 썼어요`);
  }
  if (d.projected_total !== d.total) lines.push(`대기 중인 정산을 확정하면 ${won(d.projected_total)}`);
  $("#day-detail").innerHTML = lines.join("<br>");

  const cats = Object.entries(d.by_category).filter(([, v]) => v > 0);
  renderCols($("#day-cols"), cats, d.total, "");
  const empty = $("#day-empty");
  const nothing = !d.payments.length && !d.incomings.length;
  empty.hidden = !nothing;
  if (nothing) {
    empty.innerHTML = d.latest && d.latest < iso
      ? `이날 거래가 아직 없어요. 마지막 기록인 <button data-open-day="${d.latest}">${dayLabel(d.latest)}</button>을 볼까요?`
      : "이날은 쓴 돈이 없어요.";
  }

  $("#day-count").textContent = d.payments.length ? `${d.payments.length}건` : "";
  $("#day-payments").innerHTML = d.payments.length ? d.payments.map((t) => row({
    category: t.category, title: t.description,
    meta: `${t.occurred_at.slice(11, 16)} · ${esc(t.category || "기타")}${t.needs_review ? " · 확인 필요" : ""}`,
    right: `${t.net !== t.amount ? `<span class="strike">${won(t.amount)}</span>` : ""}`
      + `<div class="amt ${t.category === "제외" ? "excluded" : ""}">${won(t.net)}</div>`,
  })).join("") : `<div class="empty">결제가 없어요.</div>`;

  $("#day-in-card").hidden = !d.incomings.length;
  $("#day-incomings").innerHTML = d.incomings.map((t) => row({
    category: "입금", title: t.description,
    meta: `${t.occurred_at.slice(11, 16)}${t.settled ? " · 정산·취소로 연결됨" : ""}`,
    right: `<div class="amt in">+${won(t.amount)}</div>`,
  })).join("");
}

function openDay(iso) {
  state.day = iso;
  if (state.view === "day") loadDay().catch(showError);
  else go("day");
}

document.addEventListener("click", (e) => {
  const open = e.target.closest("[data-open-day]");
  if (open) return openDay(open.dataset.openDay);
  const step = e.target.closest("[data-day-step]");
  if (!step) return;
  const next = isoDate(addDays(parseDate(state.day), Number(step.dataset.dayStep)));
  if (next <= state.meta.today) openDay(next);
});
document.addEventListener("keydown", (e) => {
  const open = e.target.closest?.("[data-open-day]");
  if (open && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDay(open.dataset.openDay); }
});

// ---------- 하루 요약 알림 ----------
// 설정은 이 브라우저에만 저장한다. 앱 창이 열려 있을 때 정한 시간이 지나면 하루에 한 번 알림을 띄운다.
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* 무시 */ } },
};
const notifyOn = () => store.get("notify-on", "0") === "1" && "Notification" in window && Notification.permission === "granted";

function renderNotifySettings() {
  $("#notify-time").value = store.get("notify-time", "22:00");
  const supported = "Notification" in window;
  $("#notify-toggle").textContent = notifyOn() ? "끄기" : "켜기";
  $("#notify-status").textContent = !supported ? "이 브라우저는 알림을 지원하지 않아요."
    : Notification.permission === "denied" ? "브라우저에서 알림이 막혀 있어요. 주소창 왼쪽 자물쇠 → 알림 → 허용으로 바꿔 주세요."
    : notifyOn() ? `매일 ${$("#notify-time").value}에 그날 쓴 돈을 알려줘요.` : "꺼져 있어요.";
}

$("#notify-time").addEventListener("change", (e) => { store.set("notify-time", e.target.value); renderNotifySettings(); });
$("#notify-toggle").addEventListener("click", async () => {
  if (!("Notification" in window)) return renderNotifySettings();
  if (notifyOn()) { store.set("notify-on", "0"); return renderNotifySettings(); }
  const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  store.set("notify-on", permission === "granted" ? "1" : "0");
  renderNotifySettings();
});

async function checkDailyNotify() {
  if (!notifyOn()) return;
  const now = new Date(), today = isoDate(now);
  const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  if (hhmm < store.get("notify-time", "22:00") || store.get("notified-on", "") === today) return;
  store.set("notified-on", today);
  try {
    const d = await api(`/api/day?date=${today}`);
    const top = Object.entries(d.by_category).filter(([, v]) => v > 0).slice(0, 3)
      .map(([c, v]) => `${c} ${won(v)}`).join(", ");
    const n = new Notification(`오늘 쓴 돈 ${won(d.total)}`, {
      body: top || (d.payments.length ? "모두 정산·취소로 돌려받았어요." : "오늘은 기록된 지출이 없어요."),
    });
    n.onclick = () => { window.focus(); openDay(today); n.close(); };
  } catch { /* 다음 확인 때 다시 시도하지 않는다: 하루 한 번만 */ }
}

function row({ category, title, titleHtml, meta, right, extra = "" }) {
  return `<div class="row"><div class="em" style="--c:${cat(category).c}">${cat(category).e}</div>
    <div class="body"><div class="title">${titleHtml ?? esc(title)}</div><div class="meta">${meta}</div>${extra}</div>
    <div class="right">${right}</div></div>`;
}

// ---------- 거래내역 ----------
async function loadTransactions() {
  const [txns, badges] = await Promise.all([api(`/api/transactions?month=${state.month}`), refreshBadges()]);
  const review = badges.review;
  $("#review-card").hidden = !review.length;
  $("#review-count").textContent = `${review.length}건`;
  $("#review-list").innerHTML = review.slice(0, 30).map((t) => `<div class="review-item">
      <div class="head"><div class="row" style="padding:0;background:none;flex:1">
        <div class="em" style="--c:${cat(t.category).c}">${cat(t.category).e}</div>
        <div class="body"><div class="title">${esc(t.description)}<span class="scope">${t.varies ? "이 거래만" : "같은 가게 전체"}</span></div>
          <div class="meta">${esc(t.occurred_at.slice(0, 16).replace(/-/g, "."))}${t.kind ? ` · ${esc(t.kind)}` : ""}</div></div>
        <div class="right"><div class="amt">${won(t.amount)}</div></div></div></div>
      ${t.ai_guess ? `<div class="guess guess-${t.ai_confidence}">
        <div class="g-body"><div class="g-head">AI 추측 · <b>${cat(t.ai_guess).e} ${esc(t.ai_guess)}</b>
          <span class="g-conf">${CONFIDENCE[t.ai_confidence] || ""}</span></div>
          <div class="g-reason">${esc(t.ai_reason || "")}</div></div>
        ${t.ai_confidence !== "low" ? `<button class="btn btn-ink" data-review="${t.id}" data-cat="${esc(t.ai_guess)}">맞아요</button>` : ""}
      </div>` : ""}
      <div class="chips">${state.meta.categories.map((c) =>
        `<button data-review="${t.id}" data-cat="${c}" class="${c === t.category ? "current" : ""}">${cat(c).e} ${c}</button>`).join("")}</div>
    </div>`).join("") + (review.length > 30 ? `<div class="empty">나머지 ${review.length - 30}건은 위의 것을 정하면 이어서 보여요.</div>` : "");

  const outs = txns.filter((t) => t.direction === "out" && t.category !== "제외");
  $("#txns-sub").textContent = `${txns.length}건 · 지출 ${won(outs.reduce((a, t) => a + t.amount, 0))}`;
  const options = (cur) => state.meta.categories.map((c) => `<option ${c === (cur || "기타") ? "selected" : ""}>${c}</option>`).join("");
  let lastDay = "";
  $("#txn-list").innerHTML = txns.length ? txns.map((t) => {
    const day = t.occurred_at.slice(0, 10);
    const head = day !== lastDay ? `<div class="day-head">${md(day)} (${WEEKDAYS[(parseDate(day).getDay() + 6) % 7]})</div>` : "";
    lastDay = day;
    const isOut = t.direction === "out";
    return head + row({
      category: isOut ? t.category : "입금",
      titleHtml: esc(t.description) + (t.needs_review ? `<span class="tag">확인 필요</span>` : ""),
      meta: `${t.occurred_at.slice(11, 16)}${t.kind ? ` · ${esc(t.kind)}` : ""}${!isOut ? ` · ${t.settled ? "정산·취소로 연결됨" : "수입"}` : ""}`,
      right: `<div class="amt ${isOut ? (t.category === "제외" ? "excluded" : "") : "in"}">${isOut ? "−" : "+"}${won(t.amount)}</div>`
        + (isOut ? `<select data-txn="${t.id}" aria-label="카테고리">${options(t.category)}</select>` : ""),
    });
  }).join("") : `<div class="empty">이 달의 거래가 없어요. 아래 + 버튼으로 거래내역을 올려 주세요.</div>`;
}

async function setCategory(id, category) {
  const r = await api(`/api/transactions/${id}`, { method: "PATCH", json: { category } });
  const status = $("#recat-status");
  status.hidden = !(r.scope === "merchant" && r.updated > 1);
  status.textContent = `같은 가게의 거래 ${r.updated}건을 '${category}'(으)로 바꿨어요.`;
  await loadTransactions();
}
document.addEventListener("change", (e) => {
  if (e.target.dataset.txn) setCategory(e.target.dataset.txn, e.target.value).catch(showError);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-review]");
  if (b) setCategory(b.dataset.review, b.dataset.cat).catch(showError);
});

$("#recat-btn").addEventListener("click", async () => {
  if (!confirm("AI가 정한 카테고리를 모두 지우고 다시 분류할까요? 직접 정한 분류는 그대로 남아요.")) return;
  const btn = $("#recat-btn"), status = $("#recat-status");
  btn.disabled = true;
  status.hidden = false;
  status.textContent = "AI가 다시 분류하고 있어요. 수십 초 걸릴 수 있어요.";
  try {
    await api("/api/recategorize", { method: "POST" });
    status.textContent = "다시 분류했어요.";
    await loadTransactions();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------- 정산 ----------
// 받은 돈 하나가 결제 여러 개의 몫이면 결제마다 나눠 준 금액(share)을 같이 보여준다
const pairHtml = (p) => {
  const pays = p.payments || [p.payment];
  const many = pays.length > 1;
  return `<div class="pair">
  <div class="tx in"><div class="k">받은 돈 · ${md(p.incoming.occurred_at)}</div><div class="t">${esc(p.incoming.description)}</div><div class="a">+${won(p.incoming.amount)}</div></div>
  <span class="arrow">${svg("i-arrow").replace("<svg>", '<svg width="18" height="18">')}</span>
  <div class="pays">${pays.map((x) => `<div class="tx out"><div class="k">결제 · ${md(x.occurred_at)}</div>
    <div class="t">${esc(x.description)}</div><div class="a">${won(x.amount)}${many ? ` <span class="share">중 ${won(x.share)}</span>` : ""}</div></div>`).join("")}</div>
</div>`;
};

async function loadSettlements() {
  const { settlements: s } = await refreshBadges();
  $("#pending-count").textContent = s.pending.length ? `${s.pending.length}건` : "";
  $("#pending-list").innerHTML = s.pending.length ? s.pending.map((p) => `<div class="settle-item">${pairHtml(p)}
      <div class="reason">${esc(p.reason || "")}</div>
      <div class="actions"><button class="btn btn-ink" data-confirm="${p.id}">맞아요, 확정</button>
        <button class="btn btn-ghost" data-reject="${p.id}">정산 아니에요</button></div></div>`).join("")
    : `<div class="empty">확인할 정산이 없어요.</div>`;

  $("#confirmed-count").textContent = s.confirmed.length ? `${s.confirmed.length}건` : "";
  $("#confirmed-list").innerHTML = s.confirmed.length ? s.confirmed.map((p) => `<div class="settle-item compact">${pairHtml(p)}
      <div class="actions" style="margin-top:8px;justify-content:space-between;align-items:center">
        <span class="muted" style="font-size:12.5px">${esc(p.reason === "결제 취소" ? "결제 취소 (자동 연결)" : p.reason === "직접 연결" ? "직접 연결" : "AI 제안 확정")}</span>
        <button class="btn btn-ghost" style="padding:5px 12px;font-size:12.5px" data-reject="${p.id}">연결 취소</button></div></div>`).join("")
    : `<div class="empty">아직 확정한 정산이 없어요.</div>`;

  $("#link-incoming").innerHTML = `<option value="">받은 돈 고르기</option>` + s.unlinked
    .map((t) => `<option value="${t.id}">${md(t.occurred_at)} ${esc(t.description)} +${won(t.amount)}</option>`).join("");
  $("#link-step").hidden = true;
}

// 받은 돈을 고르면 그 무렵(2주 전 ~ 이틀 뒤) 결제 몇 개만 카드로 보여준다
$("#link-incoming").addEventListener("change", async (e) => {
  const step = $("#link-step");
  if (!e.target.value) { step.hidden = true; return; }
  try {
    const pays = await api(`/api/settlements/candidates?incoming_id=${e.target.value}`);
    $("#link-payments").innerHTML = pays.length ? pays.map((t) => `<button type="button" class="pick" data-pick="${t.id}" aria-pressed="false">
        <span class="em" style="--c:${cat(t.category).c}">${cat(t.category).e}</span>
        <span class="body"><span class="t">${esc(t.description)}</span><span class="d">${esc(t.occurred_at.slice(5, 16).replace("-", ".").replace("-", "."))}</span></span>
        <span class="a">${won(t.amount)}</span></button>`).join("")
      : `<div class="empty">그 무렵 결제가 없어요.</div>`;
    step.hidden = false;
  } catch (err) { showError(err); }
});

$("#link-payments").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pick]");
  if (b) b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
});

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-confirm],[data-reject]");
  if (!b) return;
  const id = b.dataset.confirm || b.dataset.reject;
  try {
    await api(`/api/settlements/${id}/${b.dataset.confirm ? "confirm" : "reject"}`, { method: "POST" });
    await loadSettlements();
  } catch (err) { showError(err); }
});

$("#link-btn").addEventListener("click", async () => {
  const incoming_id = Number($("#link-incoming").value);
  const payment_ids = $$('#link-payments [aria-pressed="true"]').map((b) => Number(b.dataset.pick));
  if (!incoming_id || !payment_ids.length) return showError("받은 돈 하나와 결제를 하나 이상 골라 주세요.");
  try {
    await api("/api/settlements", { method: "POST", json: { incoming_id, payment_ids } });
    await loadSettlements();
  } catch (err) { showError(err); }
});

// ---------- 업로드 ----------
async function uploadFile(file) {
  $("#drop-text").textContent = `${file.name} 처리 중이에요. AI 분류에 수십 초 걸릴 수 있어요.`;
  const fd = new FormData();
  fd.append("file", file);
  if ($("#pdf-password").value) fd.append("password", $("#pdf-password").value);
  const box = $("#upload-result");
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    box.innerHTML = `<div class="notice ok">새 거래 ${r.added}건을 추가했어요${r.duplicates ? ` (이미 있던 ${r.duplicates}건은 건너뜀)` : ""}.
      ${r.proposals ? `<br>정산 후보 ${r.proposals}건을 찾았어요. <a href="#" data-go="settle">정산 확인하기</a>` : `<br><a href="#" data-go="home">홈에서 보기</a>`}</div>
      ${r.warning ? `<div class="notice warn">${esc(r.warning)}</div>` : ""}`;
    refreshBadges();
    autoReport();
  } catch (err) {
    box.innerHTML = `<div class="notice warn">${esc(err.message)}</div>`;
  } finally {
    $("#drop-text").textContent = "파일을 끌어다 놓거나 눌러서 고르기";
    $("#file").value = "";
  }
}
$("#file").addEventListener("change", (e) => e.target.files[0] && uploadFile(e.target.files[0]));
const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});

// ---------- 예산 ----------
async function loadBudgets() {
  const b = await api("/api/budgets");
  $("#budget-form").innerHTML = state.meta.categories.filter((c) => c !== "제외").map((c) => `<label class="set-row">
      <span class="em" style="--c:${cat(c).c}">${esc(cat(c).e)}</span><span class="name">${esc(c)}</span>
      <input type="number" inputmode="numeric" min="0" step="10000" name="${esc(c)}" value="${b[c] ?? ""}" placeholder="없음" aria-label="${esc(c)} 한 달 예산"></label>`).join("");
  renderCategories();
  renderNotifySettings();
}

// ---------- 카테고리 관리 ----------
// 기본 카테고리는 이모지만, 내가 만든 카테고리는 이모지·설명을 바꾸고 지울 수 있다
const EMOJI_IDEAS = ["🏋️", "📚", "✈️", "🐶", "🎁", "💄", "🎵", "☕", "🍰", "🏠", "💊", "🎓"];

async function refreshCategories(message) {
  state.meta = await api("/api/meta");
  applyCategories(state.meta.category_info);
  await loadBudgets();
  const status = $("#cat-status");
  status.hidden = !message;
  status.textContent = message || "";
}

function renderCategories() {
  $("#cat-manage").innerHTML = state.meta.category_info.map((c) => `<div class="cat-row">
      <input class="cat-emoji" value="${esc(c.emoji)}" data-cat-emoji="${esc(c.name)}" maxlength="8" aria-label="${esc(c.name)} 이모지">
      <div class="body"><b>${esc(c.name)}</b>
        ${c.builtin ? `<span class="sub">${esc(c.description)}</span>`
          : `<input class="cat-desc" value="${esc(c.description)}" data-cat-desc="${esc(c.name)}" maxlength="80" placeholder="어떤 지출이 들어가나요" aria-label="${esc(c.name)} 설명">`}</div>
      ${c.builtin ? `<span class="lock">기본</span>` : `<button type="button" class="btn btn-ghost" data-cat-del="${esc(c.name)}">삭제</button>`}
    </div>`).join("");
  $("#emoji-ideas").innerHTML = EMOJI_IDEAS.map((e) => `<button type="button" data-emoji-idea="${e}" aria-label="${e} 고르기">${e}</button>`).join("");
}

$("#cat-manage").addEventListener("change", async (e) => {
  const t = e.target, name = t.dataset.catEmoji || t.dataset.catDesc;
  if (!name) return;
  const json = t.dataset.catEmoji ? { emoji: t.value } : { description: t.value };
  try {
    await api(`/api/categories/${encodeURIComponent(name)}`, { method: "PATCH", json });
    await refreshCategories(`'${name}'을(를) 바꿨어요.`);
  } catch (err) { showError(err); await refreshCategories(); }
});

$("#cat-manage").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cat-del]");
  if (!b) return;
  // 한 번 더 눌러야 지운다 (브라우저 확인 창 대신)
  if (b.dataset.armed !== "1") { b.dataset.armed = "1"; b.textContent = "정말 삭제"; b.classList.add("danger"); return; }
  const name = b.dataset.catDel;
  try {
    const r = await api(`/api/categories/${encodeURIComponent(name)}`, { method: "DELETE" });
    await refreshCategories(r.moved ? `'${name}'을(를) 지웠어요. 거래 ${r.moved}건은 '기타'로 옮겨서 분류 확인에 다시 올렸어요.`
      : `'${name}'을(를) 지웠어요.`);
  } catch (err) { showError(err); }
});

$("#emoji-ideas").addEventListener("click", (e) => {
  const b = e.target.closest("[data-emoji-idea]");
  if (b) $("#new-emoji").value = b.dataset.emojiIdea;
});

$("#new-add").addEventListener("click", async () => {
  const name = $("#new-name").value.trim();
  try {
    await api("/api/categories", { method: "POST", json: {
      name, emoji: $("#new-emoji").value, description: $("#new-desc").value } });
    ["#new-name", "#new-desc", "#new-emoji"].forEach((s) => ($(s).value = ""));
    await refreshCategories(`'${name}'을(를) 만들었어요. 앞으로 올라오는 거래부터 AI가 써요. 예전 거래에도 넣으려면 거래 탭에서 'AI로 다시 분류'를 눌러 주세요.`);
  } catch (err) {
    const status = $("#cat-status");
    status.hidden = false;
    status.textContent = err.message;
  }
});
$("#budget-save").addEventListener("click", async () => {
  const body = {};
  new FormData($("#budget-form")).forEach((v, k) => { body[k] = Number(v) || 0; });
  try {
    await api("/api/budgets", { method: "PUT", json: body });
    const saved = $("#budget-saved");
    saved.hidden = false;
    setTimeout(() => (saved.hidden = true), 1500);
  } catch (err) { showError(err); }
});

// ---------- 보고서 ----------
function renderWeeks() {
  const start = mondayOf(parseDate(state.meta.today));
  $("#weeks").innerHTML = Array.from({ length: 8 }, (_, i) => {
    const d = addDays(start, -7 * i), iso = isoDate(d);
    const label = i === 0 ? "이번 주" : i === 1 ? "지난 주" : `${i}주 전`;
    return `<button data-week="${iso}" class="${iso === state.week ? "active" : ""}"><b>${label}</b>${md(iso)} – ${md(isoDate(addDays(d, 6)))}</button>`;
  }).join("");
}
$("#weeks").addEventListener("click", (e) => {
  const b = e.target.closest("[data-week]");
  if (!b) return;
  state.week = b.dataset.week;
  loadReport().catch(showError);
});

async function loadReport() {
  state.week ||= isoDate(mondayOf(parseDate(state.meta.today)));
  renderWeeks();
  const [w, reports, s] = await Promise.all([api(`/api/week?start=${state.week}`), api("/api/reports"),
    api(`/api/summary?month=${state.month}`)]);
  state.reports = reports;
  const diff = w.this_week.total - w.last_week.total;
  $("#wk-this").textContent = num(w.this_week.total);
  $("#wk-delta").className = `delta ${diff > 0 ? "up" : diff < 0 ? "down" : "muted"}`;
  $("#wk-delta").textContent = w.last_week.total ? `지난 주보다 ${won(Math.abs(diff))} ${diff > 0 ? "더" : "덜"}` : "지난 주 기록 없음";
  const budget = Object.entries(w.weekly_budget).filter(([c]) => c !== "제외").reduce((a, [, v]) => a + v, 0);
  $("#wk-budget").parentElement.innerHTML = budget ? `<b class="num" id="wk-budget">${num(budget)}</b><span>원</span>`
    : `<b id="wk-budget" style="font-size:18px">아직 없음</b>`;
  $("#wk-budget-note").innerHTML = budget ? (w.this_week.total > budget ? `${won(w.this_week.total - budget)} 넘었어요` : `${won(budget - w.this_week.total)} 남았어요`)
    : `<a href="#" data-go="budget" style="color:inherit">예산 정하기</a>`;

  const saved = reports.find((r) => r.week_start === state.week);
  $("#report-btn").textContent = saved ? "다시 만들기" : "보고서 만들기";
  $("#report-body").innerHTML = saved ? DOMPurify.sanitize(marked.parse(saved.content))
    : `<div class="empty">이 주의 보고서가 아직 없어요. 보고서 만들기를 누르면 AI가 써 줘요.</div>`;
  drawReportCharts($("#report-body"));
  drawMonthChart(s.daily);
}

$("#report-btn").addEventListener("click", async () => {
  const btn = $("#report-btn"), status = $("#report-status");
  btn.disabled = true;
  status.hidden = false;
  status.textContent = "AI가 보고서를 쓰고 있어요.";
  try {
    await api("/api/reports", { method: "POST", json: { week_start: state.week } });
    status.hidden = true;
    await loadReport();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

function drawMonthChart(daily) {
  state.chart?.destroy();
  const today = state.meta.today;
  state.chart = new Chart($("#daily-chart"), {
    type: "bar",
    data: {
      labels: Object.keys(daily).map((d) => Number(d.slice(8, 10))),
      datasets: [{
        data: Object.values(daily),
        backgroundColor: Object.keys(daily).map((d) => (d === today ? "#ffd23f" : "#a98bea")),
        borderRadius: 999, borderSkipped: false, maxBarThickness: 10,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (i) => `${i[0].label}일`, label: (i) => won(i.raw) } } },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: "#a597b5", maxRotation: 0, autoSkipPadding: 8 } },
        y: { beginAtZero: true, suggestedMax: 10000, grid: { color: "#eee6f6" }, border: { display: false },
          ticks: { color: "#a597b5", precision: 0, maxTicksLimit: 4, callback: (v) => short(v) } },
      },
    },
  });
}

// 보고서 에이전트가 쓴 ```chart 블록(JSON)을 막대그래프로 바꾼다. 형식이 틀린 블록은 글 그대로 둔다.
state.reportCharts = [];
function drawReportCharts(root) {
  state.reportCharts.forEach((c) => c.destroy());
  state.reportCharts = [];
  root.querySelectorAll("pre > code.language-chart").forEach((code) => {
    let spec;
    try { spec = JSON.parse(code.textContent); } catch { return; }
    const n = spec.labels?.length;
    const series = spec.type === "compare"
      ? [{ label: "지난주", data: spec.last, backgroundColor: "#e3d6f5" }, { label: "이번 주", data: spec.this, backgroundColor: "#a98bea" }]
      : [{ label: spec.title || "", data: spec.values, backgroundColor: "#a98bea" }];
    if (!n || series.some((d) => !Array.isArray(d.data) || d.data.length !== n)) return;
    const box = document.createElement("figure");
    box.className = "report-chart";
    box.innerHTML = `${spec.title ? `<figcaption>${esc(spec.title)}</figcaption>` : ""}<div class="chart-box"><canvas></canvas></div>`;
    code.parentElement.replaceWith(box);
    state.reportCharts.push(new Chart(box.querySelector("canvas"), {
      type: "bar",
      data: { labels: spec.labels, datasets: series.map((d) => ({ ...d, borderRadius: 6, borderSkipped: false, maxBarThickness: 22 })) },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: series.length > 1, position: "bottom", labels: { boxWidth: 10, color: "#6b6280" } },
          tooltip: { callbacks: { label: (i) => `${series.length > 1 ? `${i.dataset.label} ` : ""}${won(i.raw)}` } } },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: "#a597b5", maxRotation: 0 } },
          y: { beginAtZero: true, grid: { color: "#eee6f6" }, border: { display: false },
            ticks: { color: "#a597b5", precision: 0, maxTicksLimit: 4, callback: (v) => short(v) } },
        },
      },
    }));
  });
}

// ---------- 청년정책 ----------
const FIELD_EMOJI = { 주거: "🏠", 자산: "💰", 일자리: "💼", 교통: "🚇", 문화: "🎟️", 학업: "🎓", 건강: "🌿", 생활: "🎁" };

async function renderPolicyCard() {
  const box = $("#policy-card");
  try {
    const r = await api(`/api/policies?month=${state.month}`);
    const linked = r.items?.find((i) => i.spend_note);
    const sub = !r.profile ? "태어난 해·지역 등 4가지만 고르면 돼요"
      : linked ? `${linked.name} · ${linked.spend.category}와 이어져요`
      : r.items.slice(0, 2).map((i) => i.name).join(", ");
    box.innerHTML = `<button class="policy-card" data-go="policy">
      <span class="ico">🎁</span>
      <span class="body"><b>${r.profile ? `받을 수 있는 청년정책 ${r.items.length}개` : "나한테 맞는 청년정책 찾기"}</b>
        <span class="sub">${esc(sub)}</span></span>
      ${svg("i-arrow")}</button>`;
  } catch { box.innerHTML = ""; }
}

function policyCard(i, closed) {
  return `<article class="policy ${closed ? "closed" : ""}">
    <div class="p-head"><span class="p-field">${FIELD_EMOJI[i.field] || "📌"} ${esc(i.field)}</span><span class="p-org">${esc(i.org)}</span></div>
    <h3>${esc(i.name)}</h3>
    <p class="p-amount">${esc(i.amount)}</p>
    <p class="p-sum">${esc(i.summary)}</p>
    ${i.spend_note ? `<p class="p-spend">💡 ${esc(i.spend_note)}</p>` : ""}
    <ul class="p-tags">
      <li class="ok">✓ ${esc(i.reason)}</li>
      ${i.income ? `<li class="warn">소득 기준 확인: ${esc(i.income)}</li>` : ""}
      ${i.conflict_note ? `<li class="warn">${esc(i.conflict_note)}</li>` : ""}
      <li>🗓️ ${esc(i.period)}</li>
    </ul>
    <a class="btn ${closed ? "btn-soft" : "btn-ink"} btn-block" href="${esc(i.apply.url)}" target="_blank" rel="noopener">${esc(i.apply.name)}에서 ${closed ? "다음 모집 보기" : "신청하기"}</a>
  </article>`;
}

async function loadPolicy() {
  const r = await api(`/api/policies?month=${state.month}`);
  $("#pf-region").innerHTML = `<option value="">고르기</option>` + r.regions.map((x) => `<option>${x}</option>`).join("");
  $("#pf-status").innerHTML = `<option value="">고르기</option>` + r.statuses.map((x) => `<option>${x}</option>`).join("");
  const p = r.profile;
  if (p) {
    $("#pf-year").value = p.birth_year;
    $("#pf-region").value = p.region;
    $("#pf-status").value = p.status;
    $("#pf-alone").checked = p.lives_alone;
  }
  $("#policy-form").hidden = !!p;
  $("#pf-summary").hidden = !p;
  if (!p) { $("#policy-list").innerHTML = ""; $("#policy-note").textContent = ""; return; }
  $("#pf-summary").innerHTML = `<span>${p.birth_year}년생 (만 ${r.age}세) · ${esc(p.region)} · ${esc(p.status)}${p.lives_alone ? " · 자취" : ""}</span>
    <button class="btn-ghost btn" id="pf-edit" type="button">바꾸기</button>`;
  const head = (t, n) => `<div class="card-title" style="margin:18px 4px 10px"><h2>${t}</h2>${n ? `<span class="aside">${n}개</span>` : ""}</div>`;
  $("#policy-list").innerHTML = (r.items.length ? head("받을 수 있어요", r.items.length) + r.items.map((i) => policyCard(i, false)).join("")
      : `<div class="empty">지금 조건으로 맞는 정책이 없어요.</div>`)
    + (r.closed.length ? head("이번 모집은 끝났어요") + r.closed.map((i) => policyCard(i, true)).join("") : "");
  $("#policy-note").innerHTML = `${esc(r.note)} (${md(r.as_of)} 기준)<br>참고: `
    + r.sources.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a>`).join(" · ");
}

$("#policy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/policies/profile", { method: "PUT", json: {
      birth_year: Number($("#pf-year").value), region: $("#pf-region").value,
      status: $("#pf-status").value, lives_alone: $("#pf-alone").checked } });
    await loadPolicy();
  } catch (err) { showError(err); }
});
document.addEventListener("click", (e) => {
  if (e.target.id !== "pf-edit") return;
  $("#policy-form").hidden = false;
  $("#pf-summary").hidden = true;
});

// ---------- 시작 ----------
async function init() {
  state.meta = await api("/api/meta");
  applyCategories(state.meta.category_info);
  $("#ai-warning").hidden = state.meta.ai_enabled;
  setMonth(state.meta.today.slice(0, 7));
  Chart.defaults.font.family = '"IBM Plex Sans KR", system-ui, sans-serif';
  await loadHome();
  autoReport();  // 기다리지 않는다: 보고서를 쓰는 동안에도 홈은 바로 보인다
  checkDailyNotify();
  setInterval(checkDailyNotify, 60_000);
}
init().catch(showError);
