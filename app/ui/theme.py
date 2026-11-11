import streamlit as st


def render_theme():
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { background: #F3ECE0; }
        .shop-app-name { color: #2B2420; font-size: 1.4rem; font-weight: 700; line-height: 1.3; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] { border-radius: 8px; }
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover { background: #FBF7F0; }
        [class*="st-key-nav_"][class*="_current"] [data-testid="stPageLink-NavLink"] {
            background: #C8553D; color: white;
        }
        [class*="st-key-nav_"][class*="_current"] [data-testid="stPageLink-NavLink"] p { color: white; }
        [class*="st-key-card_"], [class*="st-key-candidate_"] {
            background: #FFFDF9; border: 1px solid #EADFCC; border-radius: 12px;
            box-shadow: 0 2px 8px rgba(43, 36, 32, 0.06);
        }
        [class*="st-key-candidate_"][class*="_selected"] {
            outline: 2px solid #C8553D; border-radius: 12px;
        }
        .design-title { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .design-selected { color: #9E3F2C; font-weight: 700; }
        [class*="st-key-candidate_"][class*="_selected"] [data-testid="stButton"] { display: none; }
        [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
        [data-testid="stCode"], [data-testid="stCode"] pre { height: auto !important; min-height: 0 !important; }
        [data-testid="stCode"] pre, [data-testid="stCode"] code, [data-testid="stCode"] code span {
            font-family: "Noto Sans KR", sans-serif !important; font-size: 15px !important; line-height: 1.7 !important;
        }
        .design-reason {
            color: #6E6059; font-size: 0.8rem; display: -webkit-box;
            -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden;
        }
        .palette-dot {
            display: inline-block; width: 16px; height: 16px; margin: 0 3px;
            border: 1px solid #2B2420; border-radius: 50%;
        }
        [data-testid="stMainBlockContainer"] { max-width: 1200px; padding-top: 3.25rem; }
        [data-testid="stMainMenu"], [data-testid="stAppDeployButton"] { display: none; }
        .stButton button, .stDownloadButton button { border-radius: 8px; }
        h1, h2, h3 { font-weight: 700; }
        @media (max-width: 760px) {
            [data-testid="stMainBlockContainer"] { padding-inline: 1rem; }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(2):last-child) {
                flex-wrap: wrap;
            }
            [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(2):last-child)
                > [data-testid="stColumn"] { flex-basis: 100%; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
