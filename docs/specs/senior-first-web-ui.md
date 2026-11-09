# Senior-first Web UI 구조

## Why

현재 Web은 기능 흐름은 연결됐지만 작은 Web app에 가까운 정보 밀도와 화면별로 흔들리는 구조를 갖는다. 고령 사용자가 멀리서도 현재 상태, 주문 결과, 다음 행동을 빠르게 이해할 수 있도록 공통 레이아웃과 시각적 위계를 재정리해야 한다.

## Goal

- WELCOME, SERVICE_MODE, ORDER, ORDER_REVIEW, OPTION_CHANGE, PAYMENT, COMPLETE의 핵심 위계를 큰 글자와 큰 터치 영역으로 구성한다.
- SERVICE_MODE 카드는 화면의 가용 본문 영역에서 세로 가운데 정렬되고 큰 터치 영역을 제공한다.
- LISTENING과 PROCESSING은 하단 5버튼 Footer와 동일한 bounding box에 absolute overlay로 표시한다. 배경은 `rgba(255,255,255,0.50)`의 반투명이며 `backdrop-filter`/blur를 사용하지 않는다. 활성화 중 뒷단 5버튼의 pointer interaction은 차단되고, 닫히면 기존 Footer가 같은 위치에서 그대로 복원된다. 본문(메뉴/장바구니/System Message)의 좌표가 overlay on/off로 변하지 않는다.
- ORDER 화면의 카테고리는 가로 1줄의 고정 Segmented Tab Bar(`전체` / `커피` / `논커피` / `차` / `디저트`)로 제공한다.
- ORDER 화면 하단 메인 CTA는 `장바구니 보기`로 명명하고 주문 확인(`ORDER_REVIEW`)으로 이동한다.
- ORDER 메뉴 그리드는 우측 스크롤바를 시각적으로 숨기고 터치/마우스휠 스크롤을 온전히 유지한다.
- 10개 카페 메뉴 전체는 `web/assets/menu/*.png`의 로컬 고해상도 이미지를 제공하며, metadata 미지정 시 fallback placeholder를 표시한다.
- 메뉴 추가 후 ORDER를 유지하고, 사용자가 `장바구니 보기`를 선택한 경우에만 ORDER_REVIEW로 이동한다.
- 터치 메뉴 카드의 제목은 Menu Catalog의 순수 메뉴명만 표시한다. 온도는 메뉴명에 접두하지 않는다.
- 터치 메뉴에서 HOT/ICED 모두 가능한 메뉴를 누르면 `따뜻하게`와 `아이스로`를 고르는 화면 내 선택 UI를 먼저 표시하고, 선택한 온도로 `ADD_ITEM`을 실행한다. 단일 온도 또는 온도 없는 메뉴는 즉시 추가한다.
- ORDER_REVIEW에서는 스크롤 가능한 메뉴 목록이 고정된 총액·액션보다 먼저 보인다.
- PAYMENT 2×2 결제 카드는 상하 독립 여백을 가진 그리드 블록으로 정렬되며 전체 화면 스크롤을 발생시키지 않는다.
- COMPLETE 화면은 안내 후 10초가 지나면 자동으로 세션을 리셋하고 WELCOME 화면으로 복귀한다.
- 접근성 footer는 다시 듣기·말하기 속도·직원 호출·처음으로의 2×2 대형 버튼과 중앙 확대 마이크를 제공한다. 말하기 속도는 Lv.0→Lv.1→Lv.2→Lv.0으로 순환하고 짧은 preview만 재생한다.
- STT transcript는 Voice Overlay만 소유하며, WELCOME bootstrap/COMPLETE의 처음으로 동작은 server session을 reset하고 WELCOME에서 System Message·이전 Cart·transcript·Voice Overlay·Accessibility footer를 숨긴다.
- PAYMENT 진입 시 mic capture와 TTS resource를 정리한다.
- 사용자 응답이 필요한 TTS 종료 후의 자동 Listening과 VAD는
  [`audio-input-mic.md`](audio-input-mic.md)의 계약을 따른다.
- 사용자에게 다음 행동을 안내하는 speakable System Message는 server의 동일한
  `response_text`를 화면 흰색 박스와 TTS가 1:1로 공유한다. TTS 재생 중에는 해당 흰색 박스를
  초록색(`.is-tts-playing`)으로 강조한다. PROCESSING 상태, 금액, 메뉴 카드
  세부정보처럼 행동 안내가 아닌 UI 문자열은 자동으로 읽지 않는다.
- 말하기 속도 preview(`이 속도로 안내합니다.`)는 접근성 control feedback이므로 흰 박스 문구를
  변경하지 않고 초록 강조도 적용하지 않는다. 음성만 재생하고 직전 System Message를 유지한다.
- 영수증 출력은 `영수증을 출력하는 중입니다.`를 화면과 TTS로 출력하며 재생 중 초록색으로 강조한다.
- 기존 API, 주문, 수정, fulfillment, transcript, TTS, payment, reset 흐름을 유지한다.
- 명확한 화면 조작 발화는 주문 NLU보다 먼저 screen-aware UI Command Router가 처리하며, 메뉴명·수량·옵션 발화만 기존 주문 pipeline으로 전달한다.
- `화면으로 조작하기`와 터치 메뉴 선택은 Touch mode로 전환해 자동 Listening을 중지하고, 명시적인 microphone CTA가 Voice mode를 다시 시작한다.

Out of Scope: streaming STT, reference resolution, 실제 payment, production NLU, 메뉴 탐색 후속 context.

## What

Happy Path:

1. 큰 WELCOME CTA에서 주문을 시작하고 SERVICE_MODE의 세로 중앙 정렬된 큰 선택 카드를 누른다.
2. ORDER는 fulfillment와 compact Cart 요약을 유지하며 음성 또는 Segmented Tab Bar와 2열 터치 메뉴로 메뉴를 계속 추가한다.
3. LISTENING/PROCESSING은 ORDER 또는 OPTION_CHANGE 위 Voice Overlay로 표시하고 TTS는 System Message로 표시한다.
4. ORDER_REVIEW는 이용 방식, 이미지, 메뉴명, 수량, 온도, 가격을 표시하고 수정·결제 경로만 제공한다.
5. 수정은 ORDER로 돌아가고, PAYMENT는 ORDER_REVIEW의 명시적 주문 확정에서만 진입한다.
6. 결제(2×2 독립 그리드)와 완료(10초 후 자동 처음으로)는 독립 화면으로 유지한다.

Edge Case:

- Cart가 비어 있으면 ORDER_REVIEW·PAYMENT·COMPLETE 흐름에 진입하지 않고 메뉴 선택 안내를 표시한다.
- metadata에 이미지가 없는 메뉴는 메뉴명 첫 글자 placeholder를 표시한다.
- transcript가 없으면 transcript 영역을 숨긴다.
- speech가 감지되지 않은 녹음은 `/api/audio`로 보내지 않는다.
- 음성 오류가 발생하면 현재 Context를 유지하고 Overlay에서 돌아갈 수 있다.
- TTS/마이크 정리 실패가 결제 화면 진입을 막지 않는다.
- clarification/search/recommend Context slot은 runtime data가 없으면 숨긴다.
- Cart가 있는 상태에서 처음으로를 누르면 대형 확인 UI를 표시하고 확인 전에는 session을 보존한다.
- 직원 호출은 잠시 disabled 상태와 `직원 호출됨` 표시를 유지해 중복 호출을 막는다.

## How

- `menu-metadata.js`가 10개 메뉴 전체의 로컬 이미지 경로(`assets/menu/*.png`)와 fallback accent를 제공한다.

| 메뉴 ID | 메뉴명 | 카테고리 | 로컬 이미지 경로 |
| :--- | :--- | :--- | :--- |
| `americano` | 아메리카노 | coffee | `assets/menu/americano.png` |
| `cafe_latte` | 카페라떼 | coffee | `assets/menu/cafe-latte.png` |
| `vanilla_latte` | 바닐라라떼 | coffee | `assets/menu/vanilla-latte.png` |
| `grapefruit_ade` | 자몽에이드 | non_coffee | `assets/menu/grapefruit-ade.png` |
| `matcha_latte` | 말차라떼 | non_coffee | `assets/menu/matcha-latte.png` |
| `milk_tea` | 밀크티 | tea | `assets/menu/milk-tea.png` |
| `chamomile_tea` | 캐모마일티 | tea | `assets/menu/chamomile-tea.png` |
| `iced_tea` | 아이스티 | tea | `assets/menu/iced-tea.png` |
| `croffle_icecream` | 크로플 아이스크림 | dessert | `assets/menu/croffle-icecream.png` |
| `basque_cheesecake` | 바스크 치즈 케이크 | dessert | `assets/menu/basque-cheesecake.png` |

- Menu Card renderer를 ORDER, ORDER_REVIEW, OPTION_CHANGE가 공유한다.
- persistent Header와 Accessibility footer를 모든 주문 Context가 공유한다.
- `uiState.screen`과 `voiceState.status`를 분리하고 Voice Overlay는 LISTENING/PROCESSING/ERROR만 렌더링한다.
- TTS playback 중 recorder와 mic를 정리하고 System Message에 재생 상태를 표시하며, TTS 오류는 내부 state와 console에만 남긴다.
- Voice Overlay는 음성 허용 화면(`SERVICE_MODE`, `ORDER`, `ORDER_REVIEW`, `OPTION_CHANGE`, `PAYMENT`)에서 표시하고 `WELCOME`/`COMPLETE` 진입 시 녹음·timer·pending lifecycle을 무효화한다.
- ORDER의 Cart summary는 메뉴 수와 총액, 최근 메뉴 카드를 표시한다.
- `goToScreen()`이 사용자용 상태 라벨과 footer visibility를 함께 갱신한다.
- COMPLETE 화면 진입 시 10초 타이머(`completeAutoHomeTimer`)를 구동하고 세션 리셋 후 WELCOME으로 복귀한다.
- PROCESSING Overlay는 API 요청 동안만 표시하고 내부 STT/NLU 용어를 노출하지 않는다.
- ORDER 전체는 고정하고 메뉴 grid만 scroll하며, 터치 메뉴도 음성과 같은 주문·System Message·TTS pipeline을 사용한다.
- `menu-metadata.js`의 `temperatureOptions`는 Menu Catalog의 `temperature_options`를 그대로 반영한다. Touch handler는 이 값을 사용하며 음성 NLU/clarification 상태를 사용하거나 변경하지 않는다.
- Cart/ORDER_REVIEW의 메뉴명은 순수 메뉴명으로 표시하고, `item.temperature`가 있으면 별도 `아이스` 또는 `따뜻한` 보조 배지를 표시한다.
- ORDER_REVIEW의 각 Cart line은 서버 Cart의 `menu_id`·현재 `quantity`·`temperature`로 `UPDATE_QUANTITY` 또는 `UPDATE_OPTION` command를 전송한다. 응답 Cart로만 화면·총액을 다시 그리며, 1개 항목의 `-`는 삭제 command로 바꾸지 않는다.
- Menu Catalog의 `temperatureOptions`가 정확히 두 개인 Cart line만 `따뜻한`/`아이스` 선택지를 보인다. 온도 변경에는 현재 line의 전체 수량을 `quantity`로 함께 보내어, 같은 메뉴의 다른 온도 line이 있어도 기존 Order Engine의 변경·merge 정책을 사용한다.
- VAD silence hangover는 1,400/1,600/1,800ms 시뮬레이션을 거쳐 선택한 조정 가능한 기본값 1,800ms, maximum recording timeout은 10초로 둔다.
- transcript는 고정 timeout이 아니라 STT 완료부터 다음 System Message 처리 시작까지 유지한다.
- 제품 SVG는 `/assets/*`에서 `image/svg+xml`로 제공하고 브라우저에서 양의 intrinsic size로 렌더링한다.

## AC

- GIVEN 각 주요 화면, WHEN 렌더링하면, THEN 핵심 제목과 CTA가 senior typography/touch target을 사용한다.
- GIVEN ORDER에서 메뉴 추가, WHEN API가 성공하면, THEN ORDER를 유지하고 Cart summary를 갱신한다.
- GIVEN ORDER 또는 OPTION_CHANGE, WHEN 음성 입력을 시작하면, THEN 현재 화면을 유지한 채 LISTENING Overlay를 표시한다.
- GIVEN API 요청 중, WHEN 응답을 기다리면, THEN 현재 화면 위 PROCESSING Overlay가 보인다.
- GIVEN ORDER_REVIEW, WHEN 수정할게요를 누르면, THEN Cart와 fulfillment를 유지하고 ORDER로 돌아간다.
- GIVEN ORDER_REVIEW, WHEN 결제할게요를 누르면, THEN PAYMENT로 이동한다.
- GIVEN 빈 Cart, WHEN 장바구니 보기·주문 확정·결제를 시도하면, THEN 다음 화면으로 진행하지 않고 메뉴 선택 안내를 표시한다.
- GIVEN cart item, WHEN 확인 화면을 렌더링하면, THEN metadata 이미지 또는 placeholder와 수량을 표시한다.
- GIVEN 여러 cart item, WHEN ORDER_REVIEW를 표시하면, THEN 메뉴 목록만 scroll되고 총액·액션·공통 footer는 고정된다.
- GIVEN Lv.0/1/2 또는 TTS playback, WHEN footer·재생 상태를 갱신하면, THEN 실제 level에 맞는 2×2 버튼/상태가 표시되고 재생 중 mic는 꺼지며 Voice Overlay 대신 System Message를 사용한다.
- GIVEN ORDER_REVIEW 또는 이전 server Cart가 있는 WELCOME 진입, WHEN 화면을 렌더링하면, THEN transcript 본문 카드는 없고 reset 후 이전 Cart·transcript·System Message·Voice Overlay·Accessibility footer가 노출되지 않으며 fulfillment 성공 뒤에는 다음 주문 행동을 안내한다.
- GIVEN PAYMENT 또는 COMPLETE, WHEN 늦은 TTS/녹음 callback이 도착하면, THEN Voice Overlay를 열거나 ORDER로 이동하지 않는다.
- GIVEN PAYMENT 진입, WHEN 사용자가 주문을 확정하면, THEN active mic와 TTS resource를 정리한다.
- GIVEN 기존 전체 테스트, WHEN 변경 후 실행하면, THEN 모두 통과한다.
- GIVEN 실제 speech가 없는 녹음, WHEN 종료 또는 timeout되면, THEN Overlay를 닫고 `/api/audio`를 호출하지 않는다.
- GIVEN 말하기 속도 버튼, WHEN 세 번 누르면, THEN level이 0→1→2→0으로 순환하고 매번 `이 속도로 안내합니다.`만 변경 속도로 재생하며 직전 System Message는 유지한다.
- GIVEN ORDER 터치 메뉴, WHEN 메뉴 카드를 누르면, THEN 음성 주문과 같은 Cart·System Message·TTS feedback을 거친다.
- GIVEN HOT/ICED 메뉴의 터치 카드, WHEN 사용자가 카드를 누르면, THEN 메뉴명과 분리된 `따뜻하게`/`아이스로` 선택 UI가 보이고 선택한 값으로만 `ADD_ITEM`을 실행한다.
- GIVEN 단일 온도 또는 온도 없는 메뉴의 터치 카드, WHEN 사용자가 카드를 누르면, THEN 온도 선택 UI 없이 해당 Menu Catalog 온도로 즉시 추가한다.
- GIVEN Cart 또는 ORDER_REVIEW, WHEN 온도가 있는 항목을 렌더링하면, THEN 메뉴명과 분리된 `아이스` 또는 `따뜻한` 보조 배지를 표시한다.
- GIVEN ORDER_REVIEW의 Cart line, WHEN `+` 또는 수량이 2 이상인 `-`를 누르면, THEN `UPDATE_QUANTITY`의 server 응답 Cart 기준으로 수량·가격·총액을 즉시 갱신한다.
- GIVEN 수량 1인 Cart line, WHEN `-`를 누르면, THEN 수량을 0으로 바꾸거나 삭제하지 않고 기존 삭제 경로를 유지한다.
- GIVEN 두 온도를 지원하는 Cart line, WHEN 다른 온도를 누르면, THEN 현재 line 전체 수량을 유지한 `UPDATE_OPTION` server 응답으로 갱신하며 기존 동일 menu+temperature line은 Order Engine 정책대로 merge한다.
- GIVEN 단일 온도 또는 온도 없는 Cart line, WHEN ORDER_REVIEW를 렌더링하면, THEN 온도 선택 UI를 표시하지 않는다.
- GIVEN 명확한 화면 명령, WHEN STT transcript를 routing하면, THEN 현재 screen에 허용된 UI action을 touch와 같은 handler로 실행하며 그 외 발화는 주문 NLU로 전달한다.
- GIVEN Touch mode, WHEN 응답 TTS가 끝나면, THEN 자동 Listening을 시작하지 않고 microphone CTA를 누른 경우에만 Voice mode로 복귀한다.
- GIVEN Cart가 있는 상태, WHEN 처음으로를 누르면, THEN reset 전에 취소 확인 UI를 표시한다.
- GIVEN 음성 허용 화면에서 마이크 활성화, WHEN Voice Overlay가 열리면, THEN 하단 5버튼 Footer와 동일한 bounding box에 50% 반투명(`rgba(255,255,255,0.50)`, blur 없음)으로 표시되고 상단 정보(듣고 있어요/waveform)와 하단 1×2 수평 버튼(말하기 끝내기/화면으로 조작하기)으로 구성되며 뒷단 5버튼 클릭을 차단하고 본문 레이아웃 시프트(0.00px)가 발생하지 않는다.
