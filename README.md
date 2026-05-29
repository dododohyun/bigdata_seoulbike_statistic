# 서울시 따릉이 수요예측 프로젝트

> **주제**: 서울시 따릉이 자전거 부족은 언제 발생하는가? — 시간 패턴 기반 수요예측과 선제적 재배치 의사결정 지원
>
> **분석 단위**: 대여소 × 날짜 × 시간 | **핵심 가설**: 부족은 무작위가 아니라 *반복되는 시간 구조* 안에서 발생한다 → 시간 변수로 선제 예측 가능

---

## 1. 폴더 / 파일 구조

```
bigdata_pj/
├─ bike_demand_analysis.py        # 전체 분석 노트북 (# %% 셀, VSCode/Jupyter 실행)
├─ api_config.py                  # API 키 + 호출 코드 (★비공개, .gitignore 제외)
├─ api_config.example.py          # 위 파일의 공개용 템플릿 (키 없음, 커밋됨)
├─ .gitignore                     # 키/데이터/산출물 업로드 제외 규칙
├─ README.md                      # (이 문서) 데이터 출처·실행 안내
├─ rental_data_2024/              # 따릉이 대여이력 (월별 12개, cp949, 총 ~7.6GB)
│   ├─ 서울특별시 공공자전거 대여이력 정보_2401.csv
│   ├─ ...
│   └─ 서울특별시 공공자전거 대여이력 정보_2412.csv
├─ weather_data/
│   └─ weather_2024.csv           # 시간단위 기상 (utf-8-sig)
├─ holiday_data/
│   └─ 국가데이터처_지표누리_공휴일 자료_20251106.csv   # 공휴일 (cp949)
└─ outputs/                       # 분석 산출물 (실행 시 자동 생성)
```

---

## 2. 데이터 출처 (Data Provenance)

| # | 데이터 | 제공 기관 | 취득 방법 | 형식 / 인코딩 | 기간 |
|---|---|---|---|---|---|
| 1 | 공공자전거(따릉이) **대여이력** | 서울특별시 (서울 열린데이터광장 / 공공데이터포털) | 월별 CSV 다운로드 | CSV · **cp949** · 17컬럼 | 2024-01 ~ 2024-12 |
| 2 | **기상** (기온·강수·습도·풍속) | 기상청 (기상자료개방포털 ASOS 서울지점) *추정* | CSV 다운로드 | CSV · **utf-8-sig** · 시간단위 | 2024-01-01 ~ 2024-12-31 |
| 3 | **공휴일** | 국가데이터처 지표누리 | CSV 다운로드 | CSV · **cp949** · 3컬럼 | 2023~2025 (2024 사용) |
| 4 | 공공자전거 **대여소 정보** | 서울특별시 (서울 열린데이터광장) | **OpenAPI 실시간 호출** | JSON · 3,230개소 | 최신 마스터 |

### 2-1. 출처 상세 / 다운로드 위치

- **① 따릉이 대여이력** — "서울특별시 공공자전거 대여이력 정보"
  - 제공: 서울 열린데이터광장(<https://data.seoul.go.kr>) 및 공공데이터포털(<https://www.data.go.kr>)에서 월별 파일로 배포.
  - 다운로드 URL(정확한 페이지): `____________________` *(← 실제 받은 페이지 링크 기입)*
  - 비고: 1행 = 1회 이용(대여+반납) 트랜잭션. 본 분석은 대용량(7.6GB)이라 4개 컬럼만 청크로 읽음.

- **② 기상 데이터** — `weather_2024.csv`
  - 제공: 기상청 기상자료개방포털(<https://data.kma.go.kr>) 종관기상관측(ASOS) 시간자료로 **추정**.
  - 다운로드 URL: `____________________` *(← 실제 출처 링크/지점명 기입; 서울(108) 지점 등)*
  - 컬럼이 이미 영문(`datetime, temperature, precipitation, humidity, wind_speed, temp_max, temp_min`)으로 가공돼 있음 → 원본을 전처리한 파일일 수 있음.

- **③ 공휴일 데이터** — `국가데이터처_지표누리_공휴일 자료_20251106.csv`
  - 제공: 국가데이터처 **지표누리**(<https://www.index.go.kr>) 공휴일 자료. (파일명 날짜 20251106 = 추출 시점)
  - 당초 의도된 API: 공공데이터포털 **한국천문연구원_특일 정보** (<https://www.data.go.kr/data/15051891/openapi.do>) — 단, 제공된 인증키가 **401(인증 실패)** 이라 로컬 CSV로 대체함.
  - ⚠️ **주의**: 이 파일의 2024년 목록(13건)에는 **신정(1/1)·설날 연휴(2/9~2/12)·어린이날(5/5)이 누락**돼 있음. 원본 정의를 그대로 병합하되, 필요 시 표준 공휴일로 보완 가능.

- **④ 대여소 정보** — 로컬 파일 없음, **API로 수신**
  - 제공: 서울 열린데이터광장 **OA-21235 "서울특별시 공공자전거 대여소 정보"** (<https://data.seoul.go.kr/dataList/OA-21235/S/1/datasetView.do>)
  - 호출 서비스명: `tbCycleStationInfo` / 총 3,230개소
  - 수신 후 `outputs/station_info.csv`로 캐시되어, 이후엔 캐시를 재사용(네트워크 불가 시 fallback).

### 2-2. API 키 / 엔드포인트

| 용도 | 엔드포인트 | 인증키 | 상태 |
|---|---|---|---|
| 대여소 정보 (서울) | `http://openapi.seoul.go.kr:8088/{KEY}/json/tbCycleStationInfo/{start}/{end}/` | `api_config.py` 에 보관 (비공개) | ✅ 정상 |
| 공휴일 (공공데이터포털·특일정보) | `http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo` | `api_config.py` 에 보관 (비공개) | ❌ 401 → 로컬 CSV 사용 |

> **인증키 보안**: 실제 키와 API 호출 코드는 **`api_config.py`** 에만 두고, 이 파일은 `.gitignore` 로 제외되어 GitHub 에 올라가지 않는다.
> 분석 노트북(`bike_demand_analysis.py`)은 `import api_config` 만 하므로 키가 노트북에 남지 않는다.
> 다른 사람이 쓸 때는 `api_config.example.py` 를 `api_config.py` 로 복사한 뒤 본인 키를 입력하면 된다.

---

## 3. 컬럼 명세 (원본 → 영문 매칭)

### 대여이력 (17컬럼, cp949)
| 원본 | 영문 | 의미 |
|---|---|---|
| 자전거번호 | bike_id | 자전거 식별자 |
| 대여일시 | rental_datetime | 대여 시각 |
| 대여 대여소번호 | rental_station_no | 대여소 번호(5자리, 예 04804) |
| 대여 대여소명 | rental_station_name | 대여소명 |
| 대여거치대 | rental_rack | 대여 거치대 번호 |
| 반납일시 | return_datetime | 반납 시각 |
| 반납대여소번호 | return_station_no | 반납 대여소 번호 |
| 반납대여소명 | return_station_name | 반납 대여소명 |
| 반납거치대 | return_rack | 반납 거치대 번호 |
| 이용시간(분) | use_minutes | 이용 시간(분) |
| 이용거리(M) | use_distance_m | 이용 거리(m) |
| 생년 | birth_year | 이용자 출생연도 |
| 성별 | gender | 성별 |
| 이용자종류 | user_type | 이용자 구분 |
| **대여대여소ID** | **rental_station_id** | **ST-xxxx (분석 조인키)** |
| **반납대여소ID** | **return_station_id** | **ST-xxxx** |
| 자전거구분 | bike_type | 일반/새싹 등 |

> **분석 키**: 대여소 식별자가 `대여소번호(04804)`와 `대여소ID(ST-2630)` 두 가지인데, 대여소 정보 API의 `RENT_ID`(ST-xxxx)와 직접 조인되는 **대여소ID를 `station_id`로 사용**.

### 대여소 정보 (API)
`RENT_ID→station_id`, `RENT_NO→station_no`, `RENT_NM→station_name`, `STA_LOC→district(자치구)`, `HOLD_NUM→rack_count(거치대 수)`, `STA_LAT→latitude`, `STA_LONG→longitude`

### 기상 (이미 영문)
`datetime, temperature, precipitation, humidity, wind_speed, temp_max, temp_min`

### 공휴일
`연도별 순번, 연도, 공휴일(날짜)` → 병합 시 `is_holiday` 플래그로 사용 (공휴일명은 원본에 없음)

---

## 4. 분석 파이프라인 (`bike_demand_analysis.py`)

1. **데이터 구조 확인** — shape/타입/결측/중복/기간/기초통계
2. **전처리** — 컬럼 영문화 → 대여이력 청크 집계(대여소×시간 대여/반납 건수) → full grid(미발생 시간 0채움) → 날짜 파생변수(hour, day_of_week, is_weekend, month, season, is_rush_hour, year_month) → 외부 병합(기상=시간, 공휴일=날짜, 대여소=ID) → 타깃 생성
   - `target_reg` = 다음 시간 `rental_count` (회귀)
   - `target_cls` = 대여소별 분위수 Low/Normal/High (분류)
   - 과거 수요 변수 `lag_1h, lag_24h, roll_24h` (누수 방지 위해 과거 방향 shift)
3. **기초통계** — 시간/요일/월/강수/대여소별 표 + net_flow 불균형 Top10
4. **시각화 8종** — 시간대 선그래프 · 요일×시간 히트맵 · 월별 · Top20 대여소 · 강수 박스플롯 · 기온구간 · net_flow Top20 · folium 지도
5. **시간 변수 근거** — 시간평균 baseline + 실험1~4(시간→+날씨→+대여소→+과거수요) 성능 비교
6. **산출물 저장** — 전처리 데이터(parquet) + 통계표 + 그래프 + 지도

---

## 5. 실행 방법

```powershell
# (0) API 키 설정 (대여소 정보 수신용) — 캐시(outputs/station_info.csv)가 있으면 생략 가능
Copy-Item api_config.example.py api_config.py   # 이후 api_config.py 안의 키를 본인 것으로 입력

# (1) 빠른 검증 — 1개월 샘플
$env:BIKE_MONTHS="2401"; $env:BIKE_SAMPLE_ROWS="600000"
python bike_demand_analysis.py

# (2) 전체 12개월 (기본값) — 수십 분 소요, 메모리 큼
Remove-Item Env:BIKE_MONTHS, Env:BIKE_SAMPLE_ROWS -ErrorAction SilentlyContinue
python bike_demand_analysis.py
```

또는 VSCode/Jupyter에서 `# %%` 셀 단위로 실행.

- 필요 라이브러리: `pandas numpy matplotlib seaborn scikit-learn folium requests pyarrow`
- 한글 폰트: Windows `Malgun Gothic` (mac `AppleGothic` / linux `NanumGothic`으로 교체)
- 메모리 부족 시: 스크립트 상단 `MIN_STATION_TOTAL`을 올려 저활동 대여소 제외, `CHUNKSIZE` 조정

---

## 6. 산출물 (`outputs/`)

| 파일 | 내용 |
|---|---|
| `processed_hourly.parquet` | 전처리 완료 데이터 (대여소×시간 + 파생/외부/타깃) |
| `station_info.csv` | API로 받은 대여소 정보 캐시 |
| `stat_*.csv` | 기초통계 표 |
| `01_~09_*.png` | 시각화 그래프 |
| `08_대여소_지도.html` | folium 인터랙티브 지도 |
| `experiment_results.csv` | 실험1~4 성능 비교 |

---

## 7. 주의사항 (Caveat)

1. **공휴일 누락** — 제공 파일에 신정·설날연휴·어린이날(5/5) 빠짐(§2-1 ③).
2. **`target_cls` 클래스 불균형** — 대여소×시간은 0이 많은 zero-inflated 데이터라 분위수 분류 시 Normal이 얇아짐(버그 아님). 대안: 일 단위 집계 / 도메인 임계값 라벨.
3. **샘플 실행 해석 주의** — 1개월만 돌리면 계절·기온 변동이 없어 실험2(+날씨) R²가 하락할 수 있음. 변수군 단계 비교는 **전체 12개월**로 해석.
4. **인증키 보안** — 실제 키는 `api_config.py`(비공개, `.gitignore` 제외)에만 보관. 노트북·README 에는 키 값이 없다.
   GitHub 업로드 전 `git status` 로 `api_config.py` 가 추적되지 않는지 반드시 확인.