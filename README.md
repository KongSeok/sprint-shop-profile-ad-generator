# sprint-shop-profile-ad-generator

광고 문구 생성: 화면의 **문구 만들기** 탭에서 저장된 가게와 메뉴명·가격·특징·이번만 요청을 입력합니다. `POST /copy/generate`는 `shop_id` 또는 `profile` 중 하나와 `menu`를 받습니다. 사진은 받지 않습니다.
프로필 추출과 동일한 Gemini 모델·대기 시간·medium thinking을 사용하며 문구 생성 temperature는 0.7입니다. 서버는 자동 재시도하지 않습니다. 결과는 인스타그램(3~6줄, 해시태그 5~10개), 배달앱(1~2문장, 80자 이내), 네이버 플레이스(3~5문장)와 코드가 검사한 피할 표현 경고입니다. 사실·말투·문장 수 규칙은 `app/prompts/copy_v1.txt`에 분리되어 있습니다.

확인용 샘플은 `python -m tools.copy_samples --ids 2,8,14,20,22`로 생성합니다. `data/copy_runs/copy_v1.jsonl`에 입력·출력을 저장하며 이미 있는 ID는 건너뛰고, 호출은 6초 간격, 실패 시 중단합니다. 샘플 결과의 사실 오류·피할 표현·꾸밈말 부풀림은 실제 게시 전에 직접 검토합니다.
`sprint-copy` worktree에서 실행할 때도 해당 폴더의 `.env`를 설정하고 Python 의존성을 준비해야 합니다. 원래 체크아웃의 키나 DB는 자동 복사하지 않습니다. 원래 서버와 동시에 띄우려면 FastAPI는 `--port 8001`, Streamlit은 `--server.port 8502`를 쓰고 이 worktree의 `API_BASE_URL=http://localhost:8001`로 맞추세요.

확인·저장 화면 실행 (레포 폴더의 가상환경에서, 터미널 두 개):

```powershell
uvicorn app.api.main:app --reload
streamlit run app/ui/main_ui.py
```

소개 글 정리 → 프로필 수정 → 저장 순서로 사용합니다. 이름·업종은 저장할 때 필수이며, 사이드바에서 불러온 가게는 같은 저장 번호로 수정합니다. 입력값은 Streamlit 세션의 rerun 동안 유지됩니다(브라우저 탭을 닫거나 세션이 새로 생기는 경우에는 저장된 가게를 다시 불러오세요).
프로필은 FastAPI를 통해 SQLite에 저장되며 화면은 DB를 직접 읽지 않습니다. `SHOP_DB_PATH` 기본값은 `data/shops/shops.db`이고 서버 시작 시 테이블을 생성합니다. DB와 저널 파일은 Git에서 제외합니다.

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

프로필 추출은 v1·v2 모두 thinking을 `medium`으로 고정합니다. Gemini 대기 시간은 `GEMINI_TIMEOUT_MS` 환경변수(밀리초, 기본 `300000` = 300초)로 설정합니다. Streamlit의 정리하기 요청은 이 값보다 20초 길게 기다립니다(기본 320초). 환경변수를 바꾸면 API와 Streamlit을 모두 재시작하세요. `feat/eval-score`의 진단용 `tools/gemini_check.py`의 120초·low 비교 설정은 그대로 유지합니다.

### 표현 컨셉 (선택)
확인 화면에서 분위기·말투가 모두 비어 있을 때 `컨셉 추천받기`로 후보 3개를 고르거나 직접 적습니다.
추천 실패나 미선택 상태에서도 가게 저장이 가능합니다. 고친 후보는 `source=직접`으로 저장합니다.
`POST /profile/suggest-concept`는 shop_id 또는 profile 중 하나를 받습니다. 기존 분위기·말투가 있으면 409입니다.
`/profile/save`와 조회 응답의 concept는 프로필 밖의 선택값이며, 기존 DB는 서버 시작 시 concept_json 열을 추가합니다.
문구는 원래 프로필 분위기·말투를 우선하며, 둘 다 없을 때만 컨셉을 표현 참고로 사용합니다.
concept.theme은 저장만 하고 렌더러 테마 적용은 후속 병합에서 진행합니다.

### 문구 모드와 1회 교정
가게 프로필을 저장한 뒤 문구 탭에서 가게를 선택합니다. `[가게 소개 문구]`는 메뉴 없이,
`[메뉴 문구]`는 프로필 메뉴 드롭다운 또는 새 메뉴 이름·가격·특징·이번 요청으로 생성합니다.

`POST /copy/generate`는 `mode`를 반드시 받습니다. shop은 저장된 shop_id만, menu는 shop_id 또는 profile 중 하나와 menu를 받습니다.
- shop 요청: `{"mode":"shop","shop_id":1}`. 응답은 instagram, delivery_app.shop_intro(80~150자·2~3문장), naver_place(120~220자).
- menu 요청: `{"mode":"menu","shop_id":1,"menu":{"name":"라떼","price":"4000원","features":null,"this_time":null}}`. 응답은 instagram, delivery_app.menu_description(50~90자·2문장). 플레이스는 출력하지 않습니다.
- 인스타 150~600자, 태그 5~15개. `use_examples=false`로 예시 생략 가능.
- 예시는 `short-v1`, `full-v2`, `full-v3`(기본)로 구분. full-v3는 모드별 style 우선순위로 full 2편+short 1개를 코드에서 선택합니다. shop 배달앱은 Place 예시, menu 배달앱은 delivery_app 예시를 사용합니다.

`python -m tools.copy_samples --version v2 --mode menu --example-version full-v3 --seed 42 --ids 2,8,14`
shop은 `--mode shop`. CLI 기본 모드는 menu로 기존 메뉴 비교 흐름을 유지합니다. 결과 파일은 예시 버전·seed·모드별로 구분되며 선택 ID와 regeneration 기록을 저장합니다.

생성 후 금지 표현·어절 반복·글자 수·식별 가능한 인스타 사실 수·편집 메모·이상한 이모지 꼬리·모드 형식을 검사합니다.
위반 시 같은 입력/예시로 교정 1회만 호출합니다. 두 번째도 위반이면 구조를 읽을 수 있는 후보 중 검사 위반 수가 적은 쪽(동률이면 첫 번째)을 반환하고 warnings에 남깁니다.
둘 다 JSON 구조를 읽을 수 없으면 502. 429/503/504 등 네트워크 오류를 이유로 자동 재시도하지 않습니다.
`regeneration`에 수행 여부·첫/교정 위반 목록·선택 시도 번호를 반환합니다. 사실 수와 반복 판정은 휴리스틱이며 의미 전체의 정확성을 보장하지 않습니다.
문구 UI 대기 시간은 최대 두 호출을 감안해 `GEMINI_TIMEOUT_MS * 2 / 1000 + 20`(기본 620초)입니다. 프로필 추출 대기 시간은 기존 그대로입니다.

### 오프라인 PNG 렌더링
`pip install -r requirements.txt` 다음 `playwright install chromium`을 한 번 실행합니다.
`python -m tools.render_samples --ids 2,8,14,20,22`로 임시 광고 카드를 확인합니다.
기존 Chromium 계열 브라우저를 쓰려면 `RENDER_BROWSER_EXECUTABLE`에 실행 파일 경로를 지정합니다.
폰트와 템플릿은 로컬 파일을 사용하며 렌더 중 외부 네트워크 요청은 차단합니다.
새 템플릿은 templates/ad_card/<이름>/ 안에 template.html, style.css, meta.json을 넣습니다.
필수 칸 shop_name, menu_name, price, headline, body, photo_url과 CSS 변수를 유지합니다.
POST /render/ad-card는 png_base64와 warnings를 반환합니다.

`python -m tools.render_samples --kind menu_board --ids 4,9,14,24`로 메뉴판을 확인합니다.
POST /render/menu-board: shop_id 또는 profile, 선택 menus(name/price/note), template, theme. 메뉴는 최대 12개입니다.
