"""모델 설정: 기본은 Haiku, Haiku에는 fallbacks를 보내지 않는다."""
from types import SimpleNamespace as NS

from app.agent.client import DEFAULT_MODEL, LLM


def test_default_is_haiku_without_fallbacks():
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    req = LLM(None, DEFAULT_MODEL)._request("s", "u")
    assert "fallbacks" not in req and "betas" not in req


def test_opus_keeps_fallbacks():
    req = LLM(None, "claude-opus-5-5")._request("s", "u")
    assert req["fallbacks"] == "default"


def test_cut_off_answer_is_llm_error():
    import pytest
    from app.agent.client import LLMError
    usage = NS(input_tokens=1, output_tokens=16000, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    cut = NS(stop_reason="max_tokens", parsed_output=None, usage=usage)
    llm = LLM(NS(beta=NS(messages=NS(parse=lambda **kw: cut))), DEFAULT_MODEL)
    with pytest.raises(LLMError):
        llm.parse("s", "u", None)


def test_cost_uses_model_price():
    usage = NS(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_input_tokens=0,
               cache_creation_input_tokens=0)
    haiku, opus = LLM(None, "claude-haiku-5-5"), LLM(None, "claude-opus-5-5")
    haiku._track(usage)
    opus._track(usage)
    assert round(haiku.cost_usd, 2) == 0.60 and round(opus.cost_usd, 2) == 24.0
