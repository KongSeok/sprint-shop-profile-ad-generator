# sprint-shop-profile-ad-generator

Python 3.11 / Windows PowerShell 기준. 레포 폴더에서 실행합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
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
