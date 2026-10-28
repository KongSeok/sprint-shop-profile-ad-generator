# 광고 문구 예시 (copy v2 few-shot)

- examples.jsonl: 785줄, 우석님이 고른 실제 광고 문구. channel = instagram 574 / naver_place 100 / delivery_app 111
- 필드: id, channel, business_type, text, account, source, source_kind, orig_id
- business_type: 고깃집, 빵집, 카페, 한식, 일식, 디저트, 분식, 술집, 양식, 중식
- 가게 이름 [가게], 가격 [가격], 동네 [동네]로 바꿈 (자동 치환이라 일부 남아 있을 수 있음)
- 프롬프트에는 text만 넣음. account, source는 출처 기록용
- 뺀 것: 후기·공동게시물 27, 협찬 3, 블로그 메뉴 요약 100, 네이버 블로그 제목 599
