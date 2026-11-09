import hashlib

from adapters.nlu.qwen_runtime import build_system_prompt, decode_nlu_output
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode


def test_training_system_prompt_contract_is_stable():
    digest = hashlib.sha256(build_system_prompt().encode("utf-8")).hexdigest()
    assert digest == "770903d61725207eea516c6bbb6997ddff184581cbc741f574626c3b332ff7ee"


def test_invalid_model_json_fails_closed():
    result = decode_nlu_output("not-json")
    assert result == OrderCommandError(
        code=OrderCommandErrorCode.INVALID_JSON,
        message="주문 형식을 해석하지 못했습니다. 다시 말씀해 주세요.",
    )
