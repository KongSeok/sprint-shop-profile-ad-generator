# 채점 기준

`run_extract.py`만 네트워크를 사용합니다. `score.py`는 저장 파일과 정답/원문/split만 읽고, LLM SDK를 import하지 않습니다.

- `normalize`: NFKC, 소문자, 공백 제거, Unicode 문장부호(P)와 기호(S) 제거. 숫자는 쉼표를 제거한 뒤 순서대로 숫자 덩어리를 추출합니다.
- bigram은 정규화한 글자의 2글자 집합입니다. 1글자 값은 그 글자 하나를 집합으로 사용합니다. 자유 글은 Dice ≥ 0.5와 정답 숫자(중복 개수 포함) 보존을 함께 검사합니다.
- 목록·조각은 점수가 높은 순서대로 1:1 매칭하고 동점은 정답/예측 입력 순서로 결정합니다. 메뉴 이름은 포함 관계를 허용하며, 가격은 매칭된 메뉴 안에서 숫자 목록이 완전히 같아야 hit입니다.
- 남는 예측은 원문 근거가 있으면 extra, 없으면 invented입니다. 가격의 원문 근거는 엄격 칸과 같이 정규화한 문자열 포함으로 검사합니다. 자유 글 근거는 bigram 포함 비율 ≥ 0.6과 숫자 보존입니다.
- facts CSV의 `menus.name`/`menus.price`는 각각 메뉴 이름/가격입니다. hit의 score는 짝의 Dice 또는 exact 점수, miss는 0, extra/invented는 원문 근거 점수입니다. 숫자 조건 때문에 점수가 높아도 invented가 될 수 있습니다.
- summary의 `recall_menus`는 메뉴 이름·가격을 합친 recall입니다. gold 사실이 없는 칸과 정답 충돌이 없는 집합의 비율은 빈칸입니다. 사실이 전혀 없는 개별 프로필의 recall은 1로 정의합니다.
- needs_check는 사실 개수에서 빼고 존재 여부만 별도 검사합니다. `conflict_hit_rate` 분모는 채점 대상 중 정답 needs_check가 있는 ID 수입니다.
- `--allow-missing`에서 채점할 ID가 하나도 없으면 n_scored=0, n_missing은 전체 eval 수로 기록하고 recall과 ID당 비율은 빈칸으로 둡니다.
- 누락은 기본 오류이며 `--allow-missing`일 때만 제외합니다. 서로 다른 모델/프롬프트 해시가 섞인 실행은 합산하지 않습니다. `gold`는 자기검증 예약 이름이며 모델 호출 없이 정답 자체를 채점합니다.
- 동일 run_name의 summary 행은 교체합니다. CSV는 UTF-8 BOM이며, 호출/채점 출력 폴더는 Git 추적 대상입니다.

이 점수는 위 문자열 규칙에 따른 결정적 비교 결과이며, 의미를 판정하는 LLM 평가가 아닙니다.
