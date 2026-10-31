"""표 인식이 안 되는 PDF의 텍스트를 Claude가 거래 목록으로 정리한다."""
import json
from typing import Literal

from pydantic import BaseModel

from ..parser import Txn, parse_datetime

CHUNK_LINES = 120

SYSTEM = """은행 거래내역서 PDF에서 뽑은 텍스트의 일부가 주어진다(입력 JSON의 text).
텍스트에 있는 거래를 빠짐없이 transactions 목록으로 옮겨라.
- occurred_at: 'YYYY-MM-DD HH:MM:SS' 형식 (시간이 없으면 'YYYY-MM-DD')
- description: 적요/가맹점/상대방 이름
- amount: 원 단위 양의 정수
- direction: 내 계좌에서 돈이 나갔으면 'out', 들어왔으면 'in'
- balance: 거래 후 잔액, 없으면 null
머리글, 계좌 정보, 합계 줄은 거래가 아니다. 텍스트에 없는 거래를 만들지 마라."""


class Row(BaseModel):
    occurred_at: str
    description: str
    amount: int
    direction: Literal["out", "in"]
    balance: int | None


class Extracted(BaseModel):
    transactions: list[Row]


def extractor(llm):
    def extract(text: str) -> list[Txn]:
        lines = [l for l in text.splitlines() if l.strip()]
        txns: list[Txn] = []
        for i in range(0, len(lines), CHUNK_LINES):
            chunk = "\n".join(lines[i:i + CHUNK_LINES])
            out = llm.parse(SYSTEM, json.dumps({"text": chunk}, ensure_ascii=False), Extracted)
            for r in out.transactions:
                when = parse_datetime(r.occurred_at)
                if when is not None and r.amount:
                    txns.append(Txn(when, r.description.strip() or "(내용 없음)", abs(r.amount), r.direction, r.balance))
        return txns
    return extract
