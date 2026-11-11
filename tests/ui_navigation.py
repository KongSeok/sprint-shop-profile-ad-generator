from streamlit.util import calc_hash


def navigate(view, url_path):
    # AppTest.switch_page accepts file paths only. Callable pages use URL hashes.
    view._page_hash = calc_hash(url_path)
    return view.run()
