from datetime import date

from app import service

# 토스 CSV 형식으로 결제 취소·택시 가승인 반복·비상금을 재현한다
CSV = """거래일자,구분,거래금액,거래 후 잔액,거래내용
2026-10-15 01:34:58,체크카드결제,"17,400",100000,카카오T택시_가승인
2026-10-15 01:34:48,체크카드결제,"-17,400",82600,카카오T택시_가승인
2026-10-15 01:34:31,체크카드결제,"17,400",100000,카카오T택시_가승인
2026-10-15 01:34:20,체크카드결제,"-17,400",82600,카카오T택시_가승인
2026-10-15 01:47:54,체크카드결제,"-5,000",95000,카카오T일반택시(법인)_4
2026-10-24 00:30:52,입금,"50,000",150000,비상금
2026-10-24 00:40:00,출금,"-20,000",130000,비상금
2026-10-20 10:10:46,체크카드결제,"47,600",90000,쿠팡이츠_KCP
2026-10-20 10:10:30,체크카드결제,"-47,600",42400,쿠팡이츠_KCP
2026-10-21 12:00:00,입금,"10,000",52400,이민수
""".encode("utf-8")


def test_refunds_link_automatically_and_internal_transfers_are_skipped(conn):
    r = service.import_file(conn, "toss.csv", CSV, llm=None)
    assert r["added"] == 8
    assert "비상금" in r["warning"]

    s = service.period_summary(conn, date(2026, 10, 1), date(2026, 10, 31))
    assert s["gross"] == 17400 * 2 + 5000 + 47600
    assert s["total"] == 5000  # 가승인 두 번과 쿠팡이츠는 취소돼서 0원
    assert s["income"] == 10000  # 결제 취소와 비상금은 수입이 아니다

    confirmed = service.list_settlements(conn)["confirmed"]
    assert len(confirmed) == 3
    assert all(c["payment"]["description"] == c["incoming"]["description"] for c in confirmed)

    # 다시 올려도 중복 연결되지 않는다
    service.import_file(conn, "toss.csv", CSV, llm=None)
    assert len(service.list_settlements(conn)["confirmed"]) == 3
