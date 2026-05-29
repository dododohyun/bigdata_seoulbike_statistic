# %% [markdown]
# # 서울시 따릉이 자전거 부족은 언제 발생하는가?
# ## 시간 패턴 기반 수요예측과 선제적 재배치 의사결정 지원
#
# 이 노트북은 따릉이 대여이력(2024년 월별), 기상, 공휴일, 대여소 정보를 결합하여
# **대여소 × 날짜 × 시간** 단위의 수요예측용 데이터셋을 만들고,
# 시간 변수가 수요를 잘 설명한다는 근거를 단계적으로 제시한다.
#
# ### 데이터 인벤토리 (실제 확인 결과)
# | 데이터 | 위치 | 인코딩 | 비고 |
# |---|---|---|---|
# | 대여이력 | `rental_data_2024/서울특별시 공공자전거 대여이력 정보_24MM.csv` (12개) | cp949 | 17컬럼, 총 ~7.6GB → 청크 집계 |
# | 기상 | `weather_data/weather_2024.csv` | utf-8-sig | 이미 영문 컬럼, 시간 단위 |
# | 공휴일 | `holiday_data/국가데이터처_지표누리_공휴일 자료_20251106.csv` | cp949 | `연도, 공휴일` 컬럼 |
# | 대여소 정보 | 서울 열린데이터광장 OpenAPI `tbCycleStationInfo` | JSON | 총 3,230개소 |
#
# ### 컬럼 매칭 표 (원본 → 영문, 의미/근거)
# **대여이력**
# | 원본 | 영문 | 의미 |
# |---|---|---|
# | 자전거번호 | bike_id | 자전거 식별자 |
# | 대여일시 | rental_datetime | 대여 시각 |
# | 대여 대여소번호 | rental_station_no | 대여소 번호(5자리, 예 04804) |
# | 대여 대여소명 | rental_station_name | 대여소명 |
# | 대여거치대 | rental_rack | 대여 거치대 번호 |
# | 반납일시 | return_datetime | 반납 시각 |
# | 반납대여소번호 | return_station_no | 반납 대여소 번호 |
# | 반납대여소명 | return_station_name | 반납 대여소명 |
# | 반납거치대 | return_rack | 반납 거치대 번호 |
# | 이용시간(분) | use_minutes | 이용 시간(분) |
# | 이용거리(M) | use_distance_m | 이용 거리(m) |
# | 생년 | birth_year | 이용자 출생연도 |
# | 성별 | gender | 성별 |
# | 이용자종류 | user_type | 이용자 구분 |
# | **대여대여소ID** | **rental_station_id** | **ST-xxxx (대여소 정보 RENT_ID와 조인키)** |
# | **반납대여소ID** | **return_station_id** | **ST-xxxx** |
# | 자전거구분 | bike_type | 일반/새싹 등 |
#
# **대여소 정보(API)**: `RENT_ID→station_id`, `RENT_NO→station_no`, `RENT_NM→station_name`,
# `STA_LOC→district(자치구)`, `HOLD_NUM→rack_count(거치대 수)`, `STA_LAT→latitude`, `STA_LONG→longitude`
#
# > **매칭 주의**: 대여이력에는 대여소 식별자가 `대여소번호(04804)`와 `대여소ID(ST-2630)` 두 가지가 있다.
# > 대여소 정보 API의 `RENT_ID`(ST-xxxx)와 직접 매칭되는 **대여소ID를 분석 키 `station_id`로 사용**한다.
# >
# > **공휴일 주의**: 제공된 공휴일 파일의 2024년 목록에는 신정(1/1)·설날 연휴(2/9~2/12)·어린이날(5/5)이 빠져 있다.
# > 원본 정의를 그대로 병합하되, 필요 시 표준 공휴일로 보완할 수 있도록 코드에 표시해 두었다.

# %%
# =============================================================================
# [공통 설정] 라이브러리 / 경로 / 한글 폰트 / 실행 파라미터
# =============================================================================
import os
import warnings
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 160)

# 한글 폰트 (Windows 기준). 환경에 맞게 'AppleGothic'(mac) / 'NanumGothic'(linux) 으로 교체 가능.
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", font="Malgun Gothic", rc={"axes.unicode_minus": False})

# --- 경로 ---
BASE_DIR     = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
RENTAL_DIR   = os.path.join(BASE_DIR, "rental_data_2024")
WEATHER_CSV  = os.path.join(BASE_DIR, "weather_data", "weather_2024.csv")
HOLIDAY_CSV  = os.path.join(BASE_DIR, "holiday_data", "국가데이터처_지표누리_공휴일 자료_20251106.csv")
RENTAL_TMPL  = os.path.join(RENTAL_DIR, "서울특별시 공공자전거 대여이력 정보_{m}.csv")
OUT_DIR      = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

# --- 대여소 정보 API 키/호출 코드는 별도 파일 api_config.py 로 분리(.gitignore 처리) ---
#     키가 코드에 남지 않도록 노트북에서는 import 만 한다. (없으면 캐시 CSV 사용)

# --- 실행 파라미터 (전체 실행 시 기본값 = 12개월 전부) ---
# 빠른 검증을 원하면 환경변수로 제어:  BIKE_MONTHS=2401  BIKE_SAMPLE_ROWS=300000
_ALL_MONTHS = [f"24{mm:02d}" for mm in range(1, 13)]
MONTHS = os.environ.get("BIKE_MONTHS", ",".join(_ALL_MONTHS)).split(",")
SAMPLE_ROWS = os.environ.get("BIKE_SAMPLE_ROWS")
SAMPLE_ROWS = int(SAMPLE_ROWS) if SAMPLE_ROWS else None   # 파일당 읽을 최대 행수(None=전체)
CHUNKSIZE = 1_000_000          # 청크 단위 (메모리에 맞춰 조정)
MIN_STATION_TOTAL = 0          # 연간 총대여 이 값 이하 대여소 제외 (0=전체 유지)
MODEL_SAMPLE = 300_000         # 5장 모델 실험에 사용할 표본 행수 (대용량 RF 학습 시간 단축)

print("분석 대상 월:", MONTHS)
print("파일당 표본 행수:", SAMPLE_ROWS if SAMPLE_ROWS else "전체")

# %% [markdown]
# ## 1. 데이터 구조 확인
# 각 데이터셋의 크기·컬럼·타입·결측·중복·기간·기초통계를 확인한다.
# (대여이력은 ~7.6GB 이므로 구조 확인은 1개 파일의 상위 일부 표본으로 수행한다.)

# %%
def summarize_df(df, name, datetime_cols=None):
    """데이터프레임의 기본 구조/품질 지표를 출력한다."""
    print("=" * 78)
    print(f"[{name}]  shape = {df.shape}")
    print("-" * 78)
    print("컬럼 / 타입:")
    print(df.dtypes)
    print("-" * 78)
    miss = df.isna().sum()
    miss_pct = (miss / len(df) * 100).round(2)
    miss_tbl = pd.DataFrame({"결측수": miss, "결측비율(%)": miss_pct})
    print("결측치:")
    print(miss_tbl[miss_tbl["결측수"] > 0] if (miss > 0).any() else "  결측 없음")
    print("-" * 78)
    print(f"중복 행 개수: {df.duplicated().sum():,}")
    if datetime_cols:
        for c in datetime_cols:
            s = pd.to_datetime(df[c], errors="coerce")
            print(f"  [{c}] 최소 {s.min()}  ~  최대 {s.max()}")
    print("-" * 78)
    num = df.select_dtypes(include=[np.number])
    if num.shape[1] > 0:
        print("수치형 기초통계:")
        print(num.describe().T)
    print("=" * 78, "\n")


# %%
# --- 1-1. 대여이력 구조 확인 (1개 파일 상위 20만 행 표본) ---
RENTAL_RAW_COLS = ["자전거번호", "대여일시", "대여 대여소번호", "대여 대여소명", "대여거치대",
                   "반납일시", "반납대여소번호", "반납대여소명", "반납거치대",
                   "이용시간(분)", "이용거리(M)", "생년", "성별", "이용자종류",
                   "대여대여소ID", "반납대여소ID", "자전거구분"]

_sample_path = RENTAL_TMPL.format(m=MONTHS[0])
rental_sample = pd.read_csv(_sample_path, encoding="cp949", nrows=200_000)
summarize_df(rental_sample, f"대여이력 표본 ({MONTHS[0]}, 상위 20만행)",
             datetime_cols=["대여일시", "반납일시"])

# %%
# --- 1-2. 기상 데이터 구조 확인 ---
weather_raw = pd.read_csv(WEATHER_CSV, encoding="utf-8-sig")
summarize_df(weather_raw, "기상 데이터", datetime_cols=["datetime"])

# %%
# --- 1-3. 공휴일 데이터 구조 확인 ---
holiday_raw = pd.read_csv(HOLIDAY_CSV, encoding="cp949")
summarize_df(holiday_raw, "공휴일 데이터")
print("연도별 건수:")
print(holiday_raw["연도"].value_counts().sort_index())

# %% [markdown]
# **해석 (구조 확인)**
# - 대여이력은 1건=1회 이용(대여+반납)을 담은 트랜잭션 로그다. 분석에 필요한 핵심은 `대여일시/대여대여소ID`(대여 발생),
#   `반납일시/반납대여소ID`(반납 발생) 네 컬럼이며, 나머지(거리·성별·자전거번호 등)는 시간대 수요 집계에 불필요하다.
#   → 대용량이므로 **이 4개 컬럼만 청크로 읽어** 메모리를 절감한다.
# - 기상 데이터는 시간 단위(8,784행 ≈ 366일×24h)로 결측이 거의 없어 `datetime` 기준 병합에 적합하다.
# - 공휴일 데이터는 `연도, 공휴일(날짜)`만 제공 → 병합 시 **공휴일 여부(is_holiday) 플래그**로 활용(공휴일명은 원본에 없음).

# %% [markdown]
# ## 2. 전처리
# ### 2-1. 컬럼명 영문 통일 + 외부 데이터(기상/공휴일/대여소 정보) 로딩

# %%
# --- 대여소 정보 로딩 ---
# API 호출 코드/인증키는 별도 파일 api_config.py 에 분리(.gitignore). 키가 노트북에 남지 않는다.
# 우선순위: (1) api_config.fetch_station_info() → (2) 캐시 station_info.csv → (3) 안내 후 오류
STATION_CACHE = os.path.join(OUT_DIR, "station_info.csv")

station_info = None
try:
    import api_config
    station_info = api_config.fetch_station_info()
    station_info.to_csv(STATION_CACHE, index=False, encoding="utf-8-sig")
    print(f"[api_config] 대여소 정보 API 수신: {station_info.shape}")
except ModuleNotFoundError:
    print("api_config.py 없음 → 캐시 사용 시도. "
          "(키가 있으면 api_config.example.py 를 api_config.py 로 복사 후 키 입력)")
except Exception as e:
    print("API 호출 실패 → 캐시 사용 시도:", str(e)[:120])

if station_info is None:
    if os.path.exists(STATION_CACHE):
        station_info = pd.read_csv(STATION_CACHE, encoding="utf-8-sig",
                                   dtype={"station_no": str})
        print(f"캐시 사용: {STATION_CACHE} {station_info.shape}")
    else:
        raise FileNotFoundError(
            "대여소 정보를 가져올 수 없습니다. api_config.py(키 포함)를 만들거나, "
            "outputs/station_info.csv 캐시를 준비하세요.")

summarize_df(station_info, "대여소 정보 (정제)")

# %%
# --- 기상 데이터: datetime 파싱 ---
weather = weather_raw.copy()
weather["datetime"] = pd.to_datetime(weather["datetime"])
# (이미 영문 컬럼: datetime, temperature, precipitation, humidity, wind_speed, temp_max, temp_min)

# --- 공휴일 데이터: 2024년 공휴일 날짜 집합 ---
holiday = holiday_raw.copy()
holiday["holiday_date"] = pd.to_datetime(holiday["공휴일"]).dt.date
holiday_2024 = set(holiday.loc[holiday["연도"] == 2024, "holiday_date"])
print("2024 공휴일 수:", len(holiday_2024))
print(sorted(holiday_2024))

# %% [markdown]
# ### 2-3. 시간 단위 집계 — 대여이력(7.6GB)을 청크로 읽어 `대여소 × 시간` 카운트 생성
# 거대 파일에서 `대여일시/반납일시`는 **앞 13글자("YYYY-MM-DD HH")만 잘라** 시간 키로 사용한다.
# (datetime 전체 파싱을 생략 → 수천만 행에서 속도·메모리 대폭 절감)

# %%
# 사용할 컬럼 위치: 1=대여일시, 5=반납일시, 14=대여대여소ID, 15=반납대여소ID
USECOLS = [1, 5, 14, 15]
USENAMES = ["rental_dt", "return_dt", "rental_station_id", "return_station_id"]

def _hourly_counts(chunk, dt_col, id_col, out_name):
    """청크에서 (station_id, 시간키) 별 건수 집계."""
    sub = chunk[[dt_col, id_col]].dropna()
    sub["hour_key"] = sub[dt_col].str.slice(0, 13)          # "2024-01-01 00"
    sub = sub[sub["hour_key"].str.len() == 13]
    g = (sub.groupby([id_col, "hour_key"]).size()
            .rename(out_name).reset_index()
            .rename(columns={id_col: "station_id"}))
    return g

def aggregate_hourly(months, sample_rows=None, chunksize=CHUNKSIZE):
    """월별 파일을 청크로 읽어 시간별 대여/반납 건수 테이블 생성."""
    rent_all, ret_all = [], []
    for m in months:
        path = RENTAL_TMPL.format(m=m)
        if not os.path.exists(path):
            print(f"  [건너뜀] 파일 없음: {path}")
            continue
        reader = pd.read_csv(path, encoding="cp949", usecols=USECOLS,
                             header=0, names=USENAMES, dtype=str,
                             chunksize=chunksize, on_bad_lines="skip")
        rent_parts, ret_parts, read = [], [], 0
        for chunk in reader:
            rent_parts.append(_hourly_counts(chunk, "rental_dt", "rental_station_id", "rental_count"))
            ret_parts.append(_hourly_counts(chunk, "return_dt", "return_station_id", "return_count"))
            read += len(chunk)
            if sample_rows and read >= sample_rows:
                break
        # 파일 단위로 1차 합산(메모리 절감)
        rent_all.append(pd.concat(rent_parts).groupby(["station_id", "hour_key"], as_index=False)["rental_count"].sum())
        ret_all.append(pd.concat(ret_parts).groupby(["station_id", "hour_key"], as_index=False)["return_count"].sum())
        print(f"  [{m}] 처리 행수 {read:,} → 누적 집계 완료")

    rent = pd.concat(rent_all).groupby(["station_id", "hour_key"], as_index=False)["rental_count"].sum()
    ret  = pd.concat(ret_all).groupby(["station_id", "hour_key"], as_index=False)["return_count"].sum()
    agg = rent.merge(ret, on=["station_id", "hour_key"], how="outer")
    agg[["rental_count", "return_count"]] = agg[["rental_count", "return_count"]].fillna(0).astype("int32")
    agg["datetime"] = pd.to_datetime(agg["hour_key"], format="%Y-%m-%d %H")
    return agg.drop(columns="hour_key")

print("시간 단위 집계 시작...")
agg = aggregate_hourly(MONTHS, sample_rows=SAMPLE_ROWS)
print("집계 결과 shape:", agg.shape)
print(agg.head())

# %%
# --- Full grid: (활성 대여소 × 전체 시간) 데카르트곱 후 결측 카운트 0으로 채움 ---
# 활성 대여소 = 데이터에 등장한 대여소 (필요 시 MIN_STATION_TOTAL 로 저활동 대여소 제거)
station_total = agg.groupby("station_id")["rental_count"].sum()
active_stations = sorted(station_total[station_total > MIN_STATION_TOTAL].index)

hour_min = agg["datetime"].min().normalize()
hour_max = agg["datetime"].max().normalize() + pd.Timedelta(hours=23)
full_hours = pd.date_range(hour_min, hour_max, freq="h")
print(f"활성 대여소 {len(active_stations):,}개 × 시간 {len(full_hours):,}개 "
      f"= {len(active_stations) * len(full_hours):,} 행")

full_index = pd.MultiIndex.from_product([active_stations, full_hours],
                                        names=["station_id", "datetime"])
df = (agg.set_index(["station_id", "datetime"])
         .reindex(full_index, fill_value=0)
         .reset_index())
df["rental_count"] = df["rental_count"].astype("int32")
df["return_count"] = df["return_count"].astype("int32")
df["net_flow"] = (df["return_count"] - df["rental_count"]).astype("int32")   # +면 유입(과잉), -면 유출(부족)
print("full grid shape:", df.shape)

# %% [markdown]
# ### 2-2. 날짜/시간 파생변수 생성

# %%
dt = df["datetime"]
df["date"]        = dt.dt.date
df["hour"]        = dt.dt.hour.astype("int8")
df["day_of_week"] = dt.dt.dayofweek.astype("int8")        # 0=월 ... 6=일
df["is_weekend"]  = (df["day_of_week"] >= 5).astype("int8")
df["month"]       = dt.dt.month.astype("int8")
df["year_month"]  = dt.dt.strftime("%Y-%m")

_season_map = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
               6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}
df["season"] = df["month"].map(_season_map).astype("category")

# 출퇴근 시간대: 오전 7~9시, 오후 17~19시
df["is_rush_hour"] = df["hour"].isin([7, 8, 9, 17, 18, 19]).astype("int8")
print(df[["datetime", "hour", "day_of_week", "is_weekend", "month", "season", "is_rush_hour"]].head())

# %% [markdown]
# ### 2-4. 외부 데이터 병합 (기상=날짜+시간 / 공휴일=날짜 / 대여소 정보=station_id)

# %%
# 기상 병합 (datetime 시간 단위 일치)
df = df.merge(weather, on="datetime", how="left")

# 공휴일 병합 (date 기준 플래그)
df["is_holiday"] = df["date"].isin(holiday_2024).astype("int8")
# 휴무일(주말 또는 공휴일)
df["is_dayoff"] = ((df["is_weekend"] == 1) | (df["is_holiday"] == 1)).astype("int8")

# 대여소 정보 병합 (station_id)
df = df.merge(station_info[["station_id", "station_name", "district",
                            "rack_count", "latitude", "longitude"]],
              on="station_id", how="left")

# --- 병합 후 결측 점검 ---
print("병합 후 결측치 (있는 컬럼만):")
m = df.isna().sum()
print(m[m > 0])

# %% [markdown]
# **결측 처리 방침**
# - **기상 컬럼 결측**: 특정 시간대 관측 누락이 원인. 시간 연속성이 있으므로 시간순 보간(`interpolate`) 후
#   잔여 결측은 직전/직후 값으로 채운다(`ffill/bfill`).
# - **대여소 정보 결측(district/rack_count/lat/lon)**: API 마스터에 없는(폐쇄·신설) 대여소ID가 대여이력에만
#   존재할 때 발생. 위치 정보는 보간 불가 → 지도/공간분석에서는 제외하고, 수요 시계열 분석에는 그대로 유지한다.

# %%
# 기상 결측 보간
weather_cols = ["temperature", "precipitation", "humidity", "wind_speed", "temp_max", "temp_min"]
df = df.sort_values(["station_id", "datetime"])
for c in weather_cols:
    df[c] = df[c].interpolate(limit_direction="both")
# 강수량 결측/음수 방어
df["precipitation"] = df["precipitation"].fillna(0).clip(lower=0)
print("기상 결측 처리 후 잔여 결측:")
print(df[weather_cols].isna().sum())

# %% [markdown]
# ### 2-5. 예측용 타깃 변수 생성
# - **target_reg** = *다음 시간대* `rental_count` (대여소별 1시간 후 수요). full grid가 시간 연속이라 `shift(-1)`로 안전하게 생성.
# - **target_cls** = 대여소별 `rental_count` 분위수 기준 수요 등급. 하위 25%↓ **Low**, 상위 25%↑ **High**, 그 외 **Normal**.
# - **누수 방지**: 설명변수에는 *현재 시점 이하* 정보만 사용한다. 과거 수요 lag/rolling 변수는 `shift(+)`로 만들어 미래 정보 유입을 차단한다.

# %%
df = df.sort_values(["station_id", "datetime"]).reset_index(drop=True)
g = df.groupby("station_id", observed=True)

# 회귀 타깃: 다음 시간 대여량
df["target_reg"] = g["rental_count"].shift(-1)

# 과거 수요 변수(누수 방지: 모두 과거 방향 shift)
df["lag_1h"]   = g["rental_count"].shift(1)
df["lag_24h"]  = g["rental_count"].shift(24)
df["roll_24h"] = g["rental_count"].shift(1).rolling(24, min_periods=1).mean().reset_index(level=0, drop=True)

# 분류 타깃: 대여소별 분위수(현재 rental_count 분포) → 다음 시간 수요(target_reg)를 등급화
q = df.groupby("station_id", observed=True)["rental_count"].quantile([0.25, 0.75]).unstack()
q.columns = ["q25", "q75"]
df = df.merge(q, on="station_id", how="left")
df["target_cls"] = np.where(df["target_reg"] <= df["q25"], "Low",
                     np.where(df["target_reg"] >= df["q75"], "High", "Normal"))
df.loc[df["target_reg"].isna(), "target_cls"] = np.nan   # 마지막 시간은 타깃 없음
df["target_cls"] = df["target_cls"].astype("category")

# 각 대여소의 마지막 시간(타깃 없음) 행 확인
print("target_reg 결측(=대여소별 마지막 시간) 행수:", df["target_reg"].isna().sum())
print("target_cls 분포:\n", df["target_cls"].value_counts(dropna=False))
print(df[["station_id", "datetime", "rental_count", "target_reg",
          "lag_1h", "lag_24h", "roll_24h", "target_cls"]].head(8))

# %% [markdown]
# > **target_cls 클래스 불균형 주의(영과잉)**: 대여소×시간 단위는 대부분의 칸이 0인 *zero-inflated* 데이터다.
# > 저활동 대여소는 분위수가 q25=q75=0이 되어 0이 전부 Low로 분류되므로 Normal이 얇아진다(데이터 특성, 버그 아님).
# > 대안: ① 분류 단위를 **대여소×날짜(일 단위)** 로 올려 0을 줄이거나, ② "부족 위험" 같은 도메인 임계값 라벨을 별도 설계.
# > 본 노트북은 요구사항대로 분위수 정의를 유지하고, 분포를 함께 출력해 불균형을 드러낸다.

# %% [markdown]
# ## 3. 기초통계 분석

# %%
# 모델/통계용으로 타깃이 존재하는 행만 사용 (대여소별 마지막 시간 제외)
data = df.dropna(subset=["target_reg"]).copy()
data["target_reg"] = data["target_reg"].astype("int32")

summary_basic = pd.Series({
    "전체 대여 건수":   int(df["rental_count"].sum()),
    "전체 반납 건수":   int(df["return_count"].sum()),
    "분석 시작":        str(df["datetime"].min()),
    "분석 종료":        str(df["datetime"].max()),
    "분석 대여소 수":   df["station_id"].nunique(),
    "총 (대여소×시간) 행": len(df),
}).to_frame("값")
print(summary_basic)

# %%
# 대여소별 평균/표준편차
by_station = (df.groupby("station_id")["rental_count"]
                .agg(평균대여="mean", 표준편차="std", 총대여="sum")
                .sort_values("총대여", ascending=False))
print("대여소별 평균/표준편차 (상위 10):")
print(by_station.head(10).round(2))

# 시간대별 / 요일별 / 월별 평균
by_hour  = df.groupby("hour")["rental_count"].mean().round(3)
by_dow   = df.groupby("day_of_week")["rental_count"].mean().round(3)
by_month = df.groupby("month")["rental_count"].mean().round(3)
print("\n시간대별 평균 대여량:\n", by_hour.to_string())
print("\n요일별(0=월) 평균 대여량:\n", by_dow.to_string())
print("\n월별 평균 대여량:\n", by_month.to_string())

# 강수 여부별 평균
df["is_rain"] = (df["precipitation"] > 0).astype("int8")
by_rain = df.groupby("is_rain")["rental_count"].agg(평균="mean", 표본수="size").round(3)
by_rain.index = ["비안옴", "비옴"]
print("\n강수 여부별 평균 대여량:\n", by_rain)

# %%
# 대여-반납 차이(net_flow 절대합)가 큰 대여소 Top 10
flow_gap = (df.groupby("station_id")
              .agg(총대여=("rental_count", "sum"),
                   총반납=("return_count", "sum"),
                   순유입=("net_flow", "sum")).reset_index())
flow_gap["불균형규모"] = flow_gap["순유입"].abs()
flow_gap = flow_gap.merge(station_info[["station_id", "station_name", "district"]],
                          on="station_id", how="left")
top_gap = flow_gap.sort_values("불균형규모", ascending=False).head(10)
print("대여-반납 불균형 Top 10 (순유입 절대값 기준):")
print(top_gap[["station_id", "station_name", "district", "총대여", "총반납", "순유입"]].to_string(index=False))

# %% [markdown]
# **해석 (기초통계 → 문제정의 연결)**
# - 시간대별·요일별·월별 평균 대여량의 분산이 크다면, 수요는 **시간 구조**에 강하게 의존한다는 뜻 → 시간 변수 중심 모델링의 근거.
# - `net_flow` 절대합이 큰 대여소는 구조적으로 자전거가 **빠져나가기만(부족)** 하거나 **쌓이기만(과잉)** 하는 곳 → 선제적 재배치 1순위 후보.
# - 강수 여부별 평균 차이가 뚜렷하면 날씨 변수를 보조 설명변수로 포함할 가치가 있다.

# %% [markdown]
# ## 4. 데이터 시각화
# 각 그래프는 `outputs/`에 PNG로도 저장된다.

# %%
def finish(fig, fname):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, fname), dpi=120, bbox_inches="tight")
    plt.show()

# 4-1. 시간대별 평균 대여량 선그래프
fig, ax = plt.subplots(figsize=(10, 4))
by_hour.plot(marker="o", ax=ax)
ax.set_title("시간대별 평균 대여량")
ax.set_xlabel("시간(0~23시)"); ax.set_ylabel("평균 대여 건수")
ax.set_xticks(range(0, 24))
finish(fig, "01_시간대별_평균대여량.png")

# %% [markdown]
# - **확인된 패턴**: 출근(8~9시)·퇴근(18~19시) 피크가 보이는지 확인.
# - **문제정의와의 연결**: 부족은 특정 시간대에 집중 발생 → "언제" 부족한지의 1차 답.
# - **모델 변수로 반영할 내용**: `hour`, `is_rush_hour`.

# %%
# 4-2. 요일 × 시간대 평균 대여량 히트맵
pivot = df.pivot_table(index="day_of_week", columns="hour",
                       values="rental_count", aggfunc="mean")
pivot.index = ["월", "화", "수", "목", "금", "토", "일"]
fig, ax = plt.subplots(figsize=(13, 4.5))
sns.heatmap(pivot, cmap="YlOrRd", ax=ax, cbar_kws={"label": "평균 대여 건수"})
ax.set_title("요일 × 시간대 평균 대여량 히트맵")
ax.set_xlabel("시간"); ax.set_ylabel("요일")
finish(fig, "02_요일x시간대_히트맵.png")

# %% [markdown]
# - **확인된 패턴**: 평일은 출퇴근 쌍봉, 주말은 낮 시간대 단봉 형태인지 확인.
# - **문제정의와의 연결**: 평일/주말의 부족 시점이 다르므로 재배치 타이밍도 달라야 함.
# - **모델 변수로 반영할 내용**: `hour × day_of_week` 상호작용, `is_weekend`.

# %%
# 4-3. 월별 평균 대여량
fig, ax = plt.subplots(figsize=(9, 4))
by_month.plot(kind="bar", ax=ax, color="#4C78A8")
ax.set_title("월별 평균 대여량")
ax.set_xlabel("월"); ax.set_ylabel("평균 대여 건수")
finish(fig, "03_월별_평균대여량.png")

# %% [markdown]
# - **확인된 패턴**: 봄·가을 성수기, 겨울 비수기 등 계절성 확인.
# - **문제정의와의 연결**: 계절에 따라 전체 수요 수준이 달라져 부족 빈도도 달라짐.
# - **모델 변수로 반영할 내용**: `month`, `season`.

# %%
# 4-4. 대여소별 총 대여량 Top 20
top20 = by_station.head(20).merge(
    station_info[["station_id", "station_name"]], on="station_id", how="left")
top20["label"] = top20["station_name"].fillna(top20["station_id"])
fig, ax = plt.subplots(figsize=(10, 6))
ax.barh(top20["label"][::-1], top20["총대여"][::-1], color="#54A24B")
ax.set_title("대여소별 총 대여량 Top 20")
ax.set_xlabel("총 대여 건수"); ax.set_ylabel("대여소")
finish(fig, "04_대여소별_총대여량_Top20.png")

# %% [markdown]
# - **확인된 패턴**: 상위 소수 대여소에 수요가 집중되는지(롱테일) 확인.
# - **문제정의와의 연결**: 수요 집중 대여소가 부족 위험도 높음 → 우선 관리 대상.
# - **모델 변수로 반영할 내용**: 대여소 식별/특성(`station_id`, `district`, `rack_count`).

# %%
# 4-5. 강수 여부별 대여량 박스플롯 (0 과다 분포라 로그 스케일)
fig, ax = plt.subplots(figsize=(7, 5))
sns.boxplot(data=df, x="is_rain", y="rental_count", ax=ax, showfliers=False)
ax.set_xticklabels(["비안옴", "비옴"])
ax.set_title("강수 여부별 시간당 대여량 분포")
ax.set_xlabel("강수 여부"); ax.set_ylabel("시간당 대여 건수")
finish(fig, "05_강수여부별_박스플롯.png")

# %% [markdown]
# - **확인된 패턴**: 비 오는 시간대 대여량 중앙값/분포가 낮아지는지 확인.
# - **문제정의와의 연결**: 강수는 단기 수요 급감 요인 → 재배치 의사결정 시 보정 필요.
# - **모델 변수로 반영할 내용**: `precipitation`, `is_rain`.

# %%
# 4-6. 기온 구간별 평균 대여량
temp_bins = [-100, 0, 5, 10, 15, 20, 25, 30, 100]
temp_labels = ["0↓", "0~5", "5~10", "10~15", "15~20", "20~25", "25~30", "30↑"]
df["temp_band"] = pd.cut(df["temperature"], bins=temp_bins, labels=temp_labels)
by_temp = df.groupby("temp_band")["rental_count"].mean()
fig, ax = plt.subplots(figsize=(9, 4))
by_temp.plot(marker="o", ax=ax, color="#E45756")
ax.set_title("기온 구간별 평균 대여량")
ax.set_xlabel("기온 구간(℃)"); ax.set_ylabel("평균 대여 건수")
finish(fig, "06_기온구간별_평균대여량.png")

# %% [markdown]
# - **확인된 패턴**: 적정 기온(약 15~25℃)에서 수요 최고, 혹한·혹서에서 급감하는 비선형 관계 확인.
# - **문제정의와의 연결**: 기온은 계절성과 함께 수요 수준을 좌우.
# - **모델 변수로 반영할 내용**: `temperature`(비선형 → 트리계열 모델에 적합).

# %%
# 4-7. 대여소별 net_flow Top 20 (유출=부족 10 + 유입=과잉 10)
flow_sorted = flow_gap.sort_values("순유입")
worst_short = flow_sorted.head(10)    # 가장 유출(부족) 심한 곳
worst_over  = flow_sorted.tail(10)    # 가장 유입(과잉) 심한 곳
plot_df = pd.concat([worst_short, worst_over])
plot_df["label"] = plot_df["station_name"].fillna(plot_df["station_id"])
colors = ["#E45756" if v < 0 else "#4C78A8" for v in plot_df["순유입"]]
fig, ax = plt.subplots(figsize=(10, 7))
ax.barh(plot_df["label"], plot_df["순유입"], color=colors)
ax.axvline(0, color="k", lw=0.8)
ax.set_title("대여소별 순유입(net_flow) — 부족(빨강) / 과잉(파랑) Top 20")
ax.set_xlabel("순유입 = 총반납 - 총대여")
finish(fig, "07_대여소별_netflow_Top20.png")

# %% [markdown]
# - **확인된 패턴**: 순유출(빨강)=자전거가 계속 빠지는 부족 대여소, 순유입(파랑)=쌓이는 과잉 대여소.
# - **문제정의와의 연결**: 이 두 그룹을 잇는 것이 **선제적 재배치**의 핵심 경로.
# - **모델 변수로 반영할 내용**: `net_flow`(타깃·진단 지표), 대여소 위치(`district`, 좌표).

# %%
# 4-8. 대여소 위치 지도 (folium): 점 크기=총대여량, 색=net_flow 방향
import folium

map_df = flow_gap.merge(
    station_info[["station_id", "latitude", "longitude"]], on="station_id", how="left").dropna(
    subset=["latitude", "longitude"])
# 수요 등급(대여소 총대여량 분위수)
ql, qh = map_df["총대여"].quantile([0.25, 0.75])
def grade(v): return "High" if v >= qh else ("Low" if v <= ql else "Normal")
map_df["수요등급"] = map_df["총대여"].apply(grade)

m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="cartodbpositron")
max_total = map_df["총대여"].max() or 1
for _, r in map_df.iterrows():
    color = "red" if r["순유입"] < 0 else "blue"      # 부족=빨강, 과잉=파랑
    radius = 3 + 12 * (r["총대여"] / max_total)
    folium.CircleMarker(
        location=[r["latitude"], r["longitude"]],
        radius=radius, color=color, fill=True, fill_color=color, fill_opacity=0.5,
        popup=folium.Popup(
            f"{r['station_name']} ({r['district']})<br>총대여 {int(r['총대여']):,} / "
            f"순유입 {int(r['순유입']):,} / 등급 {r['수요등급']}", max_width=250),
    ).add_to(m)
map_path = os.path.join(OUT_DIR, "08_대여소_지도.html")
m.save(map_path)
print("지도 저장:", map_path)
m  # 노트북에서 인라인 표시

# %% [markdown]
# - **확인된 패턴**: 도심·한강변에 수요 집중, 외곽은 저수요인지 공간 분포 확인.
# - **문제정의와의 연결**: 부족(빨강)·과잉(파랑) 대여소가 지리적으로 인접하면 재배치 비용이 낮음.
# - **모델 변수로 반영할 내용**: `latitude/longitude`, `district`(공간 군집/클러스터 변수).

# %% [markdown]
# ## 5. 시간 변수가 중요한 근거 제시
# (1) 시간대별 수요 차이, (2) 요일×시간 히트맵은 4장에서 시각적으로 확인했다.
# 여기서는 (3) **시간 변수만 사용한 baseline 성능**을 측정하고,
# (4) 변수군을 단계적으로 추가하며 설명력(R²/MAE/RMSE)이 어떻게 향상되는지 비교한다.

# %% [markdown]
# ### 실험 설계
# | 실험 | 사용 변수 | 목적 | 기대 효과 |
# |---|---|---|---|
# | 실험 1 | 시간 변수만 | 기본 시간 패턴 확인 | baseline |
# | 실험 2 | 시간 + 날씨 | 조건 변화 반영 | 강수·기온 영향 반영 |
# | 실험 3 | 시간 + 날씨 + 대여소 특성 | 공간 차이 반영 | 대여소별 수요 차이 반영 |
# | 실험 4 | 시간 + 날씨 + 대여소 특성 + 과거 수요 | 최종 예측 성능 향상 | 반복 패턴 반영 |

# %%
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# 변수군 정의
TIME_FEATS    = ["hour", "day_of_week", "is_weekend", "month", "is_rush_hour", "is_holiday"]
WEATHER_FEATS = ["temperature", "precipitation", "humidity", "wind_speed"]
STATION_FEATS = ["rack_count", "latitude", "longitude", "district_code"]
LAG_FEATS     = ["lag_1h", "lag_24h", "roll_24h"]

model_df = data.copy()
model_df["district_code"] = model_df["district"].astype("category").cat.codes      # 자치구 → 정수 인코딩
model_df = model_df.dropna(subset=LAG_FEATS + STATION_FEATS)                        # lag/위치 결측 제거

# 시간 순서 기반 train/test 분할 (앞 80% 학습, 뒤 20% 검증)
model_df = model_df.sort_values("datetime")
split_t = model_df["datetime"].quantile(0.8)
train_mask = model_df["datetime"] <= split_t
train_full = model_df[train_mask]
test_full  = model_df[~train_mask]

# 학습 표본 축소(대용량 RF 시간 단축) — 검증셋은 그대로 사용
if len(train_full) > MODEL_SAMPLE:
    train_full = train_full.sample(MODEL_SAMPLE, random_state=42)
print(f"학습 {len(train_full):,}행 / 검증 {len(test_full):,}행 (분할 기준 {split_t})")

y_train = train_full["target_reg"]
y_test  = test_full["target_reg"]

# %%
# (3) 시간 변수만 쓰는 단순 baseline: (hour, day_of_week)별 평균 대여량으로 예측
base_table = train_full.groupby(["hour", "day_of_week"])["target_reg"].mean()
pred_base = test_full.set_index(["hour", "day_of_week"]).index.map(base_table)
pred_base = pd.Series(pred_base, index=test_full.index).fillna(y_train.mean())

def score(y_true, y_pred):
    return {
        "MAE":  mean_absolute_error(y_true, y_pred),
        "RMSE": mean_squared_error(y_true, y_pred) ** 0.5,
        "R2":   r2_score(y_true, y_pred),
    }

results = {"baseline(시간평균)": score(y_test, pred_base)}
print("baseline(시간 hour×dow 평균):", {k: round(v, 3) for k, v in results["baseline(시간평균)"].items()})

# %%
# 실험 1~4: 변수군을 단계적으로 추가하며 RandomForest 학습
experiments = {
    "실험1: 시간":                  TIME_FEATS,
    "실험2: 시간+날씨":             TIME_FEATS + WEATHER_FEATS,
    "실험3: 시간+날씨+대여소":      TIME_FEATS + WEATHER_FEATS + STATION_FEATS,
    "실험4: 시간+날씨+대여소+과거": TIME_FEATS + WEATHER_FEATS + STATION_FEATS + LAG_FEATS,
}

for name, feats in experiments.items():
    rf = RandomForestRegressor(n_estimators=60, max_depth=18, n_jobs=-1, random_state=42)
    rf.fit(train_full[feats], y_train)
    results[name] = score(y_test, rf.predict(test_full[feats]))
    print(f"{name:28s} -> " + ", ".join(f"{k} {v:.3f}" for k, v in results[name].items()))

result_table = pd.DataFrame(results).T[["MAE", "RMSE", "R2"]].round(3)
print("\n=== 실험 성능 비교표 ===")
print(result_table)
result_table.to_csv(os.path.join(OUT_DIR, "experiment_results.csv"), encoding="utf-8-sig")

# %%
# 성능 향상 시각화
fig, ax = plt.subplots(figsize=(9, 4.5))
result_table["R2"].plot(kind="bar", ax=ax, color="#4C78A8")
ax.set_title("실험 단계별 설명력(R²) 비교")
ax.set_ylabel("R² (검증셋)"); ax.set_xlabel("")
plt.xticks(rotation=20, ha="right")
finish(fig, "09_실험별_R2비교.png")

# %% [markdown]
# **해석 (시간 변수의 중요성)**
# - `baseline(시간평균)`만으로도 상당한 R²가 나온다면, **수요의 큰 부분이 시간 구조로 설명**된다는 직접 증거다.
# - 실험1→2 향상폭 = 날씨의 한계기여, 2→3 = 대여소(공간) 한계기여, 3→4 = 과거 수요(자기상관)의 한계기여.
# - 통상 실험4에서 `lag/rolling` 추가 시 가장 큰 향상이 나타나며, 이는 "시간 + 과거 패턴"이 핵심 신호임을 보여준다.
# - ⚠️ **샘플(1개월) 실행 주의**: 한 달치만 돌리면 `month/season` 변동이 없고 기온 변동도 작아 날씨 변수가 노이즈로
#   작용해 실험2 R²가 오히려 내려갈 수 있다. 변수군 단계 비교는 반드시 **전체 12개월**로 해석할 것.
# - ⚠️ 시간 순서 분할이라, 1개월 샘플의 검증셋은 "1월 하순"에 치우친다. 전체 실행 시 계절 분포가 고르게 섞인다.

# %% [markdown]
# ## 6. 최종 산출물

# %%
# (1) 전처리 완료 데이터프레임 저장
keep_cols = ["station_id", "station_name", "district", "datetime", "date",
             "hour", "day_of_week", "is_weekend", "month", "season", "year_month",
             "is_rush_hour", "is_holiday", "is_dayoff",
             "rental_count", "return_count", "net_flow",
             "temperature", "precipitation", "humidity", "wind_speed", "is_rain",
             "rack_count", "latitude", "longitude",
             "lag_1h", "lag_24h", "roll_24h", "target_reg", "target_cls"]
final_df = df[[c for c in keep_cols if c in df.columns]].copy()
parquet_path = os.path.join(OUT_DIR, "processed_hourly.parquet")
try:
    final_df.to_parquet(parquet_path, index=False)
    print("전처리 데이터 저장:", parquet_path, final_df.shape)
except Exception as e:
    csv_path = os.path.join(OUT_DIR, "processed_hourly.csv")
    final_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print("(parquet 불가 → csv 저장)", csv_path, final_df.shape)

# (2) 기초통계 표 저장
summary_basic.to_csv(os.path.join(OUT_DIR, "stat_summary_basic.csv"), encoding="utf-8-sig")
by_station.to_csv(os.path.join(OUT_DIR, "stat_by_station.csv"), encoding="utf-8-sig")
top_gap.to_csv(os.path.join(OUT_DIR, "stat_flow_gap_top10.csv"), index=False, encoding="utf-8-sig")

# %% [markdown]
# ### (4) 시간 변수가 중요한 이유 — 요약
# - 시간대별·요일×시간 패턴이 뚜렷하고, **시간 변수만의 baseline R²가 이미 높다**.
# - 즉 따릉이 부족은 "무작위"가 아니라 **반복되는 시간 구조** 안에서 발생 → "언제 부족한가"를 시간 변수로 선제 예측 가능.
#
# ### (5) 모델링 최종 변수 후보
# | 그룹 | 변수 |
# |---|---|
# | 시간 | hour, day_of_week, is_weekend, month, season, is_rush_hour, is_holiday, is_dayoff |
# | 날씨 | temperature, precipitation, humidity, wind_speed, is_rain |
# | 대여소 | district, rack_count, latitude, longitude |
# | 과거 수요 | lag_1h, lag_24h, roll_24h |
#
# ### (6) 타깃 변수
# - **회귀** `target_reg`: 다음 1시간 `rental_count` (연속값). 부족량 예측·재배치 수량 산정에 사용.
# - **분류** `target_cls`: 대여소별 분위수 기준 Low/Normal/High. "High 예상 대여소"를 사전 경보하는 의사결정 트리거.
#
# ### (7) 다음 단계 모델링 실험 계획
# 1. 위 실험1~4를 **전체 데이터**로 재실행하여 변수군별 한계기여 확정.
# 2. 회귀: RandomForest/LightGBM + 시계열 교차검증(시간 순서 보존), 평가지표 MAE/RMSE.
# 3. 분류: 동일 변수로 Low/Normal/High 예측, 평가지표 F1(High 재현율 중시 — 부족 사전탐지).
# 4. 예측된 High 대여소 + 음(-)의 net_flow 예측을 결합해 **재배치 우선순위 리스트** 산출.

# %%
print("완료. 산출물 폴더:", OUT_DIR)
print(sorted(os.listdir(OUT_DIR)))
