# 고문서 OCR 복원

한국어+한자가 섞인 저화질 고문서(예: 옛 농업과학 도서) 스캔본을
**전처리 → PaddleOCR(PP-OCRv5) → 텍스트 복원** 파이프라인으로 처리하는
백엔드 + 간단한 웹 프론트엔드.

여러 문서를 업로드해 관리하고, 처리 진행상황을 실시간 진행바로 확인하며,
인식 결과를 편집·다운로드할 수 있습니다.

## 주요 기능

- **전처리 파이프라인** (각 단계 on/off 토글)
  - 흑백 변환 · 디노이즈 · 업스케일 · 기울기 보정(deskew) · 이진화(Sauvola)
- **PaddleOCR(PP-OCRv5)** 문자 인식 — 언어 선택(한국어+한자/한국어/번체/간체/일본어/영어)
- **한국어+한자 혼용 모드 + 한글 병기 보정** ⭐
  - 단일 모델로는 한글·한자를 동시에 못 읽으므로 **두 모델을 같이 돌려(듀얼패스)**
    한글·한자 후보를 모은 뒤, **LLM(Claude)이 합쳐 한글 병기 형식으로 보정**합니다.
  - 예: `農業의 發達을` → **`농업(農業)의 발달(發達)을`** (한글 독음을 앞에, 한자는 괄호)
  - 한자 독음은 문맥에 따라 달라지므로(樂→락/악/요) LLM이 문맥으로 정확히 잡습니다.
- **이미지 + PDF**(다중 페이지) 지원
- **다중 문서 관리** — 업로드·목록·진행상황·삭제·재처리
- **진행바**로 단계별 상태 표시 (전처리 → 인식 → 보정 → 완료)
- **전처리 미리보기** 이미지 + **결과 텍스트 편집/저장/다운로드**

### 한글 병기 LLM 보정 켜기

한국어+한자 모드의 한글 병기 보정은 **Anthropic API 키**가 있어야 동작합니다
(키가 없으면 자동으로 신뢰도 기반 병합 폴백 — 한자가 병기 없이 그대로 출력됩니다).

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # macOS/Linux
setx ANTHROPIC_API_KEY "sk-ant-..."     # Windows (새 터미널부터 적용)
```

키를 설정하고 서버를 실행하면 화면 좌하단에 **"한글 병기 LLM 보정 켜짐"** 으로 표시됩니다.
사용 모델은 환경변수 `OCR_LLM_MODEL`(기본 `claude-opus-4-8`)로 변경할 수 있습니다.

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

## 오프라인(인터넷 없는 환경) 사용

이 프로그램은 **모델을 한 번만 받으면 그 뒤로는 인터넷 없이** 완전히 동작합니다.
PaddleOCR은 첫 실행 시 글자 인식 모델을 다운로드해 다음 폴더에 저장합니다.

```
Windows : C:\Users\<사용자>\.paddlex\official_models\
macOS/Linux : ~/.paddlex/official_models/
```

이 폴더만 있으면 인터넷이 차단된 PC에서도 OCR이 동작합니다.

### 모델을 받지 못하는 망(방화벽 등)일 때 — 폴더 복사 우회법

회사·학교처럼 모델 서버(HuggingFace/바이두 등)가 막힌 환경이라면:

1. **인터넷이 자유로운 다른 PC**(집·휴대폰 핫스팟에 연결한 PC 등)에서
   이 프로그램을 한 번 실행해 작은 파일로 OCR을 돌립니다.
   → 모델이 위 `.paddlex/official_models` 폴더에 받아집니다.
2. 그 **`.paddlex` 폴더를 USB로 복사**해 차단된 PC의
   `C:\Users\<사용자>\` 아래에 붙여넣습니다.
3. 이제 차단된 PC에서도 **인터넷 없이** OCR이 동작합니다.

> 모델 다운로드 서버를 지정하려면 실행 전 환경변수를 설정하세요(PowerShell):
> `$env:PADDLE_PDX_MODEL_SOURCE="HuggingFace"` (또는 `ModelScope`, `BOS`)

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
