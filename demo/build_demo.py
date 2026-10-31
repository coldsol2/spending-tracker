"""static/ 화면 파일과 demo/mock_api.js를 묶어 링크로 공유할 수 있는 HTML 한 파일을 만든다.

실행: python demo/build_demo.py [출력 경로]   (기본: demo/dist/spending-demo.html)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

# 공유 페이지에 맞춘 덧붙임: 휴대폰 가장자리 여백, 데모 안내 띠, 알림 토스트
EXTRA_CSS = """
:root { color-scheme: light; }
.app { padding-left: max(18px, env(safe-area-inset-left, 0px)); padding-right: max(18px, env(safe-area-inset-right, 0px)); }
.tabbar { bottom: calc(14px + env(safe-area-inset-bottom, 0px)); }
.demo-banner { border-radius: 18px; padding: 10px 14px; margin-bottom: 14px; font-size: 13px;
  background: var(--lilac-soft); color: var(--lilac-deep); }
.demo-banner b { font-weight: 600; }
.demo-toast { position: fixed; left: 50%; transform: translateX(-50%); bottom: calc(100px + env(safe-area-inset-bottom, 0px));
  width: min(380px, calc(100% - 32px)); z-index: 30; background: var(--ink); color: #fff;
  border-radius: 18px; padding: 12px 16px; font-size: 14px; box-shadow: 0 16px 40px -14px rgba(43, 27, 61, .5); }
"""

BANNER = ('<div class="demo-banner"><b>데모</b> · 연습용 가짜 거래내역으로 만든 화면이에요. '
          '눌러 볼 수 있지만 바꾼 내용은 새로고침하면 처음으로 돌아가요.</div>')


def build(out: Path) -> Path:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    mock = (Path(__file__).parent / "mock_api.js").read_text(encoding="utf-8")

    # 실제 서버 호출을 데모용 가짜 서버로 바꾸고, 공유 페이지에서 막히는 alert/confirm을 대체한다
    app = app.replace("async function api(path, opts = {})", "async function serverApi(path, opts = {})", 1)
    app = app.replace("const showError = (e) => alert(e.message || e);", "const showError = (e) => demoToast(e.message || e);", 1)
    app = app.replace('if (!confirm("AI가 정한 카테고리를 모두 지우고 다시 분류할까요? 직접 정한 분류는 그대로 남아요.")) return;', "", 1)
    for needle in ("async function serverApi", "demoToast(e.message", "const state ="):
        assert needle in app, f"app.js 구조가 바뀌어 데모 변환에 실패: {needle}"

    head_links = "\n".join(re.findall(r"<link [^>]*fonts\.(?:googleapis|gstatic)[^>]*>", html))
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = re.sub(r'<script src="/static/app\.js"></script>', "", body)
    body = body.replace('<div class="app">', '<div class="app">\n  ' + BANNER, 1)

    page = f"""<title>실지출 트래커 데모</title>
<meta name="claude:viewport-fit-sides" content="cover">
{head_links}
<style>
{css}
{EXTRA_CSS}
</style>
{body}
<script>
{mock}
</script>
<script>
{app}
</script>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "dist" / "spending-demo.html"
    print(build(target))
