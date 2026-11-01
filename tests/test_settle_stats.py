from datetime import date, datetime, timedelta

from app.settle import allocate, find_candidates, is_excluded, is_internal
from app.stats import net_by_payment, summarize, week_budget

T0 = datetime(2026, 10, 3, 19, 0)


def pay(id, amount, when=T0, category="식비", desc="고기집"):
    return {"id": id, "occurred_at": when, "description": desc, "amount": amount, "category": category}


def inc(id, amount, when, desc="이민수"):
    return {"id": id, "occurred_at": when, "description": desc, "amount": amount}


def test_candidate_window_includes_7_days_exactly():
    c = find_candidates([pay(1, 90000)], [inc(2, 30000, T0 + timedelta(days=7))])
    assert [x["incoming"]["id"] for x in c] == [2]


def test_candidate_window_excludes_after_7_days_and_long_before_payment():
    late = inc(2, 30000, T0 + timedelta(days=7, seconds=1))
    early = inc(3, 30000, T0 - timedelta(hours=2, seconds=1))
    assert find_candidates([pay(1, 90000)], [late, early]) == []


def test_money_sent_just_before_payment_is_a_candidate():
    # 친구가 주문 3분 전에 자기 몫을 미리 보낸 경우
    c = find_candidates([pay(1, 59500)], [inc(2, 11900, T0 - timedelta(minutes=3))])
    assert [x["incoming"]["id"] for x in c] == [2]


def test_candidate_requires_payments_larger_than_incoming():
    assert find_candidates([pay(1, 30000)], [inc(2, 30000, T0 + timedelta(hours=1))]) == []


def test_incoming_larger_than_each_payment_but_not_their_sum():
    # 1차 식당 + 2차 만화카페를 반씩: 36,350원은 어느 결제보다 크지만 합(72,700원)보다는 작다
    pays = [pay(1, 26500, T0), pay(2, 15000, T0 - timedelta(minutes=40)), pay(3, 31200, T0 + timedelta(hours=3))]
    c = find_candidates(pays, [inc(9, 36350, T0 + timedelta(hours=6))])
    assert sorted(p["id"] for p in c[0]["payments"]) == [1, 2, 3]


def test_allocate_splits_by_payment_amount():
    assert allocate(36350, [15000, 26500, 31200]) == [7500, 13250, 15600]
    assert allocate(14540, [49000, 23700]) == [9800, 4740]
    assert sum(allocate(10001, [1, 1, 1])) == 10001


def test_excluded_keywords():
    assert is_excluded("(주)한빛 급여")
    assert is_excluded("예금이자")
    assert not is_excluded("박지훈")
    assert find_candidates([pay(1, 90000)], [inc(2, 300, T0 + timedelta(hours=1), desc="이자")]) == []


def test_internal_transfers():
    assert is_internal("비상금")
    assert is_internal("원화로 환전 (USD)")
    assert is_internal("원하는 환율에 환전 (USD)")
    assert not is_internal("비상금통장 카페")  # 이름 전체가 '비상금'일 때만


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
