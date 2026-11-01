# 디자인 작업 안내

화면 디자인을 맡아 주시는 분을 위한 문서예요. 서버나 API 키 없이 화면을 보면서 고칠 수 있어요.

## 처음 한 번 준비

| 준비물 | 용도 |
|---|---|
| [GitHub Desktop](https://desktop.github.com) | 명령어 없이 코드를 받고 올리기 |
| [Python 3.11 이상](https://www.python.org/downloads/) | 미리보기 파일 만들기 |
| VS Code 같은 편집기 | 파일 고치기 |

GitHub Desktop에서 **File → Clone repository → spending-tracker**를 고르면 코드가 내려받아져요.

## 화면 보면서 고치기

데모 파일에는 연습용 가짜 거래 43건이 들어 있어서 모든 화면이 채워진 상태로 보여요.

1. `static/` 폴더의 파일을 고쳐요.
2. 프로젝트 폴더에서 미리보기 파일을 만들어요.

   ```bash
   python demo/build_demo.py
   ```

3. `demo/dist/spending-demo.html`을 더블클릭해서 브라우저로 열어요.
4. 또 고치면 2번을 다시 실행하고 브라우저를 새로고침해요.

데모에서는 파일 업로드, AI로 다시 분류, 새 보고서 만들기가 안내 문구만 나와요. 나머지(정산 확정, 카테고리 고르기, 예산 바꾸기, 화면 이동)는 실제처럼 눌러 볼 수 있어요.
폰 화면으로 보려면 브라우저 개발자 도구(F12)의 기기 모드를 쓰면 돼요. 이 앱은 폰 폭(약 390px) 기준으로 만들어졌어요.

## 어디를 고치면 되나요

| 바꾸고 싶은 것 | 파일과 위치 |
|---|---|
| 기본 색 (라일락, 핑크, 노랑, 글자색, 배경) | `static/style.css` 맨 위 `:root { ... }` |
| 카테고리별 색과 아이콘(이모지) | `static/app.js` 맨 위 `CATS = { 식비: {...}, ... }` |
| 글꼴 | `static/index.html`의 Google Fonts 링크, `style.css`의 `font-family` |
| 카드 모양, 여백, 모서리, 그림자 | `static/style.css` (`/* ---------- 홈 ---------- */`처럼 화면별 구역) |
| 화면 뼈대 (어떤 카드가 어디 있는지) | `static/index.html` (화면마다 `<section class="view" id="view-...">`) |
| 목록·카드 안쪽 구조 | `static/app.js`의 `renderFeature`, `row`, `pairHtml`, `renderWeek` 등 |
| 아이콘 (탭바, 버튼) | `static/index.html` 맨 위 `<svg>` 안의 `<symbol id="i-...">` |

### 화면 목록

| 화면 | `id` | 하는 일 |
|---|---|---|
| 홈 | `view-home` | 이번 달 실지출, 카테고리 막대, 이번 주, 안내 카드 |
| 거래 | `view-txns` | 분류 확인(용도 고르기)과 전체 거래 목록 |
| 정산 | `view-settle` | 친구가 보낸 돈을 결제에 연결 (AI 제안 확정, 직접 연결) |
| 보고서 | `view-report` | 주간 보고서, 이번 주 실지출과 예산 |
| 업로드 | `view-upload` | 토스 거래내역서 PDF 올리기 (탭바 가운데 +) |
| 예산 | `view-budget` | 카테고리별 한 달 예산 (홈 오른쪽 위 톱니바퀴) |

### 함께 챙겨 주세요

같은 화면이라도 데이터에 따라 모양이 달라져요.

- 데이터가 하나도 없을 때 (처음 쓰는 사람)
- 카테고리가 많을 때(최대 11개)와 적을 때
- 가게 이름이 아주 길 때 (예: `보드게임카페 무지개 행복역점`)
- 정산 하나가 결제 여러 개에 걸칠 때 (정산 화면)
- 예산을 넘었을 때, 예산을 안 정했을 때

## 건드리지 말아 주세요

- `app/` 폴더: 서버와 계산 로직이에요.
- `.env` 파일과 `data/` 폴더: 각자 PC에만 있어야 해요(이미 올라가지 않게 막혀 있어요).
- `app.js` 안의 `api(...)` 호출과 HTML의 `id="..."` 이름: 기능이 이 이름으로 화면을 찾아요. 구조를 크게 바꿔야 하면 바꾸기 전에 말해 주세요.

## 고친 걸 보내는 방법

main에 바로 올리지 말고 브랜치를 만들어 Pull Request로 보내 주세요.

1. GitHub Desktop에서 **Current branch → New branch** (예: `design-home`)
2. 고친 뒤 **Commit to design-home** → **Publish branch**
3. **Create Pull Request**로 요청을 보내요.

받은 쪽에서 기능이 깨지지 않았는지 확인하고 테스트를 돌린 뒤 합쳐요.
