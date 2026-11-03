"""Claude 호출 래퍼. 모든 AI 호출은 여기를 거치므로 테스트에서 가짜로 바꿀 수 있다."""
import json
import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

DEFAULT_MODEL = "claude-haiku-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_FALLBACK = ("claude-haiku",)  # Haiku에는 서버 쪽 대체 모델이 없다 (fallbacks를 보내면 안 됨)

Schema = TypeVar("Schema", bound=BaseModel)


class LLMError(Exception):
    """AI 호출이 실패했을 때. 앱은 이 오류를 잡고 AI 없이 계속 동작한다."""


# 공개 가격 (100만 토큰당 달러): 입력, 출력, 캐시 읽기, 캐시 쓰기. Haiku는 프롬프트 10만 토큰 이하 기준.
PRICES_PER_MTOK = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0},
}


class LLM:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model
        self.cost_usd = 0.0  # 이 객체로 부른 호출의 누적 비용 (정확도·비용 비교용)

    def _track(self, usage) -> None:
        if usage is None:
            return
        tokens = {"input": usage.input_tokens, "output": usage.output_tokens,
                  "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                  "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0}
        price = PRICES_PER_MTOK.get(self.model, PRICES_PER_MTOK[DEFAULT_MODEL])
        self.cost_usd += sum(tokens[k] * price[k] for k in tokens) / 1_000_000

    def _request(self, system: str, user: str) -> dict:
        req = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if not self.model.startswith(NO_FALLBACK):
            req.update(betas=[FALLBACK_BETA], fallbacks="default")  # 안전 분류기가 거절하면 서버가 다른 모델로 재시도
        return req

    def parse(self, system: str, user: str, schema: type[Schema]) -> Schema:
        try:
            resp = self.client.beta.messages.parse(**self._request(system, user), output_format=schema)
        except anthropic.APIError as e:
            raise LLMError(f"Claude 호출 실패: {e}") from e
        except ValueError as e:  # 답이 중간에 끊겨 JSON이 깨졌을 때 (pydantic ValidationError)
            raise LLMError(f"Claude 답이 중간에 끊겼어요: {e}") from e
        self._track(resp.usage)
        if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
            raise LLMError("Claude가 응답을 만들지 못했어요.")
        return resp.parsed_output

    def text(self, system: str, user: str) -> str:
        try:
            resp = self.client.beta.messages.create(**self._request(system, user))
        except anthropic.APIError as e:
            raise LLMError(f"Claude 호출 실패: {e}") from e
        self._track(resp.usage)
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
