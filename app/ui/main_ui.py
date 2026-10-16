import sys
from pathlib import Path

import requests
import streamlit as st

# Allow running this script directly through the Streamlit CLI.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.config import API_BASE_URL

st.title("광고 콘텐츠 생성 서비스")

try:
    response = requests.get(f"{API_BASE_URL.rstrip('/')}/health", timeout=5)
    response.raise_for_status()
    if response.json().get("status") == "ok":
        st.success("모델 서버 정상 연결")
    else:
        st.warning("모델 서버 상태 응답을 확인해 주세요.")
except (requests.RequestException, ValueError):
    st.error("모델 서버에 연결할 수 없습니다.")
