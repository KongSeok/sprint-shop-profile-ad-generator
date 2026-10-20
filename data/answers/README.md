# Few-shot 데이터 준비

정답은 `data/samples/answer_profiles_gold.jsonl` 하나에서 관리합니다. train과 eval을 포함한 30개 정답을 보관하며, few-shot 로더는 train 5개만 선택합니다.
`fewshot_profiles.example.jsonl`은 형식 설명용 가짜 자리표시 값이며 로더가 읽지 않습니다. 그대로 정답으로 사용하지 마세요.

- `data/samples/shop_texts.jsonl`: 한 줄에 `{"id": 1, "text": "사장님 소개 글 원문"}` 형식입니다.
- `data/samples/split.json`: `{"train": [1, 7, 13, 19, 25], "eval": [평가용 정수 ID들]}` 구조입니다. 대괄호 안 설명 대신 실제 정수들을 작성합니다.
- `data/samples/answer_profiles_gold.jsonl`: 한 줄에 `{"id": 1, "profile": {...}}` 구조입니다. `other_info`에는 다른 칸에 안 맞는 사실을 원문 그대로 기록하고, 없으면 `null`로 둡니다.

원문과 split은 제공된 실제 데이터로 준비해 주세요. train/eval 분할이나 정답은 자동 생성하지 않습니다.
로더는 ID로 원문과 답안을 결합합니다. gold의 eval 답안은 무시합니다. split에서 train/eval이 겹치거나, train 답안이 중복되거나, 5개 중 하나라도 빠지면 v2를 호출하지 않습니다.
답안이 없거나 비어 있어도 v1은 사용할 수 있습니다. 평가/채점 코드는 포함하지 않습니다.
