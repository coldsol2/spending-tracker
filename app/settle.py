"""더치페이 정산 후보를 찾는 규칙. AI는 이 후보 안에서만 판단한다."""
from datetime import timedelta

EXCLUDE_WORDS = ["급여", "월급", "이자", "환불", "취소", "캐시백", "배당", "적금", "예금", "이체"]
# 내 계좌끼리 오간 돈(토스 비상금, 환전 등): 수입도 지출도 아니므로 가져오지 않는다.
# 예금주(내 이름)와 오간 돈도 같지만, 이름은 파일마다 달라 service가 account_owners로 따로 본다.
INTERNAL_NAMES = ["비상금"]
INTERNAL_WORDS = ["환전"]
MAX_PAYMENTS_PER_INCOMING = 8
REFUND_WINDOW_DAYS = 30
# 친구가 결제 직전에 미리 보내는 경우가 있다 (예: 주문 3분 전에 자기 몫 송금)
BEFORE_PAYMENT = timedelta(hours=2)


def is_excluded(description: str) -> bool:
    return any(w in description for w in EXCLUDE_WORDS)


def is_internal(description: str) -> bool:
    d = description.strip()
    return d in INTERNAL_NAMES or any(w in d for w in INTERNAL_WORDS)


def is_refund(kind: str, description: str) -> bool:
    """들어온 돈 중 결제 취소인지. 토스는 취소를 양수 '체크카드결제'로 적는다."""
    return "결제" in kind or "취소" in kind or "취소" in description


def find_candidates(payments: list[dict], incomings: list[dict], days: int = 7) -> list[dict]:
    """각 입금마다, 결제 2시간 전 ~ 결제 후 `days`일 사이에 들어온 경우 그 결제를 후보로 묶는다.
    입금 하나가 여러 결제의 몫일 수 있으니 결제 하나가 입금보다 작아도 되지만,
    후보 결제를 모두 합한 금액은 입금보다 커야 한다.

    dict 키: id, occurred_at(datetime), description, amount
    반환: [{"incoming": inc, "payments": [pay, ...]}] (가까운 결제 순)
    """
    window = timedelta(days=days)
    result = []
    for inc in incomings:
        if is_excluded(inc["description"]):
            continue
        matches = [p for p in payments
                   if p["occurred_at"] - BEFORE_PAYMENT <= inc["occurred_at"] <= p["occurred_at"] + window]
        matches.sort(key=lambda p: abs(inc["occurred_at"] - p["occurred_at"]))
        matches = matches[:MAX_PAYMENTS_PER_INCOMING]
        if sum(p["amount"] for p in matches) > inc["amount"]:
            result.append({"incoming": inc, "payments": matches})
    return result


def allocate(amount: int, payment_amounts: list[int]) -> list[int]:
    """입금 하나를 여러 결제에 결제 금액 비율대로 나눈다. 합은 정확히 amount."""
    total = sum(payment_amounts)
    shares = [amount * a // total for a in payment_amounts]
    shares[-1] += amount - sum(shares)
    return shares
