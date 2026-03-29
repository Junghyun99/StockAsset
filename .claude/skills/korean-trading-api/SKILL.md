---
name: korean-trading-api
description: Use when implementing or extending KIS broker for Korean domestic/overseas stock trading, or referencing KIS REST API endpoints, TR IDs, and request/response patterns
---

# 한국투자증권 (KIS) REST API Reference

## Overview

한국투자증권 Open Trading API를 통한 국내주식/해외주식 매매 레퍼런스.
현재 `src/infra/broker.py`의 `KisBrokerBase`는 **해외주식(미국)만 구현**되어 있으며, 국내주식은 미구현 상태.

**서버 URL:**
| 환경 | URL |
|------|-----|
| 실전 | `https://openapi.koreainvestment.com:9443` |
| 모의 | `https://openapivts.koreainvestment.com:29443` |

**기존 구현:** `KisPaperBroker`(모의), `KisLiveBroker`(실전) → `src/infra/broker.py:530-555`

## 공통 패턴

### 헤더 구성
```python
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "authorization": f"Bearer {access_token}",
    "appkey": app_key,
    "appsecret": app_secret,
    "tr_id": "<TR_ID>",
    "custtype": "P"  # P: 개인
}
# POST 요청 시 HashKey 추가 필요
if is_post:
    headers["hashkey"] = get_hashkey(data)
```
기존 구현: `_get_header()` at `broker.py:203`

### 핵심 규칙
| 항목 | 규칙 |
|------|------|
| 성공 판별 | `rt_cd == '0'` |
| POST 요청 | HashKey 필수 (`/uapi/hashkey`) |
| GET 요청 | HashKey 불필요 |
| Rate Limit | 호출 간 0.1~0.2초 sleep |
| 계좌번호 | `CANO` = 앞 8자리, `ACNT_PRDT_CD` = 뒤 2자리 |
| 파라미터 타입 | **모든 값은 String으로 전달** |
| 페이지네이션 | `tr_cont` 헤더 + `CTX_AREA_FK`/`CTX_AREA_NK` 연속 토큰 |

---

## 1. 인증

### REST 토큰 발급
- **Endpoint:** `POST /oauth2/tokenP`
- **구현:** `KisBrokerBase._auth()` at `broker.py:185`

```python
# Request
payload = {
    "grant_type": "client_credentials",
    "appkey": app_key,
    "appsecret": app_secret
}

# Response
{
    "access_token": "eyJ...",
    "token_type": "Bearer",
    "expires_in": 86400  # 24시간
}
```

### HashKey 생성
- **Endpoint:** `POST /uapi/hashkey`
- **구현:** `KisBrokerBase._get_hashkey()` at `broker.py:221`
- POST 주문 요청 시 body 데이터로 HashKey를 생성하여 헤더에 포함

### WebSocket 접속키 (미구현)
- **Endpoint:** `POST /oauth2/Approval`
- 실시간 시세 스트리밍 시 필요

---

## 2. 해외주식 API (구현됨)

### 2.1 현재가 조회
- **Endpoint:** `GET /uapi/overseas-price/v1/quotations/price`
- **TR ID:** `HHDFS00000300` (실전/모의 동일)
- **구현:** `fetch_current_prices()` at `broker.py:234`

```python
params = {"AUTH": "", "EXCD": "NAS", "SYMB": "AAPL"}
# Response: data['output']['last'] → 현재가
```

**거래소 코드 (현재가 조회용):** `NAS`(나스닥), `NYS`(뉴욕), `AMS`(아멕스)

### 2.1.1 호가 조회 (1호가)
- **Endpoint:** `GET /uapi/overseas-price/v1/quotations/inquire-asking-price`
- **TR ID:** `HHDFS76200100` (실전/모의 동일)
- **구현:** `_fetch_asking_price()` at `broker.py`

```python
params = {"AUTH": "", "EXCD": "NAS", "SYMB": "AAPL"}
# Response: data['output2'] → 호가 데이터
# output2['pbid1'] → 최우선 매수호가 (best bid)
# output2['pask1'] → 최우선 매도호가 (best ask)
```

**용도:** 주문 가격 결정 시 bid/ask 기반 지정가 주문 + 스프레드 이상 감지 (임계값 0.5%)

### 2.2 매수/매도
- **Endpoint:** `POST /uapi/overseas-stock/v1/trading/order`
- **구현:** `_send_order()` at `broker.py:387`

| 액션 | 실전 TR ID | 모의 TR ID |
|------|-----------|-----------|
| 미국 매수 | TTTT1002U | VTTT1002U |
| 미국 매도 | TTTT1006U | VTTT1006U |

```python
data = {
    "CANO": "50068923",
    "ACNT_PRDT_CD": "01",
    "OVRS_EXCG_CD": "NASD",       # 거래소 (NASD/NYSE/AMEX)
    "PDNO": "AAPL",               # 티커
    "ORD_QTY": "10",              # 수량
    "OVRS_ORD_UNPR": "150.00",    # 주문단가 (소수점 2자리)
    "CTAC_TLNO": "",
    "MGCO_APTM_ODNO": "",
    "SLL_TYPE": "00",             # 매도 시 "00", 매수 시 ""
    "ORD_SVR_DVSN_CD": "0",
    "ORD_DVSN": "00"              # 00: 지정가
}
```

**거래소 코드 (주문용):** `NASD`(나스닥), `NYSE`(뉴욕), `AMEX`(아멕스)

### 2.3 미체결 조회
- **Endpoint:** `GET /uapi/overseas-stock/v1/trading/inquire-nccs`
- **구현:** `_get_pending_orders_count()` at `broker.py:454`

| 환경 | TR ID |
|------|-------|
| 실전 | TTTS3018R |
| 모의 | VTTS3018R |

```python
params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "OVRS_EXCG_CD": "NASD",   # NASD → NYSE → AMEX 순회
    "SORT_SQN": "DS",
    "CTX_AREA_FK200": "",
    "CTX_AREA_NK200": ""
}
# Response: data['output'] → 미체결 주문 리스트
```

### 2.4 잔고 조회
- **Endpoint:** `GET /uapi/overseas-stock/v1/trading/inquire-balance`
- **구현:** `get_portfolio()` at `broker.py:269`

| 환경 | TR ID |
|------|-------|
| 실전 | TTTS3012R |
| 모의 | VTTS3012R |

```python
params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "OVRS_EXCG_CD": "NASD",   # NASD → NYSE → AMEX 순회
    "TR_CRCY_CD": "USD",
    "CTX_AREA_FK200": "",
    "CTX_AREA_NK200": ""
}
# Response:
# output1[]: ovrs_pdno(티커), ovrs_cblc_qty(보유수량), now_pric2(현재가)
# output2:   ovrs_ord_psbl_amt(주문가능금액, USD)
```

### 2.5 체결 내역 (미구현)
- **Endpoint:** `GET /uapi/overseas-stock/v1/trading/inquire-ccnl`
- **TR ID:** `TTTS3035R` (실전) / `VTTS3035R` (모의)
- 조회 기간, 매수/매도 구분, 체결/미체결 필터 지원
- 페이지네이션 지원 (CTX_AREA_FK200/NK200)

### 2.6 매수가능금액 (미구현)
- **Endpoint:** `GET /uapi/overseas-stock/v1/trading/inquire-psamount`
- **TR ID:** `TTTS3007R` (실전) / `VTTS3007R` (모의)
- 주문단가 기준 매수 가능 수량 계산

---

## 3. 국내주식 API (미구현)

### 3.1 매수/매도
- **Endpoint:** `POST /uapi/domestic-stock/v1/trading/order-cash`

| 액션 | 실전 TR ID | 모의 TR ID |
|------|-----------|-----------|
| 매수 | TTTC0012U | VTTC0012U |
| 매도 | TTTC0011U | VTTC0011U |

```python
data = {
    "CANO": "50068923",
    "ACNT_PRDT_CD": "01",
    "PDNO": "005930",             # 종목코드 (6자리, 예: 삼성전자)
    "ORD_DVSN": "01",             # 00: 지정가, 01: 시장가
    "ORD_QTY": "10",              # 주문수량 (String)
    "ORD_UNPR": "0",              # 주문단가 (시장가일 때 "0", KRW 정수)
    "EXCG_ID_DVSN_CD": "KRX",     # 거래소 구분 (KRX)
    "SLL_TYPE": "",               # 매도 유형
    "CNDT_PRIC": ""               # 조건부 가격
}
# Response:
# output: KRX_FWDG_ORD_NO(주문번호), ODNO(주문ID), ORD_TMD(주문시각)
```

### 3.2 주문 정정/취소
- **Endpoint:** `POST /uapi/domestic-stock/v1/trading/order-rvsecncl`

| 환경 | TR ID |
|------|-------|
| 실전 | TTTC0013U |
| 모의 | VTTC0013U |

```python
data = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "KRX_FWDG_ORD_ORGNO": "",     # KRX 원주문번호
    "ORGN_ODNO": "00001234",       # 원래 주문번호
    "ORD_DVSN": "01",              # 주문구분
    "RVSE_CNCL_DVSN_CD": "02",    # 01: 정정, 02: 취소
    "ORD_QTY": "10",               # 주문수량
    "ORD_UNPR": "70000",           # 정정 시 새 가격
    "QTY_ALL_ORD_YN": "Y",         # 전량 여부 (Y/N)
    "EXCG_ID_DVSN_CD": "KRX"       # 거래소 구분
}
```

### 3.3 미체결 조회
- **Endpoint:** `GET /uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl`
- **TR ID:** `TTTC0084R`
- 정정/취소 가능한 미체결 주문 목록 조회

```python
params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "INQR_DVSN_1": "0",           # 조회구분1
    "INQR_DVSN_2": "0",           # 조회구분2
    "CTX_AREA_FK100": "",          # 연속조회 검색조건
    "CTX_AREA_NK100": ""           # 연속조회 키
}
# 페이지네이션: tr_cont 헤더 "M"/"F" 시 재귀 호출
# Response: output[] → 미체결 주문 리스트
```

### 3.4 잔고 조회
- **Endpoint:** `GET /uapi/domestic-stock/v1/trading/inquire-balance`

| 환경 | TR ID |
|------|-------|
| 실전 | TTTC8434R |
| 모의 | VTTC8434R |

```python
params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "AFHR_FLPR_YN": "N",          # 시간외단일가 여부
    "INQR_DVSN": "01",            # 조회구분 (01: 대출일별, 02: 종목별)
    "UNPR_DVSN": "01",            # 단가구분
    "FUND_STTL_ICLD_YN": "N",     # 펀드결제분 포함 여부
    "FNCG_AMT_AUTO_RDPT_YN": "N", # 융자금액 자동상환 여부
    "PRCS_DVSN": "00",            # 처리구분 (00: 전일매매포함)
    "CTX_AREA_FK100": "",
    "CTX_AREA_NK100": ""
}
# Response:
# output1[]: pdno(종목코드), prdt_name(종목명), hldg_qty(보유수량),
#            pchs_avg_pric(매입평균가), prpr(현재가), evlu_pfls_amt(평가손익)
# output2:   dnca_tot_amt(예수금총액), tot_evlu_amt(총평가금액)
```

### 3.5 체결 내역
- **Endpoint:** `GET /uapi/domestic-stock/v1/trading/inquire-daily-ccld`

| 구분 | 실전 TR ID | 모의 TR ID |
|------|-----------|-----------|
| 3개월 이내 | TTTC0081R | VTTC0081R |
| 3개월 이전 | CTSC9215R | VTSC9215R |

```python
params = {
    "CANO": cano,
    "ACNT_PRDT_CD": acnt_prdt_cd,
    "INQR_STRT_DT": "20260101",   # 조회시작일 (YYYYMMDD)
    "INQR_END_DT": "20260328",    # 조회종료일
    "SLL_BUY_DVSN_CD": "00",      # 00: 전체, 01: 매도, 02: 매수
    "CCLD_DVSN": "00",            # 00: 전체, 01: 체결, 02: 미체결
    "INQR_DVSN": "00",            # 조회구분
    "INQR_DVSN_3": "00",          # 조회구분3
    "PDNO": "",                    # 종목코드 (빈값=전체)
    "EXCG_ID_DVSN_CD": "KRX",
    "CTX_AREA_FK100": "",
    "CTX_AREA_NK100": ""
}
# Response:
# output1[]: 체결 내역 배열
# output2:   메타데이터
```

---

## TR ID 종합 테이블

| API | 실전 TR ID | 모의 TR ID | Method | 구현 여부 |
|-----|-----------|-----------|--------|----------|
| 토큰 발급 | - | - | POST | O |
| HashKey | - | - | POST | O |
| **해외** 현재가 | HHDFS00000300 | HHDFS00000300 | GET | O |
| **해외** 미국 매수 | TTTT1002U | VTTT1002U | POST | O |
| **해외** 미국 매도 | TTTT1006U | VTTT1006U | POST | O |
| **해외** 미체결 | TTTS3018R | VTTS3018R | GET | O |
| **해외** 잔고 | TTTS3012R | VTTS3012R | GET | O |
| **해외** 체결내역 | TTTS3035R | VTTS3035R | GET | X |
| **해외** 매수가능 | TTTS3007R | VTTS3007R | GET | X |
| **국내** 매수 | TTTC0012U | VTTC0012U | POST | X |
| **국내** 매도 | TTTC0011U | VTTC0011U | POST | X |
| **국내** 정정/취소 | TTTC0013U | VTTC0013U | POST | X |
| **국내** 미체결 | TTTC0084R | - | GET | X |
| **국내** 잔고 | TTTC8434R | VTTC8434R | GET | X |
| **국내** 체결내역 | TTTC0081R | VTTC0081R | GET | X |

## 거래소 코드 매핑 (해외주식)

해외주식은 현재가 API와 주문 API에서 거래소 코드가 다르므로 주의.
기존 구현: `_get_exchange_code()` at `broker.py:497`

| 거래소 | 현재가 API (`EXCD`) | 주문/잔고 API (`OVRS_EXCG_CD`) |
|--------|-------------------|-------------------------------|
| 나스닥 | NAS | NASD |
| 뉴욕 | NYS | NYSE |
| 아멕스 | AMS | AMEX |

국내주식은 거래소 코드 매핑 불필요 (`EXCG_ID_DVSN_CD: "KRX"` 고정).

## 국내주식 확장 가이드

`KisBrokerBase`를 확장하여 국내주식을 지원할 때의 핵심 차이점:

| 항목 | 해외주식 (현재) | 국내주식 (확장 시) |
|------|---------------|------------------|
| URL 경로 | `/uapi/overseas-stock/...` | `/uapi/domestic-stock/...` |
| TR ID 접두사 | `TTTT`/`TTTS` (실전), `VTTT`/`VTTS` (모의) | `TTTC` (실전), `VTTC` (모의) |
| 종목코드 | 티커 심볼 (`AAPL`) | 6자리 숫자 (`005930`) |
| 주문단가 | USD 소수점 2자리 (`"150.00"`) | KRW 정수 (`"70000"`) |
| 시장가 주문 | 미지원 (지정가만) | 지원 (`ORD_DVSN: "01"`) |
| 거래소 코드 | NASD/NYSE/AMEX 매핑 필요 | KRX 고정 |
| 주문 endpoint | `/trading/order` | `/trading/order-cash` |
| 잔고 응답 키 | `ovrs_pdno`, `ovrs_cblc_qty` | `pdno`, `hldg_qty` |
| 예수금 응답 키 | `ovrs_ord_psbl_amt` | `dnca_tot_amt` |

**구현 방식 권장:** `KisDomesticBrokerBase` 별도 클래스를 `KisBrokerBase`와 병렬로 생성하여 `IBrokerAdapter` 인터페이스 구현. 공통 인증/헤더 로직은 mixin 또는 공통 베이스로 추출 가능.
