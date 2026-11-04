import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.agent.client import LLMError  # noqa: E402


@pytest.fixture(autouse=True)
def api_engine(monkeypatch):
    """테스트는 진짜 Console 에이전트를 부르지 않는다 (.env의 GUESS_ENGINE=agent를 덮는다)."""
    monkeypatch.setenv("GUESS_ENGINE", "api")
    monkeypatch.setenv("GUESS_SCOPE", "review")
    monkeypatch.setenv("REPORT_ENGINE", "api")


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


class FakeLLM:
    """Claude 대신 쓰는 가짜. handlers[스키마 이름](payload) -> 스키마 인스턴스."""

    def __init__(self, handlers=None, text="# 보고서"):
        self.handlers = handlers or {}
        self.text_value = text
        self.calls = []

    def parse(self, system, user, schema):
        self.calls.append(schema.__name__)
        if schema.__name__ not in self.handlers:
            raise LLMError(f"가짜 LLM에 {schema.__name__} 처리기가 없음")
        return self.handlers[schema.__name__](json.loads(user))

    def text(self, system, user):
        self.calls.append("text")
        return self.text_value
