"""
어제의 일별 박스오피스를 보여 주는 스트림릿 앱.

- 데이터 출처: 영화진흥위원회(KOBIS) 오픈 API - 일별 박스오피스
- 배포: 스트림릿 클라우드 (인증키는 앱 설정의 Secrets에 KOBIS_KEY 로 저장)
"""

# ── 1. 필요한 도구(라이브러리) 불러오기 ────────────────────────────────
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo  # 파이썬 3.9+ 에 기본 내장된 시간대 도구

import pandas as pd      # 표(테이블)를 다루는 도구
import requests          # 인터넷으로 데이터를 요청하는 도구
import streamlit as st   # 화면(웹 앱)을 만드는 도구


# ── 2. 고정값 ──────────────────────────────────────────────────────────
# KOBIS 공식 문서의 요청 주소
API_URL = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/"
    "searchDailyBoxOfficeList.json"
)

# 한국 시간대(KST). 배포 서버 시계가 한국 시간이 아니어도 이걸 쓰면 안전하다.
KST = ZoneInfo("Asia/Seoul")


class KobisError(Exception):
    """API에서 문제가 생겼을 때 쓰는 우리만의 오류 종류.

    이 오류가 나면 화면에 한국어 안내문을 대신 보여 준다.
    (주의: 오류가 나면 아래 캐시에 저장되지 않으므로, 다음에 다시 시도된다.)
    """


# ── 3. '어제' 날짜 계산 ────────────────────────────────────────────────
def get_yesterday_kst() -> date:
    """한국 시간 기준으로 '어제' 날짜를 돌려준다.

    오늘 자료는 아직 집계 전이라 어제 날짜로 조회한다.
    서버가 미국이든 유럽이든, 항상 한국 시간을 기준으로 계산한다.
    """
    now_in_korea = datetime.now(KST)          # 지금 한국은 몇 시인가
    return (now_in_korea - timedelta(days=1)).date()  # 하루 전 날짜


# ── 4. API 호출 (같은 날짜는 1시간 동안 기억해 두기) ───────────────────
# @st.cache_data 는 "같은 값으로 다시 부르면 실제로 부르지 말고
# 저장해 둔 결과를 그대로 써라" 라는 뜻이다. ttl=3600 은 3600초(=1시간).
@st.cache_data(ttl=3600, show_spinner="박스오피스 자료를 불러오는 중입니다...")
def fetch_box_office(target_dt: str) -> list[dict]:
    """target_dt(예: '20260916') 날짜의 박스오피스 목록을 가져온다.

    성공하면 영화 정보가 담긴 목록(list)을 돌려주고,
    문제가 있으면 KobisError 를 일으킨다.
    """

    # (1) 비밀 금고에서 인증키 꺼내기 — 코드에는 절대 키를 적지 않는다.
    try:
        api_key = st.secrets["KOBIS_KEY"]
    except Exception:  # 금고가 없거나 KOBIS_KEY 항목이 없을 때
        raise KobisError(
            "인증키를 찾지 못했습니다.\n\n"
            "스트림릿 클라우드에서 앱 메뉴의 **Settings → Secrets** 에 아래처럼 "
            "한 줄을 넣고 저장해 주세요.\n\n"
            '```toml\nKOBIS_KEY = "발급받은_인증키"\n```\n\n'
            "내 컴퓨터에서 실행 중이라면 `.streamlit/secrets.toml` 파일에 "
            "같은 내용을 적으면 됩니다."
        )

    # (2) 실제로 요청 보내기
    try:
        response = requests.get(
            API_URL,
            params={"key": api_key, "targetDt": target_dt},
            timeout=10,  # 10초 안에 응답이 없으면 포기
        )
        response.raise_for_status()  # 404, 500 같은 상태코드면 여기서 오류
        data = response.json()       # 받은 글자를 파이썬 자료로 바꾸기
    except requests.exceptions.Timeout:
        raise KobisError(
            "KOBIS 서버가 10초 안에 응답하지 않았습니다.\n\n"
            "잠시 뒤 다시 시도해 보시고, 계속 같으면 KOBIS 서버 점검 여부를 "
            "확인해 주세요."
        )
    except requests.exceptions.RequestException:
        raise KobisError(
            "KOBIS 서버에 연결하지 못했습니다.\n\n"
            "인터넷 연결 상태와 요청 주소가 올바른지 확인해 주세요."
        )
    except ValueError:  # JSON 모양이 아닐 때
        raise KobisError(
            "응답을 읽지 못했습니다. 받은 내용이 정상적인 JSON 형식이 아닙니다.\n\n"
            "요청 주소가 올바른지, KOBIS 서버에 일시적인 문제가 없는지 확인해 주세요."
        )

    # (3) 인증키가 틀려도 상태코드는 200이고, 대신 faultInfo 상자가 온다.
    if "faultInfo" in data:
        fault = data.get("faultInfo", {})
        message = fault.get("message", "알 수 없는 오류")
        code = fault.get("errorCode", "-")
        raise KobisError(
            f"KOBIS가 오류를 보냈습니다. (코드 {code}: {message})\n\n"
            "확인할 점\n"
            "- 인증키가 올바른지, 앞뒤에 빈칸이나 따옴표가 섞이지 않았는지\n"
            "- 인증키가 만료되거나 일일 호출 한도를 넘지 않았는지\n"
            "- 조회 날짜가 여덟 자리(yyyymmdd) 형식인지"
        )

    # (4) 영화 목록 꺼내기
    movies = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
    if not movies:
        raise KobisError(
            f"{target_dt} 날짜의 박스오피스 자료가 비어 있습니다.\n\n"
            "확인할 점\n"
            "- 해당 날짜의 집계가 아직 끝나지 않았을 수 있습니다 "
            "(보통 다음 날 오전에 공개됩니다)\n"
            "- 너무 예전 날짜이거나 아직 오지 않은 날짜는 아닌지\n"
            "- 잠시 뒤 다시 시도해 보세요"
        )

    return movies


# ── 5. 받은 자료를 표로 정리하기 ───────────────────────────────────────
def to_dataframe(movies: list[dict]) -> pd.DataFrame:
    """API가 준 목록을 표로 바꾸고, 글자로 온 숫자를 진짜 숫자로 바꾼다."""
    df = pd.DataFrame(movies)

    # KOBIS는 숫자도 전부 글자("1", "12345")로 보내 준다.
    # 정렬과 그래프에 쓰려면 숫자로 바꿔 줘야 한다.
    number_columns = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for column in number_columns:
        if column in df.columns:
            # errors="coerce": 숫자로 못 바꾸는 값은 빈 값으로 처리
            df[column] = pd.to_numeric(df[column], errors="coerce")

    # 순위 순서대로 정렬
    df = df.sort_values("rank").reset_index(drop=True)
    return df


def format_number(value) -> str:
    """12345 -> '12,345명' 처럼 읽기 좋게 바꾼다."""
    if pd.isna(value):
        return "-"
    return f"{int(value):,}"


# ── 6. 화면 그리기 ─────────────────────────────────────────────────────
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

st.title("🎬 어제의 박스오피스")

# 어제 날짜 계산 (한국 시간 기준)
yesterday = get_yesterday_kst()
target_dt = yesterday.strftime("%Y%m%d")  # API가 원하는 여덟 자리 형식

st.caption(
    f"기준일: {yesterday.strftime('%Y년 %m월 %d일')} "
    f"(한국 시간 기준 어제) · 자료 출처: 영화진흥위원회 KOBIS"
)

# 자료 불러오기 — 문제가 생기면 안내문을 보여 주고 앱을 여기서 멈춘다.
try:
    movies = fetch_box_office(target_dt)
    df = to_dataframe(movies)
except KobisError as error:
    st.error(str(error))
    st.stop()  # 아래 내용은 그리지 않고 끝낸다

# ── 6-1. 1위 영화: 지표 카드 세 장 ────────────────────────────────────
top_movie = df.iloc[0]  # 표의 첫 번째 줄 = 1위

st.subheader(f"🥇 1위 · {top_movie['movieNm']}")

col1, col2, col3 = st.columns(3)  # 화면을 세 칸으로 나누기
col1.metric("어제 관객수", f"{format_number(top_movie['audiCnt'])}명")
col2.metric("누적 관객수", f"{format_number(top_movie['audiAcc'])}명")
col3.metric("스크린수", f"{format_number(top_movie['scrnCnt'])}개")

st.divider()

# ── 6-2. 관객수 상위 5편 막대그래프 ───────────────────────────────────
st.subheader("📊 관객수 상위 5편")

top5 = df.nlargest(5, "audiCnt")  # 관객수가 많은 순으로 5편

# 막대그래프: 가로축은 영화 이름, 세로축은 관객수
chart_data = top5.set_index("movieNm")[["audiCnt"]]
chart_data.columns = ["관객수"]
st.bar_chart(chart_data)

st.divider()

# ── 6-3. 전체 순위 표 ─────────────────────────────────────────────────
st.subheader("📋 전체 순위")

# 보여 줄 칸만 골라서 한국어 이름을 붙인다.
table = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]

st.dataframe(
    table,
    hide_index=True,          # 왼쪽 번호(0,1,2...) 숨기기
    use_container_width=True,  # 화면 너비에 맞추기
    column_config={
        # 숫자 칸은 1,234 형태로 보여 준다
        "관객수": st.column_config.NumberColumn(format="%,d"),
        "누적관객": st.column_config.NumberColumn(format="%,d"),
        "스크린수": st.column_config.NumberColumn(format="%,d"),
    },
)

# ── 6-4. 새로고침 버튼 ────────────────────────────────────────────────
# 저장해 둔(캐시된) 자료를 지우고 다시 불러오고 싶을 때 쓴다.
if st.button("🔄 자료 새로 불러오기"):
    fetch_box_office.clear()  # 기억해 둔 결과 지우기
    st.rerun()                # 앱을 처음부터 다시 실행
