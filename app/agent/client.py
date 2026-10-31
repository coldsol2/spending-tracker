"""Claude 호출 래퍼. 모든 AI 호출은 여기를 거치므로 테스트에서 가짜로 바꿀 수 있다."""
import json
import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

Schema = TypeVar("Schema", bound=BaseModel)


class LLMError(Exception):
    """AI 호출이 실패했을 때. 앱은 이 오류를 잡고 AI 없이 계속 동작한다."""


class LLM:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def _request(self, system: str, user: str) -> dict:
        return dict(
            model=self.model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",  # 안전 분류기가 거절하면 서버가 다른 모델로 재시도
            system=system,
            messages=[{"role": "user", "content": user}],
        )

    def parse(self, system: str, user: str, schema: type[Schema]) -> Schema:
        try:
            resp = self.client.beta.messages.parse(**self._request(system, user), output_format=schema)
        except anthropic.APIError as e:
            raise LLMError(f"Claude 호출 실패: {e}") from e
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise LLMError("Claude가 응답을 만들지 못했어요.")
        return resp.parsed_output

    def text(self, system: str, user: str) -> str:
        try:
            resp = self.client.beta.messages.create(**self._request(system, user))
        except anthropic.APIError as e:
            raise LLMError(f"Claude 호출 실패: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("Claude가 응답을 만들지 못했어요.")
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def get_client() -> LLM | None:
    """API 키가 없으면 None. 앱은 AI 없이도 동작한다."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    return LLM(anthropic.Anthropic(), os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL))


class ColumnMap(BaseModel):
    header_row: int
    date: int
    time: int | None
    desc: int | None
    amount: int | None
    deposit: int | None
    withdrawal: int | None
    type: int | None
    balance: int | None


COLUMN_SYSTEM = """은행 거래내역 파일의 앞부분 행들이 JSON 배열로 주어진다.
열 이름이 있는 헤더 행의 번호(0부터)와, 각 역할에 해당하는 열 번호(0부터)를 찾아라.
- date: 거래 날짜(또는 날짜+시간), time: 시간만 따로 있는 열
- desc: 거래 내용/가맹점/상대방 이름
- amount: 부호가 있는 거래 금액 한 열 / deposit, withdrawal: 입금액·출금액이 따로 있을 때
- type: 입금/출금/결제 같은 거래 유형, balance: 거래 후 잔액
해당하는 열이 없으면 null."""


def column_mapper(llm: LLM):
    def mapper(rows: list[list[str]]) -> dict:
        m = llm.parse(COLUMN_SYSTEM, json.dumps(rows, ensure_ascii=False), ColumnMap)
        return {
            "header_row": m.header_row, "date": m.date, "time": m.time, "desc": m.desc,
            "amount": m.amount, "in": m.deposit, "out": m.withdrawal, "type": m.type, "balance": m.balance,
        }
    return mapper
