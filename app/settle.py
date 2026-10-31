"""더치페이 정산 후보를 찾는 규칙. AI는 이 후보 안에서만 판단한다."""
from datetime import timedelta

EXCLUDE_WORDS = ["급여", "월급", "이자", "환불", "취소", "캐시백", "배당", "적금", "예금", "이체"]
# 내 계좌끼리 오간 돈(토스 비상금 등): 수입도 지출도 아니므로 가져오지 않는다
INTERNAL_WORDS = ["비상금"]
MAX_PAYMENTS_PER_INCOMING = 5
REFUND_WINDOW_DAYS = 30


def is_excluded(description: str) -> bool:
    return any(w in description for w in EXCLUDE_WORDS)


def is_internal(description: str) -> bool:
    return description.strip() in INTERNAL_WORDS


def is_refund(kind: str, description: str) -> bool:
    """들어온 돈 중 결제 취소인지. 토스는 취소를 양수 '체크카드결제'로 적는다."""
    return "결제" in kind or "취소" in kind or "취소" in description


def find_candidates(payments: list[dict], incomings: list[dict], days: int = 7) -> list[dict]:
    """각 입금마다, 그 전 `days`일 안에 있었던 더 큰 결제를 후보로 묶는다.

    dict 키: id, occurred_at(datetime), description, amount
    반환: [{"incoming": inc, "payments": [pay, ...]}] (가까운 결제 순)
    """
    window = timedelta(days=days)
    result = []
    for inc in incomings:
        if is_excluded(inc["description"]):
            continue
        matches = [
            p for p in payments
            if p["occurred_at"] <= inc["occurred_at"] <= p["occurred_at"] + window
            and inc["amount"] < p["amount"]
        ]
        if matches:
            matches.sort(key=lambda p: inc["occurred_at"] - p["occurred_at"])
            result.append({"incoming": inc, "payments": matches[:MAX_PAYMENTS_PER_INCOMING]})
    return result
