// 공유용 데모: 서버 대신 브라우저 안에서 같은 API 응답을 만든다.
// 데이터는 samples/sample_toss.csv와 같은 연습용 가짜 거래이고, 바꾼 내용은 새로고침하면 처음으로 돌아간다.
const DEMO_TODAY = "2026-10-30";
// app/categories.py의 BUILTIN과 같은 기본 카테고리 (이름, 이모지, 색, 설명)
const DEMO_BUILTIN = [
  ["식비", "🍚", "#ffb98a", "식당, 학식, 분식, 패스트푸드, 배달앱"], ["편의점", "🏪", "#ffd23f", "이마트24, GS25, CU, 세븐일레븐"],
  ["술", "🍺", "#f2709c", "술집, 호프, 포차, 이자카야"], ["유흥", "🎮", "#a98bea", "카페·디저트, 만화카페, PC방, 노래방, 영화"],
  ["구독료", "🔁", "#c9b6f5", "넷플릭스·유튜브 등 정기결제"], ["교통비", "🚕", "#ffe58a", "택시, 버스·지하철, 교통카드"],
  ["쇼핑", "🛍️", "#f8a9c4", "온라인몰, 옷, 전자기기, 화장품"], ["생활", "🧴", "#e3d6f5", "미용실, 통신요금, 생활용품, 병원, 약국"],
  ["송금", "💸", "#ffd6bd", "사람에게 보낸 돈"], ["기타", "📦", "#cfc4e0", "어디에도 넣기 어려운 것"],
  ["제외", "⏸️", "#f1edf4", "환전, 투자, 저축처럼 지출이 아닌 이동"],
];
const DEMO_PALETTE = ["#9ad0c2", "#f4a7b9", "#b8a4f0", "#ffcf99", "#a7c7f2", "#f6c1e0"];
const demoCategories = DEMO_BUILTIN.map(([name, emoji, color, description]) =>
  ({ name, emoji, color, description, builtin: true, special: ["송금", "기타", "제외"].includes(name) }));
const categoryNames = () => demoCategories.map((c) => c.name);

// [일시, 내용, 부호 있는 금액, 은행 거래 유형, 카테고리, 거래마다 용도가 다른지]
const DEMO_ROWS = [
  ["2026-10-01 09:00:12", "(주)한빛 급여", 2100000, "입금"],
  ["2026-10-01 12:31:40", "김밥천국 판교점", -8500, "체크카드결제", "식비"],
  ["2026-10-02 08:42:10", "스타벅스 판교역", -5300, "체크카드결제", "유흥"],
  ["2026-10-02 18:20:05", "티머니 충전", -30000, "체크카드결제", "교통비"],
  ["2026-10-03 19:20:11", "고기굽는집 강남점", -96000, "체크카드결제", "식비"],
  ["2026-10-03 21:05:40", "이민수", 24000, "입금"],
  ["2026-10-04 10:12:03", "박지훈", 24000, "입금"],
  ["2026-10-04 13:47:22", "최유나", 24000, "입금"],
  ["2026-10-05 14:10:00", "쿠팡", -52400, "체크카드결제", "쇼핑"],
  ["2026-10-06 21:10:00", "GS25 판교역점", -6200, "체크카드결제", "편의점"],
  ["2026-10-07 12:05:31", "맘스터치", -9800, "체크카드결제", "식비"],
  ["2026-10-08 20:30:00", "넷플릭스", -13500, "체크카드결제", "구독료"],
  ["2026-10-10 22:15:44", "판교포차", -180000, "체크카드결제", "술"],
  ["2026-10-11 01:40:09", "코인노래방 판교", -12000, "체크카드결제", "유흥"],
  ["2026-10-11 11:20:15", "이민수", 48000, "입금"],
  ["2026-10-11 12:02:51", "박지훈", 48000, "입금"],
  ["2026-10-11 15:30:33", "정하늘", 48000, "입금"],
  ["2026-10-13 08:40:10", "스타벅스 판교역", -5300, "체크카드결제", "유흥"],
  ["2026-10-14 19:10:00", "SKT 통신요금", -65000, "자동이체", "생활"],
  ["2026-10-15 12:30:00", "김밥천국 판교점", -8500, "체크카드결제", "식비"],
  ["2026-10-16 23:40:00", "GS25 판교역점", -4300, "체크카드결제", "편의점"],
  ["2026-10-17 18:55:00", "카카오T 택시", -38400, "체크카드결제", "교통비"],
  ["2026-10-17 19:30:21", "박지훈", 19200, "입금"],
  ["2026-10-18 15:00:00", "무신사", -89000, "체크카드결제", "쇼핑"],
  ["2026-10-19 10:00:00", "엄마", 200000, "입금"],
  ["2026-10-20 13:15:00", "연세약국", -7200, "체크카드결제", "생활"],
  ["2026-10-21 21:40:00", "김철수", -15000, "출금", "송금", true],
  ["2026-10-22 12:20:00", "맘스터치", -9800, "체크카드결제", "식비"],
  ["2026-10-23 13:05:00", "카카오페이", -12900, "오픈뱅킹", "기타", true],
  ["2026-10-24 19:45:00", "배달의민족", -32000, "체크카드결제", "식비"],
  ["2026-10-24 20:30:12", "최유나", 16000, "입금"],
  ["2026-10-25 00:00:01", "토스뱅크 이자", 1820, "이자입금"],
  ["2026-10-26 08:35:00", "스타벅스 판교역", -5300, "체크카드결제", "유흥"],
  ["2026-10-26 12:40:00", "김밥천국 판교점", -8500, "체크카드결제", "식비"],
  ["2026-10-27 19:00:00", "교촌치킨", -28000, "체크카드결제", "식비"],
  ["2026-10-27 21:12:00", "정하늘", 14000, "입금"],
  ["2026-10-28 08:30:00", "스타벅스 판교역", -5800, "체크카드결제", "유흥"],
  ["2026-10-28 22:50:00", "CU 판교점", -3900, "체크카드결제", "편의점"],
  ["2026-10-28 23:10:00", "판교포차", -64000, "체크카드결제", "술"],
  ["2026-10-29 09:10:00", "이민수", 32000, "입금"],
  ["2026-10-29 12:10:00", "맘스터치", -9800, "체크카드결제", "식비"],
  ["2026-10-29 18:20:00", "토스페이", -7400, "오픈뱅킹", "기타", true],
  ["2026-10-30 08:45:00", "스타벅스 판교역", -5300, "체크카드결제", "유흥"],
];

const demo = {
  txns: DEMO_ROWS.map(([at, description, signed, kind, category, varies], i) => ({
    id: i + 1, occurred_at: at, description, amount: Math.abs(signed), direction: signed < 0 ? "out" : "in",
    kind, category: signed < 0 ? category : null, varies: !!varies, reviewed: false,
  })),
  settlements: [],
  budgets: { 식비: 250000, 술: 200000, 유흥: 80000, 교통비: 80000, 쇼핑: 150000, 생활: 80000 },
  reports: [],
  policyProfile: null,
};
// 분류 확인 화면의 AI 추측 예시 (실제 앱은 앞뒤 거래·친구 정산·사용자 선택을 보고 만든다)
const DEMO_GUESSES = {
  김철수: ["술", "medium", "판교포차 술자리가 있던 주의 저녁 9시대 친구 송금이라 술값 정산으로 보여요."],
  카카오페이: ["식비", "medium", "평일 점심시간의 1만 원대 결제라 점심 식사로 보여요."],
  토스페이: ["편의점", "low", "주변에 다른 결제가 없어 금액대만 보고 추측했어요."],
};
demo.txns.forEach((t) => {
  const g = DEMO_GUESSES[t.description];
  if (!g || t.direction !== "out") return;
  [t.ai_guess, t.ai_confidence, t.ai_reason] = g;
  if (g[1] !== "low") t.category = g[0];
});
const byId = (id) => demo.txns.find((t) => t.id === id);
const findTxn = (at, desc) => demo.txns.find((t) => t.occurred_at.startsWith(at) && t.description === desc).id;
// 고기집 정산은 이미 확정, 나머지는 AI 제안 대기
[["2026-10-03 21:05", "이민수"], ["2026-10-04 10:12", "박지훈"], ["2026-10-04 13:47", "최유나"]].forEach(([at, d]) =>
  demo.settlements.push({ payment_id: findTxn("2026-10-03 19:20", "고기굽는집 강남점"), incoming_id: findTxn(at, d), status: "confirmed", reason: "AI 제안 확정" }));
const PENDING = [
  ["2026-10-11 11:20", "이민수", "2026-10-10 22:15", "판교포차", "술자리 다음 날 오전, 같은 금액 48,000원이 세 명에게서 들어왔어요. 180,000원을 4명이 나눈 몫(45,000원)과 비슷해요."],
  ["2026-10-11 12:02", "박지훈", "2026-10-10 22:15", "판교포차", "판교포차 결제 다음 날 같은 금액으로 들어온 송금이에요."],
  ["2026-10-11 15:30", "정하늘", "2026-10-10 22:15", "판교포차", "판교포차 결제 다음 날 같은 금액으로 들어온 세 번째 송금이에요."],
  ["2026-10-17 19:30", "박지훈", "2026-10-17 18:55", "카카오T 택시", "택시 결제 35분 뒤 정확히 절반(19,200원)이 들어왔어요."],
  ["2026-10-24 20:30", "최유나", "2026-10-24 19:45", "배달의민족", "배달 주문 45분 뒤 절반(16,000원)이 들어왔어요."],
  ["2026-10-27 21:12", "정하늘", "2026-10-27 19:00", "교촌치킨", "치킨 결제 두 시간 뒤 절반(14,000원)이 들어왔어요."],
  ["2026-10-29 09:10", "이민수", "2026-10-28 23:10", "판교포차", "술자리 다음 날 아침 절반(32,000원)이 들어왔어요."],
];
PENDING.forEach(([ia, id, pa, pd, reason]) =>
  demo.settlements.push({ payment_id: findTxn(pa, pd), incoming_id: findTxn(ia, id), status: "pending", reason }));
demo.settlements.forEach((s, i) => (s.id = i + 1));

// ---- 계산 (app/stats.py, app/service.py와 같은 규칙) ----
// 날짜 도우미는 같은 페이지에 묶이는 static/app.js의 isoDate·parseDate·addDays·daysIn을 쓴다(호출 시점엔 이미 정의됨)
const plusDays = (s, n) => isoDate(addDays(parseDate(s), n));
const monthDays = (s) => daysIn(s.slice(0, 7));
// 정산 하나가 결제 여러 개를 덮을 수 있다: [{id: 결제 id, share: 나눠 준 금액}]
const parts = (s) => s.parts || [{ id: s.payment_id, share: byId(s.incoming_id).amount }];
function allocate(amount, ids) {
  const amounts = ids.map((id) => byId(id).amount), total = amounts.reduce((a, v) => a + v, 0);
  const shares = amounts.map((a) => Math.floor((amount * a) / total));
  shares[shares.length - 1] += amount - shares.reduce((a, v) => a + v, 0);
  return ids.map((id, i) => ({ id, share: shares[i] }));
}
const needsReview = (t) => t.direction === "out" && !t.reviewed && (["송금", "기타"].includes(t.category) || t.varies);
const settledIn = (status) => new Set(demo.settlements.filter((s) => s.status === status).map((s) => s.incoming_id));

function summarize(start, end, topN = 10) {
  const pays = demo.txns.filter((t) => t.direction === "out" && t.category !== "제외"
    && t.occurred_at.slice(0, 10) >= start && t.occurred_at.slice(0, 10) <= end);
  const back = (status) => {
    const m = {};
    demo.settlements.filter((s) => s.status === status).forEach((s) => parts(s).forEach((x) => { m[x.id] = (m[x.id] || 0) + x.share; }));
    return m;
  };
  const conf = back("confirmed"), pend = back("pending");
  const net = {}, proj = {};
  pays.forEach((p) => {
    net[p.id] = Math.max(0, p.amount - (conf[p.id] || 0));
    proj[p.id] = Math.max(0, p.amount - (conf[p.id] || 0) - (pend[p.id] || 0));
  });
  const daily = {};
  for (let d = start; d <= end; d = plusDays(d, 1)) daily[d] = 0;
  const byCat = {};
  pays.forEach((p) => {
    daily[p.occurred_at.slice(0, 10)] += net[p.id];
    byCat[p.category || "기타"] = (byCat[p.category || "기타"] || 0) + net[p.id];
  });
  const confirmedIn = settledIn("confirmed");
  const income = demo.txns.filter((t) => t.direction === "in" && !confirmedIn.has(t.id)
    && t.occurred_at.slice(0, 10) >= start && t.occurred_at.slice(0, 10) <= end).reduce((a, t) => a + t.amount, 0);
  const sum = (o) => Object.values(o).reduce((a, v) => a + v, 0);
  return {
    gross: pays.reduce((a, p) => a + p.amount, 0), total: sum(net), projected_total: sum(proj), daily,
    by_category: Object.fromEntries(Object.entries(byCat).sort((a, b) => b[1] - a[1])), income,
    top: [...pays].sort((a, b) => net[b.id] - net[a.id]).filter((p) => net[p.id] > 0).slice(0, topN).map((p) => ({
      date: p.occurred_at.slice(0, 10), description: p.description, category: p.category || "기타", amount: p.amount, net: net[p.id],
    })),
  };
}

function txnJson(t) {
  const confirmedIn = settledIn("confirmed");
  return { ...t, occurred_at: t.occurred_at.slice(0, 16), needs_review: needsReview(t) ? 1 : 0, varies: t.varies ? 1 : 0,
    settled: confirmedIn.has(t.id) ? "confirmed" : null };
}
const brief = (t) => ({ id: t.id, occurred_at: t.occurred_at.slice(0, 16), description: t.description, amount: t.amount });

// ---- 주간 보고서 (실제 앱은 Console 보고서 에이전트가 도구로 숫자를 받아 이 양식으로 쓴다) ----
const DEMO_EMOJI = Object.fromEntries(DEMO_BUILTIN.map(([n, e]) => [n, e]));
const wonText = (n) => `${Math.round(n).toLocaleString("ko-KR")}원`;
const DEMO_TIPS = {
  술: "2차는 건너뛰고 1차에서 마무리", 유흥: "커피는 학교 카페·텀블러 할인으로", 식비: "배달 대신 한 번은 포장·학식으로",
  편의점: "소액 여러 번 대신 마트에서 한 번에", 교통비: "막차 전에 지하철·버스로", 쇼핑: "장바구니에 하루 묵혀 두고 사기",
};

function demoReport(ws) {
  const we = plusDays(ws, 6);
  const now = summarize(ws, we, 50), last = summarize(plusDays(ws, -7), plusDays(ws, -1));
  const diff = now.total - last.total;
  const cats = Object.entries(now.by_category).filter(([, v]) => v > 0);
  const daily = Object.values(now.daily);
  const days = ["월", "화", "수", "목", "금", "토", "일"];
  const peak = daily.indexOf(Math.max(...daily));
  const weekly = Object.fromEntries(Object.entries(demo.budgets).map(([c, v]) => [c, Math.round((v / monthDays(ws)) * 7)]));
  const budgetRows = Object.entries(weekly).filter(([c]) => now.by_category[c])
    .map(([c, b]) => [c, b, now.by_category[c]]).sort((a, b) => (b[2] - b[1]) - (a[2] - a[1]));
  const allCats = [...new Set([...Object.keys(now.by_category), ...Object.keys(last.by_category)])]
    .sort((a, b) => (now.by_category[b] || 0) - (now.by_category[a] || 0)).slice(0, 6);
  const cuts = now.top.filter((t) => DEMO_TIPS[t.category]).slice(0, 2)
    .map((t) => ({ ...t, save: Math.round((t.net * 0.4) / 100) * 100 }));
  const over = budgetRows.find(([, b, s]) => s > b);
  const row = (c) => `${DEMO_EMOJI[c] || ""} ${c}`.trim();
  return [
    "## 한 줄 요약",
    `이번 주 실지출은 **${wonText(now.total)}**으로 지난주보다 **${wonText(Math.abs(diff))} ${diff >= 0 ? "더" : "적게"}** 썼어요.`,
    "", "## 이번 주 소비",
    "```chart", JSON.stringify({ type: "bar", title: "요일별 실지출", labels: days, values: daily }), "```",
    `${days[peak]}요일에 가장 많이 썼어요 (${wonText(daily[peak])}).`, "",
    "| 카테고리 | 실지출 | 비중 |", "|---|---:|---:|",
    ...cats.map(([c, v]) => `| ${row(c)} | ${wonText(v)} | ${Math.round((v / now.total) * 100)}% |`),
    "", "## 예산 대비",
    "| 카테고리 | 예산 | 쓴 돈 | 남음/초과 |", "|---|---:|---:|---|",
    ...budgetRows.map(([c, b, s]) => `| ${row(c)} | ${wonText(b)} | ${wonText(s)} | ${s > b ? `⚠️ ${wonText(s - b)} 초과` : `✅ ${wonText(b - s)} 남음`} |`),
    "", "## 지난주 대비",
    "```chart", JSON.stringify({ type: "compare", title: "지난주 vs 이번 주", labels: allCats,
      this: allCats.map((c) => now.by_category[c] || 0), last: allCats.map((c) => last.by_category[c] || 0) }), "```",
    "| 카테고리 | 지난주 | 이번 주 | 변화 |", "|---|---:|---:|---|",
    ...allCats.map((c) => {
      const a = last.by_category[c] || 0, b = now.by_category[c] || 0;
      return `| ${row(c)} | ${wonText(a)} | ${wonText(b)} | ${b >= a ? "▲" : "▼"} ${wonText(Math.abs(b - a))} |`;
    }),
    "", "## 이번 주에 줄일 수 있었던 곳",
    "| 결제 | 금액 | 이렇게 했다면 | 아낄 수 있던 돈 |", "|---|---:|---|---:|",
    ...cuts.map((t) => `| ${t.description} (${Number(t.date.slice(8))}일) | ${wonText(t.net)} | ${DEMO_TIPS[t.category]} | ${wonText(t.save)} |`),
    "", `이렇게 하면 한 주에 약 **${wonText(cuts.reduce((a, t) => a + t.save, 0))}**을 아낄 수 있었어요.`,
    "", "## 다음 주 목표",
    over ? `**${over[0]}${(over[0].charCodeAt(over[0].length - 1) - 0xac00) % 28 ? "은" : "는"} ${wonText(over[1])} 안쪽으로** — 이번 주보다 ${wonText(over[2] - over[1])}만 줄이면 돼요.`
      : `**이번 주처럼 예산 안에서** — 지금 페이스면 충분해요.`,
  ].join("\n");
}

// ---- 청년정책 (실제 앱의 app/policy.py와 같은 규칙, 목록은 빌드할 때 app/policies.json을 넣는다) ----
const DEMO_POLICIES = /*POLICIES*/null;
const POLICY_REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
  "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
const POLICY_STATUSES = ["대학생", "휴학생", "취업준비", "직장인"];

function recommendPolicies(profile, spending, monthLabel) {
  const age = Number(DEMO_TODAY.slice(0, 4)) - profile.birth_year;
  const names = Object.fromEntries(DEMO_POLICIES.policies.map((p) => [p.id, p.name]));
  const items = [], closed = [];
  for (const p of DEMO_POLICIES.policies) {
    if (age < p.age[0] || age > p.age[1]) continue;
    if (p.regions && !p.regions.includes(profile.region)) continue;
    if (p.statuses && !p.statuses.includes(profile.status)) continue;
    if (p.alone && !profile.lives_alone) continue;
    const why = [`만 ${age}세`];
    if (p.regions) why.push(`${profile.region} 거주`);
    if (p.statuses) why.push(profile.status);
    if (p.alone) why.push("자취");
    const spent = p.spend ? (spending[p.spend.category] || 0) : 0;
    const item = { ...p, reason: `${why.join(" · ")} 조건이 맞아요`,
      spend_note: spent ? `${monthLabel} ${p.spend.category} ${spent.toLocaleString("ko-KR")}원 — ${p.spend.hint}` : null,
      conflict_note: p.conflicts.length ? `${p.conflicts.map((c) => names[c]).join(", ")}와(과) 중복 신청은 안 돼요` : null };
    (p.open ? items : closed).push(item);
  }
  items.sort((a, b) => (a.spend_note ? 0 : 1) - (b.spend_note ? 0 : 1) || b.value - a.value);
  return { as_of: DEMO_POLICIES.as_of, note: DEMO_POLICIES.note, sources: DEMO_POLICIES.sources, age, items, closed };
}

class DemoError extends Error {}
const fail = (msg) => { throw new DemoError(msg); };

function demoRoute(path, opts) {
  const url = new URL(path, "https://demo.local");
  const p = url.pathname, method = (opts.method || "GET").toUpperCase();
  const body = opts.body && typeof opts.body === "string" ? JSON.parse(opts.body) : {};
  let m;
  if (p === "/api/meta") return { categories: categoryNames(), category_info: demoCategories, ai_enabled: true, today: DEMO_TODAY };
  if (p === "/api/categories" && method === "POST") {
    const name = (body.name || "").trim(), emoji = (body.emoji || "").trim();
    if (!name || name.length > 10) fail("카테고리 이름은 1~10글자로 정해 주세요.");
    if (!emoji) fail("이모지를 하나 골라 주세요.");
    if (categoryNames().includes(name)) fail(`'${name}' 카테고리는 이미 있어요.`);
    const custom = demoCategories.filter((c) => !c.builtin).length;
    const c = { name, emoji, color: DEMO_PALETTE[custom % DEMO_PALETTE.length], description: (body.description || "").trim(), builtin: false, special: false };
    demoCategories.splice(demoCategories.findIndex((x) => x.name === "송금"), 0, c);
    return c;
  }
  if ((m = p.match(/^\/api\/categories\/(.+)$/))) {
    const name = decodeURIComponent(m[1]), c = demoCategories.find((x) => x.name === name);
    if (!c) fail(`'${name}' 카테고리를 찾을 수 없어요.`);
    if (method === "PATCH") {
      if (body.emoji != null) c.emoji = body.emoji.trim() || c.emoji;
      if (body.description != null) { if (c.builtin) fail("기본 카테고리의 설명은 바꿀 수 없어요."); c.description = body.description.trim(); }
      return { ok: true };
    }
    if (c.builtin) fail("기본 카테고리는 지울 수 없어요.");
    const moved = demo.txns.filter((t) => t.category === name);
    moved.forEach((t) => { t.category = "기타"; t.reviewed = false; });
    demoCategories.splice(demoCategories.indexOf(c), 1);
    delete demo.budgets[name];
    return { moved: moved.length };
  }
  if (p === "/api/summary") {
    const month = url.searchParams.get("month");
    const start = `${month}-01`, end = `${month}-${String(monthDays(start)).padStart(2, "0")}`;
    const s = summarize(start, end);
    return { ...s, month, today: s.daily[DEMO_TODAY] || 0, budgets: { ...demo.budgets } };
  }
  if (p === "/api/day") {
    const day = url.searchParams.get("date");
    const s = summarize(day, day);
    const confirmedBack = {};
    demo.settlements.filter((x) => x.status === "confirmed")
      .forEach((x) => parts(x).forEach((q) => { confirmedBack[q.id] = (confirmedBack[q.id] || 0) + q.share; }));
    const ofDay = demo.txns.filter((t) => t.occurred_at.startsWith(day)).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
    const monthly = Object.values(demo.budgets).reduce((a, v) => a + v, 0);
    return {
      date: day, total: s.total, gross: s.gross, projected_total: s.projected_total, by_category: s.by_category,
      payments: ofDay.filter((t) => t.direction === "out").map((t) => ({ ...txnJson(t), net: Math.max(0, t.amount - (confirmedBack[t.id] || 0)) })),
      incomings: ofDay.filter((t) => t.direction === "in").map(txnJson),
      daily_budget: monthly ? Math.round(monthly / monthDays(day)) : null,
      latest: demo.txns.map((t) => t.occurred_at.slice(0, 10)).sort().pop(),
    };
  }
  if (p === "/api/transactions") {
    const month = url.searchParams.get("month");
    return demo.txns.filter((t) => t.occurred_at.startsWith(month)).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).map(txnJson);
  }
  if ((m = p.match(/^\/api\/transactions\/(\d+)$/)) && method === "PATCH") {
    const t = byId(Number(m[1]));
    if (!t || t.direction !== "out") fail("출금 거래를 찾을 수 없어요.");
    const scope = body.scope || (t.varies ? "one" : "merchant");
    const targets = scope === "one" ? [t] : demo.txns.filter((x) => x.direction === "out" && x.description === t.description);
    targets.forEach((x) => { x.category = body.category; x.reviewed = true; if (scope === "merchant") x.varies = false; });
    return { scope, updated: targets.length };
  }
  if (p === "/api/review") return demo.txns.filter(needsReview).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).map(txnJson);
  if (p === "/api/settlements" && method === "GET") {
    const out = { pending: [], confirmed: [] };
    demo.settlements.filter((s) => s.status !== "rejected")
      .sort((a, b) => byId(b.incoming_id).occurred_at.localeCompare(byId(a.incoming_id).occurred_at))
      .forEach((s) => {
        const payments = parts(s).map((x) => ({ ...brief(byId(x.id)), share: x.share }));
        out[s.status].push({ id: s.id, reason: s.reason, payment: payments[0], payments, incoming: brief(byId(s.incoming_id)) });
      });
    const linked = new Set(demo.settlements.filter((s) => s.status !== "rejected").map((s) => s.incoming_id));
    const notSettlement = /급여|월급|이자|환불|취소|캐시백/;  // app/settle.py의 EXCLUDE_WORDS와 같은 뜻
    out.unlinked = demo.txns.filter((t) => t.direction === "in" && !linked.has(t.id)
        && !notSettlement.test(t.description) && !notSettlement.test(t.kind || ""))
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).map(txnJson);
    return out;
  }
  if (p === "/api/settlements/candidates") {
    const inc = byId(Number(url.searchParams.get("incoming_id")));
    if (!inc) fail("받은 돈을 찾을 수 없어요.");
    const t0 = new Date(inc.occurred_at.replace(" ", "T")).getTime(), day = 86400000;
    return demo.txns
      .filter((t) => t.direction === "out" && !["송금", "제외"].includes(t.category))
      .map((t) => ({ t, dt: new Date(t.occurred_at.replace(" ", "T")).getTime() - t0 }))
      .filter(({ dt }) => dt >= -14 * day && dt <= 2 * day)
      .sort((a, b) => Math.abs(a.dt) - Math.abs(b.dt)).slice(0, 6)
      .map(({ t }) => txnJson(t)).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  }
  const busy = (incoming, except) => demo.settlements.some((s) => s.incoming_id === incoming && s.status === "confirmed" && s.id !== except);
  if ((m = p.match(/^\/api\/settlements\/(\d+)\/(confirm|reject)$/))) {
    const s = demo.settlements.find((x) => x.id === Number(m[1]));
    if (!s) fail("정산 제안을 찾을 수 없어요.");
    if (m[2] === "reject") { s.status = "rejected"; return { ok: true }; }
    if (busy(s.incoming_id, s.id)) fail("이 입금은 이미 다른 결제의 정산으로 확정돼 있어요.");
    s.status = "confirmed";
    demo.settlements.forEach((x) => { if (x.incoming_id === s.incoming_id && x.id !== s.id && x.status === "pending") x.status = "rejected"; });
    return { ok: true };
  }
  if (p === "/api/settlements" && method === "POST") {
    if (busy(body.incoming_id)) fail("이 입금은 이미 다른 결제의 정산으로 확정돼 있어요.");
    demo.settlements.forEach((x) => { if (x.incoming_id === body.incoming_id && x.status === "pending") x.status = "rejected"; });
    const ids = body.payment_ids?.length ? body.payment_ids : [body.payment_id];
    const id = demo.settlements.length + 1;
    demo.settlements.push({ id, payment_id: ids[0], parts: allocate(byId(body.incoming_id).amount, ids),
      incoming_id: body.incoming_id, status: "confirmed", reason: "직접 연결" });
    return { id };
  }
  if (p === "/api/budgets" && method === "GET") return { ...demo.budgets };
  if (p === "/api/budgets" && method === "PUT") {
    Object.entries(body).forEach(([c, v]) => { if (v > 0) demo.budgets[c] = v; else delete demo.budgets[c]; });
    return { ...demo.budgets };
  }
  if (p === "/api/week") {
    const ws = url.searchParams.get("start");
    const pick = (s) => ({ total: s.total, by_category: s.by_category, daily: s.daily });
    const thisWeek = summarize(ws, plusDays(ws, 6));
    return {
      week: `${ws} ~ ${plusDays(ws, 6)}`, this_week: pick(thisWeek), last_week: pick(summarize(plusDays(ws, -7), plusDays(ws, -1))),
      weekly_budget: Object.fromEntries(Object.entries(demo.budgets).map(([c, v]) => [c, Math.round((v / monthDays(ws)) * 7)])),
      top_payments: thisWeek.top,
    };
  }
  if (p === "/api/reports/auto") return { status: "no_ai", week_start: "2026-10-19" };
  if (p === "/api/reports" && method === "GET") {
    if (!demo.reports.length) demo.reports.push({ week_start: "2026-10-26", content: demoReport("2026-10-26") });
    return demo.reports.map((r) => ({ ...r }));
  }
  if (p === "/api/policies" && method === "GET") {
    const base = { profile: demo.policyProfile, regions: POLICY_REGIONS, statuses: POLICY_STATUSES };
    if (!demo.policyProfile) return base;
    const month = url.searchParams.get("month");
    const spending = summarize(`${month}-01`, `${month}-${String(monthDays(`${month}-01`)).padStart(2, "0")}`).by_category;
    return { ...base, ...recommendPolicies(demo.policyProfile, spending, `${Number(month.slice(5, 7))}월`) };
  }
  if (p === "/api/policies/profile" && method === "PUT") {
    if (!(body.birth_year >= 1950 && body.birth_year <= 2016)) fail("태어난 해를 다시 확인해 주세요.");
    if (!POLICY_REGIONS.includes(body.region)) fail("사는 지역을 골라 주세요.");
    if (!POLICY_STATUSES.includes(body.status)) fail("지금 상태를 골라 주세요.");
    demo.policyProfile = { birth_year: body.birth_year, region: body.region, status: body.status, lives_alone: !!body.lives_alone };
    return { ...demo.policyProfile };
  }
  if (p === "/api/reports" && method === "POST") {
    if (!demo.reports.some((r) => r.week_start === body.week_start)) {
      fail("데모에서는 AI를 부르지 않아서, 미리 만들어 둔 이번 주 보고서만 볼 수 있어요.");
    }
    return { content: demo.reports.find((r) => r.week_start === body.week_start).content };
  }
  if (p === "/api/upload") fail("데모에서는 파일을 올릴 수 없어요. 실제 앱에서는 여기에 토스 거래내역서 PDF를 올려요.");
  if (p === "/api/recategorize") fail("데모에서는 AI를 부르지 않아요. 실제 앱에서는 AI가 전체 거래를 다시 분류해요.");
  fail(`데모에 없는 기능이에요: ${p}`);
}

async function api(path, opts = {}) {
  if (opts.json !== undefined) opts = { ...opts, body: JSON.stringify(opts.json) };
  await new Promise((r) => setTimeout(r, 60));
  return JSON.parse(JSON.stringify(demoRoute(path, opts)));
}

function demoToast(message) {
  let el = document.getElementById("demo-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "demo-toast";
    el.className = "demo-toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), 3600);
}
