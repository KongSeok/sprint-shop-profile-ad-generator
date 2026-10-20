# Few-shot 데이터 준비

`fewshot_profiles.jsonl`은 사장님 글을 보고 사람이 직접 채우는 답안 파일입니다. 현재는 비워 두었습니다.
`fewshot_profiles.example.jsonl`은 형식 설명용 가짜 자리표시 값이며 로더가 읽지 않습니다. 그대로 정답으로 사용하지 마세요.

- `data/samples/shop_texts.jsonl`: 한 줄에 `{"id": 1, "text": "사장님 소개 글 원문"}` 형식입니다.
- `data/split.json`: `{"train": [1, 7, 13, 19, 25], "eval": [평가용 정수 ID들]}` 구조입니다. 대괄호 안 설명 대신 실제 정수들을 작성합니다.
- `data/answers/fewshot_profiles.jsonl`: 한 줄에 `{"id": 1, "profile": {...}}` 구조로, 지정한 train ID 5개만 작성합니다. 모든 필드를 명시하고, 글에 없는 값은 `null`로 둡니다.

원문과 split은 제공된 실제 데이터로 준비해 주세요. train/eval 분할이나 정답은 자동 생성하지 않습니다.
로더는 ID로 원문과 답안을 결합합니다. eval ID가 train과 겹치거나, 답안에 train 이외 ID가 있거나, 5개 중 하나라도 빠지면 v2를 호출하지 않습니다.
답안이 없거나 비어 있어도 v1은 사용할 수 있습니다. 평가/채점 코드는 포함하지 않습니다.
