# MockNLU 일반 주문 문장 처리

## Why

Web UX/E2E 데모의 Mock STT는 고정 발화를 사용하지만 텍스트 fallback은 사용자의 실제 문장을 전달한다. 현재 MockNLU는 일부 정확 문자열만 ADD_ITEM으로 처리하여 일반적인 수량 표현이 메뉴 조회 또는 미지원 발화로 분류된다.

## Goal

- 공식 메뉴명 또는 기존 alias와 수량이 있는 일반 주문형 문장을 ADD_ITEM으로 파싱한다.
- `한/두/세 잔`, `하나/둘` 등 데모에 필요한 수량 표현을 지원한다.
- 질문·설명 요청 문장은 기존 QUERY_MENU로 유지한다.
- 기존 수정, 삭제, 옵션, 추천, undo 동작을 변경하지 않는다.

Out of Scope: 실제 LLM NLU, dialogue history, 대명사 해석, clarification state machine, 새로운 intent/schema, Web UI 변경.

## What

Happy Path:

- `아이스 아메리카노 하나 줘`를 americano/iced/1 ADD_ITEM으로 만든다.
- `캐모마일티 한 잔 주세요`처럼 공식 메뉴명과 수량이 있는 문장을 ADD_ITEM으로 만든다.
- `말차라떼가 뭐야?`, `아메리카노는 아이스도 돼?`는 QUERY_MENU로 유지한다.

Edge Case:

- 메뉴와 무관한 문장은 UNSUPPORTED_UTTERANCE를 반환한다.
- 변경·삭제 표지가 있는 문장은 일반 ADD 규칙이 가로채지 않는다.
- 온도가 필수인 메뉴에서 온도 없는 ADD command의 최종 검증은 기존 Order Engine 정책을 따른다.

## How

- 기존 alias resolver, 공식 메뉴 목록, temperature parser, quantity parser를 재사용한다.
- 메뉴 상세 resolver 결과와 질문·설명 요청 표지가 모두 있을 때만 QUERY_MENU로 확정한다.
- 질문이 아니고 단일 메뉴와 수량이 확인된 경우 ADD_ITEM을 생성한다.
- bare 수량은 공백/문장 경계가 있는 `하나`, `둘`, `셋` 범위만 지원한다.

## AC

- Given 공식 메뉴명과 지원 수량이 있는 주문형 문장, When MockNLU가 파싱하면, Then ADD_ITEM command를 반환한다.
- Given `아이스 아메리카노 하나 줘`, When `/api/order`로 호출하면, Then success=true이고 iced americano 1잔이 cart에 담긴다.
- Given 메뉴 설명 또는 가능 여부 질문, When MockNLU가 파싱하면, Then QUERY_MENU와 적절한 detail_fields를 반환한다.
- Given 메뉴와 관련 없는 문장, When MockNLU가 파싱하면, Then UNSUPPORTED_UTTERANCE를 반환한다.
- Given 기존 전체 테스트, When 변경 후 실행하면, Then 모두 통과한다.
