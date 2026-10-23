# sprint-shop-profile-ad-generator

Python 3.11 / Windows PowerShell 기준. 레포 폴더에서 실행합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env에 GEMINI_API_KEY를 설정합니다. 기본 GEMINI_MODEL은 gemini-3.8-flash입니다.
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

다른 PowerShell에서 레포 폴더로 이동한 뒤 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app/ui/main_ui.py
```

테스트:

```powershell
python -m pytest
```

프로필 추출: `POST /profile/extract`, 요청은 `text`와 `prompt_version`(`v1`/`v2`, 기본 `v2`)입니다. 누락된 정보는 `null`이며, 추출 단계에서는 가게 이름·업종을 강제 입력하지 않습니다.

PowerShell 호출 예시 (curl.exe, 데이터 없이 쓸 수 있는 v1):

```powershell
curl.exe --json '{"text":"카페입니다. 평일 오전 10시부터 오후 6시까지 열어요.","prompt_version":"v1"}' http://localhost:8000/profile/extract
```

v1은 규칙만, v2는 규칙과 train ID `1, 7, 13, 19, 25`의 예시 5개를 사용합니다. 원문은 `data/samples/shop_texts.jsonl`, 분할은 `data/samples/split.json`, 정답은 `data/samples/answer_profiles_gold.jsonl`에서 읽습니다. gold에는 30개 정답을 함께 보관하고, 로더는 train 5개만 선택하며 나머지 eval 답안은 무시합니다. 파일이 없거나 비어 있으면 `503 FEWSHOT_NOT_READY`를 반환합니다. 형식은 [데이터 안내](data/answers/README.md)를 참고하세요.

`other_info`에는 원산지·예약·좌석·사진 요청 등 다른 칸에 안 맞는 사실을 원문 그대로 담습니다. 업종은 직접 적혀 있지 않아도 메뉴로 분명할 때만 판단하고, 애매하면 `null`로 둡니다. 가게 이름은 지어내지 않습니다.

오류 응답은 `{"detail":{"code":"...","message":"원인"}}` 형식입니다. 키/데이터 누락은 503, Gemini 호출·응답 검증 실패는 502, 요청 형식 오류는 FastAPI 기본 422입니다. 테스트는 Gemini를 mock 처리하여 실제 API를 호출하지 않습니다.

기본 모델 ID와 무료 등급은 [공식 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)와 [요금표](https://ai.google.dev/gemini-api/docs/pricing)에서 확인했습니다. 무료 등급 적용과 쿼터는 AI Studio 프로젝트에서 확인하세요. 코드에서는 과금 등급을 바꾸거나 다른 모델로 자동 전환하지 않습니다.

평가 실행 순서:

1. `python -m eval.run_extract --version v1 --run-name v1` — eval 25개 호출·저장 (기본 간격 6초, `--ids 2,3`, `--force` 지원).
2. `python -m eval.score --run-name v1` — 저장 파일만 채점 (`--allow-missing` 허용, `--run-name gold`로 호출 없는 자기검증).
3. `eval/results/summary.csv` 확인 — 개별 판정은 `v1_facts.csv`, ID별 결과는 `v1_by_id.csv` 참고.

호출 결과는 `experiments/runs/{run_name}/{id}.json`에 원본·프로필·모델·시스템 프롬프트 SHA1과 함께 저장합니다. 같은 모델/해시의 성공 결과는 재사용하고, 실패 파일은 재시도합니다. 429/500/503/504는 30·60·120초 대기 후 최대 3번 재시도하고 중단하며, 같은 명령을 다시 실행하면 남은 결과만 호출합니다. 두 출력 폴더는 Git 추적 대상입니다. 자세한 판정·빈 분모 규칙은 [평가 안내](eval/README.md)를 참고하세요.
