import requests


class UserApiError(Exception):
    pass


def request_api(base_url: str, method: str, path: str, *, payload=None, timeout=10):
    try:
        response = requests.request(method, f"{base_url.rstrip('/')}{path}", json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise UserApiError("서버에 연결하지 못했어요. 잠시 후 다시 눌러 주세요") from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", {})
        except (ValueError, AttributeError):
            detail = {}
        code = detail.get("code") if isinstance(detail, dict) else None
        if code == "FEWSHOT_NOT_READY":
            message = "정리에 필요한 예시 데이터가 준비되지 않았어요. 관리자에게 알려 주세요"
        elif code == "GEMINI_KEY_MISSING":
            message = "서비스 연결 설정을 확인해야 해요. 관리자에게 알려 주세요"
        elif response.status_code == 422:
            message = ("가게 선택과 메뉴 이름을 확인해 주세요" if path == "/copy/generate"
                       else "가게 이름과 업종은 꼭 적어 주세요. 메뉴를 입력했다면 메뉴 이름도 확인해 주세요")
        elif response.status_code == 404:
            message = "저장된 가게를 찾지 못했어요. 목록을 새로 불러와 주세요"
        else:
            message = "지금은 처리하지 못했어요. 잠시 후 다시 눌러 주세요"
        raise UserApiError(message)
    try:
        return response.json()
    except ValueError as exc:
        raise UserApiError("응답을 읽지 못했어요. 잠시 후 다시 눌러 주세요") from exc
