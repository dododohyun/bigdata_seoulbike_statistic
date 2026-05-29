"""
api_config.py 템플릿 (공개용 — 실제 인증키 없음).

사용법:
  1) 이 파일을 api_config.py 로 복사한다.
       (PowerShell)  Copy-Item api_config.example.py api_config.py
  2) 아래 인증키 자리에 본인의 키를 입력한다.
  3) api_config.py 는 .gitignore 에 등록되어 있어 GitHub 에 올라가지 않는다.
"""
import requests
import pandas as pd

# ---------------------------------------------------------------------------
# 인증키 (← 본인 키로 교체)
# ---------------------------------------------------------------------------
# 서울 열린데이터광장 (대여소 정보 OpenAPI) 발급: https://data.seoul.go.kr
SEOUL_API_KEY = "YOUR_SEOUL_OPENAPI_KEY"
SEOUL_STATION_SERVICE = "tbCycleStationInfo"

# 공공데이터포털 한국천문연구원_특일 정보(공휴일) 발급: https://www.data.go.kr/data/15051891/openapi.do
HOLIDAY_API_KEY = "YOUR_DATA_GO_KR_SERVICE_KEY"
HOLIDAY_API_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"


def fetch_station_info(api_key=SEOUL_API_KEY, page_size=1000):
    """서울 OpenAPI(tbCycleStationInfo) 전체 페이지를 받아 영문 컬럼 DataFrame으로 반환."""
    url0 = f"http://openapi.seoul.go.kr:8088/{api_key}/json/{SEOUL_STATION_SERVICE}/1/1/"
    total = int(requests.get(url0, timeout=20).json()["stationInfo"]["list_total_count"])
    rows = []
    for start in range(1, total + 1, page_size):
        end = min(start + page_size - 1, total)
        url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/{SEOUL_STATION_SERVICE}/{start}/{end}/"
        rows.extend(requests.get(url, timeout=30).json()["stationInfo"]["row"])
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "RENT_ID": "station_id", "RENT_NO": "station_no", "RENT_NM": "station_name",
        "STA_LOC": "district", "HOLD_NUM": "rack_count",
        "STA_LAT": "latitude", "STA_LONG": "longitude",
    })[["station_id", "station_no", "station_name", "district",
        "rack_count", "latitude", "longitude"]]
    for c in ["rack_count", "latitude", "longitude"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_holidays(year, api_key=HOLIDAY_API_KEY):
    """공공데이터포털 특일정보 API로 해당 연도 공휴일 날짜 set 반환."""
    import datetime as _dt
    dates = set()
    for month in range(1, 13):
        params = {"serviceKey": api_key, "solYear": str(year),
                  "solMonth": f"{month:02d}", "_type": "json", "numOfRows": "50"}
        r = requests.get(HOLIDAY_API_URL, params=params, timeout=20)
        r.raise_for_status()
        items = r.json()["response"]["body"]["items"]
        if not items:
            continue
        rows = items["item"]
        rows = rows if isinstance(rows, list) else [rows]
        for it in rows:
            if str(it.get("isHoliday", "Y")) == "Y":
                d = str(it["locdate"])
                dates.add(_dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])))
    return dates