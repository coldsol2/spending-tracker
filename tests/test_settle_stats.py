from datetime import date, datetime, timedelta

from app.settle import find_candidates, is_excluded
from app.stats import net_by_payment, summarize, week_budget

T0 = datetime(2026, 10, 3, 19, 0)


def pay(id, amount, when=T0, category="식비", desc="고기집"):
    return {"id": id, "occurred_at": when, "description": desc, "amount": amount, "category": category}


def inc(id, amount, when, desc="이민수"):
    return {"id": id, "occurred_at": when, "description": desc, "amount": amount}


def test_candidate_window_includes_7_days_exactly():
    c = find_candidates([pay(1, 90000)], [inc(2, 30000, T0 + timedelta(days=7))])
    assert [x["incoming"]["id"] for x in c] == [2]


def test_candidate_window_excludes_after_7_days_and_before_payment():
    late = inc(2, 30000, T0 + timedelta(days=7, seconds=1))
    early = inc(3, 30000, T0 - timedelta(minutes=1))
    assert find_candidates([pay(1, 90000)], [late, early]) == []


def test_candidate_requires_smaller_amount():
    assert find_candidates([pay(1, 30000)], [inc(2, 30000, T0 + timedelta(hours=1))]) == []


def test_excluded_keywords():
    assert is_excluded("(주)한빛 급여")
    assert is_excluded("예금이자")
    assert not is_excluded("박지훈")
    assert find_candidates([pay(1, 90000)], [inc(2, 300, T0 + timedelta(hours=1), desc="이자")]) == []


def test_candidates_sorted_by_closeness():
    p_old = pay(1, 50000, T0)
    p_new = pay(2, 50000, T0 + timedelta(days=2))
    c = find_candidates([p_old, p_new], [inc(3, 10000, T0 + timedelta(days=3))])
    assert [p["id"] for p in c[0]["payments"]] == [2, 1]


def test_net_spend_floor_zero():
    assert net_by_payment([pay(1, 10000)], [(1, 7000), (1, 7000)]) == {1: 0}


def test_summarize_applies_confirmed_only():
    payments = [pay(1, 96000), pay(2, 4800, T0 + timedelta(days=1), category="카페")]
    s = summarize(payments, confirmed=[(1, 24000), (1, 24000)], pending=[(1, 24000)],
                  start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert s["gross"] == 100800
    assert s["total"] == 48000 + 4800
    assert s["projected_total"] == 24000 + 4800
    assert s["daily"]["2026-10-03"] == 48000
    assert s["daily"]["2026-10-04"] == 4800
    assert s["daily"]["2026-10-01"] == 0
    assert len(s["daily"]) == 31
    assert s["by_category"] == {"식비": 48000, "카페": 4800}


def test_summarize_filters_period_and_defaults_category():
    payments = [pay(1, 1000, category=None), pay(2, 5000, datetime(2026, 9, 30))]
    s = summarize(payments, [], [], date(2026, 10, 1), date(2026, 10, 31))
    assert s["total"] == 1000
    assert s["by_category"] == {"기타": 1000}


def test_week_budget():
    assert week_budget(300000, date(2026, 10, 26)) == 67742
    assert week_budget(300000, date(2026, 11, 2)) == 70000
