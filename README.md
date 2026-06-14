# 고문서 OCR 복원

한국어+한자가 섞인 저화질 고문서(예: 옛 농업과학 도서) 스캔본을
**전처리 → PaddleOCR(PP-OCRv5) → 텍스트 복원** 파이프라인으로 처리하는
백엔드 + 간단한 웹 프론트엔드.

여러 문서를 업로드해 관리하고, 처리 진행상황을 실시간 진행바로 확인하며,
인식 결과를 편집·다운로드할 수 있습니다.

## 주요 기능

- **전처리 파이프라인** (각 단계 on/off 토글)
  - 흑백 변환 · 디노이즈 · 업스케일 · 기울기 보정(deskew) · 이진화(Sauvola)
- **PaddleOCR(PP-OCRv5)** 문자 인식 — 언어 선택(한국어/중국어/번체/일본어/영어)
- **이미지 + PDF**(다중 페이지) 지원
- **다중 문서 관리** — 업로드·목록·진행상황·삭제·재처리
- **진행바**로 단계별 상태 표시 (전처리 → 인식 → 완료)
- **전처리 미리보기** 이미지 + **결과 텍스트 편집/저장/다운로드**

> LLM 문장 보정(앞뒤 문맥으로 어색한 문장 복원)은 추후 추가 예정입니다.
> 파이프라인에 확장 포인트(`backend/pipeline.py`의 `LLM 보정 확장 포인트`
> 주석)가 준비되어 있습니다.

## 빠른 시작

```bash
# 1. 핵심 의존성 설치
pip install -r requirements.txt

# 2. (선택) 실제 문자 인식을 위해 OCR 엔진 설치 — 용량이 큽니다
#    미설치 시에도 서버는 동작하며 전처리/미리보기는 정상 수행됩니다.
pip install paddlepaddle paddleocr

# 3. 서버 실행
./run.sh
#  또는: uvicorn backend.main:app --reload
```

브라우저에서 **http://localhost:8000/app/** 접속.

## 아키텍처

```
backend/
  main.py        FastAPI 앱 · REST API · 정적 프론트 서빙
  config.py      경로/설정
  db.py          SQLite 문서 메타데이터 저장소 (목록/진행상황/결과)
  pipeline.py    백그라운드 처리: 로드 → 전처리 → OCR → 저장 (진행상황 갱신)
  preprocess.py  업스케일·디노이즈·deskew·이진화 (OpenCV / scikit-image)
  ocr_engine.py  PaddleOCR 래퍼 (+ 미설치 시 폴백)
frontend/
  index.html · styles.css · app.js   빌드 없는 단일 페이지 앱 (폴링 기반 진행바)
data/            업로드·미리보기·DB (gitignore)
```

처리는 백그라운드 스레드풀에서 수행되고, 프론트엔드는 `/api/documents`를
주기적으로 폴링해 진행상황을 표시합니다.

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/documents` | 파일 업로드(다중) + 처리 시작 |
| `GET` | `/api/documents` | 문서 목록(진행상황 포함) |
| `GET` | `/api/documents/{id}` | 문서 상세(결과 텍스트 포함) |
| `GET` | `/api/documents/{id}/preview` | 전처리 미리보기 이미지 |
| `GET` | `/api/documents/{id}/download` | 결과 텍스트(.txt) 다운로드 |
| `PUT` | `/api/documents/{id}/text` | 편집한 결과 텍스트 저장 |
| `POST` | `/api/documents/{id}/retry` | 다시 처리 |
| `DELETE` | `/api/documents/{id}` | 문서 삭제 |
| `GET` | `/api/health` | 상태 · OCR 엔진 설치 여부 |

## 환경 변수 (선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OCR_DEFAULT_LANG` | `korean` | 기본 인식 언어 |
| `OCR_VERSION` | `PP-OCRv5` | PaddleOCR 모델 버전 |
| `OCR_MAX_WORKERS` | `1` | 동시 처리 문서 수 |
| `OCR_DATA_DIR` | `./data` | 데이터 저장 경로 |
