"""실지출 집계. 실지출 = max(0, 결제액 - 확정된 정산 입금 합)."""
import calendar
from collections import defaultdict
from datetime import date, timedelta

DEFAULT_CATEGORY = "기타"


def net_by_payment(payments: list[dict], settled: list[tuple[int, int]]) -> dict[int, int]:
    refunds: dict[int, int] = defaultdict(int)
    for payment_id, amount in settled:
        refunds[payment_id] += amount
    return {p["id"]: max(0, p["amount"] - refunds[p["id"]]) for p in payments}


def summarize(payments: list[dict], confirmed: list[tuple[int, int]],
              pending: list[tuple[int, int]], start: date, end: date) -> dict:
    """payments: id, occurred_at(datetime), category, amount. start~end(포함) 기간만 집계."""
    in_range = [p for p in payments if start <= p["occurred_at"].date() <= end]
    net = net_by_payment(in_range, confirmed)
    projected = net_by_payment(in_range, confirmed + pending)

    daily = {(start + timedelta(days=i)).isoformat(): 0 for i in range((end - start).days + 1)}
    by_category: dict[str, int] = defaultdict(int)
    for p in in_range:
        daily[p["occurred_at"].date().isoformat()] += net[p["id"]]
        by_category[p["category"] or DEFAULT_CATEGORY] += net[p["id"]]

    return {
        "gross": sum(p["amount"] for p in in_range),
        "total": sum(net.values()),
        "projected_total": sum(projected.values()),
        "daily": daily,
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "net": net,
    }


def week_budget(monthly: int, week_start: date) -> int:
    days = calendar.monthrange(week_start.year, week_start.month)[1]
    return round(monthly / days * 7)
