# 광고 문구 예시 (copy v2 few-shot)

- examples.jsonl: 1,076줄. 사용자 제공 `통예시글 (생성)/examples.jsonl`을 그대로 복사.
- instagram: full 291편 + short 574개 / naver_place 100 / delivery_app 111.
- full에는 생성 예시도 포함되며 `style` 필드로 구성·말투를 구분한다. style 없는 full 1편은 full-v2 선택에서 제외한다.
- 필드: id, channel, business_type, text, account, source, source_kind, orig_id
- business_type: 고깃집, 빵집, 카페, 한식, 일식, 디저트, 분식, 술집, 양식, 중식
- 가게 이름 [가게], 가격 [가격], 동네 [동네]로 바꿈 (자동 치환이라 일부 남아 있을 수 있음)
- 프롬프트에는 text만 넣음. account, source는 출처 기록용
- 예시 선택 버전 (`prompt_version`과 별도):
  - `short-v1`: 기존 방식. 인스타 short 최대 3개, 같은 업종 우선 후 다른 업종 보충.
  - `full-v2` (copy v2 기본): 인스타 full 2편(서로 다른 style, 같은 업종 우선) + 같은 업종 short 1개. 같은 업종 short가 없으면 생략.
  - 배달앱·플레이스는 두 버전 모두 기존 방식과 동일한 예시를 선택한다.
  - API: `example_version`에 `short-v1` 또는 `full-v2`. `use_examples=false`면 예시 생략.
  - CLI: `python -m tools.copy_samples --version v2 --example-version full-v2 --ids 2`
  - 결과는 `copy_v2_full_v2.jsonl` / `copy_v2_short_v1.jsonl`로 구분. 예시 없는 결과는 기존 `copy_v2_noex.jsonl` 유지.
  - full은 "흐름·말투 참고 (문장 그대로 쓰지 말 것)", short는 "짧은 표현 참고"로 프롬프트에 구분한다.
- 뺀 것: 후기·공동게시물 27, 협찬 3, 블로그 메뉴 요약 100, 네이버 블로그 제목 599
