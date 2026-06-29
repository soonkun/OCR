# 고문서 OCR 복원

한국어+한자가 섞인 저화질 고문서(예: 1962년 농업과학 도서) 스캔본을
**전처리 → PaddleOCR(PP-OCRv5) → 다단 읽기순서 복원 → 한글 병기 보정**
파이프라인으로 처리하는 백엔드 + 빌드 없는 웹 프론트엔드.

여러 문서를 업로드해 관리하고, 처리 진행상황을 실시간 진행바로 확인하며,
페이지를 넘겨가며 이미지와 인식 결과를 대조해 편집·다운로드할 수 있습니다.

> 📘 **자세한 사용법** → [docs/USER_MANUAL.md](docs/USER_MANUAL.md)
> 🛠 **설계·기술 결정** → [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md)

## 주요 기능

- **원클릭 실행** — `고문서OCR-실행.bat` 더블클릭이면 기존 서버 정리 → 서버 시작
  → 브라우저 자동 열기까지 한 번에. cmd를 만질 필요가 없습니다.
- **전처리 파이프라인** (각 단계 on/off + 밝기·대비·감마·선명도·디노이즈 미세조정)
  - 흑백 변환 · 디노이즈 · 업스케일 · 기울기 보정(deskew) · 이진화(Sauvola)
  - 업로드 시 **페이지를 넘겨가며 미리보기**로 조정하고 **OCR 적합도(신뢰도) 측정** 가능
- **PaddleOCR(PP-OCRv5)** 문자 인식 — 언어 선택(한국어+한자/한국어/번체/간체/일본어/영어)
- **다단(多段) 읽기순서 복원** ⭐ — 2단·3단 세로조판을 텍스트 줄 박스의 x분포로 자동
  감지해 칸 좌→우·칸 안 위→아래 순으로 복원(사진·삽화가 많아도 견고).
- **한국어+한자 혼용 모드 + 한글 병기 보정** ⭐
  - 단일 모델로는 한글·한자를 동시에 못 읽으므로 **두 모델을 같이 돌려(듀얼패스)**
    한글·한자 후보를 모은 뒤, **LLM(OpenAI)이 합쳐 한글 병기 형식으로 보정**합니다.
  - 예: `農業의 發達을` → **`농업(農業)의 발달(發達)을`** (한글 독음을 앞에, 한자는 괄호)
  - 한자 독음은 문맥에 따라 달라지므로(樂→락/악/요) LLM이 문맥으로 정확히 잡습니다.
- **이미지 + PDF**(다중 페이지) 지원, **다중 문서 관리**(업로드·목록·삭제·재처리)
- **실시간 진행** — 진행바 + **현재 처리 중인 페이지가 미리보기에 표시**
- **결과 화면 페이지 넘김** — 완료 후 `◀ N/전체 ▶`로 넘기면 **왼쪽 이미지와 오른쪽
  텍스트가 같이 그 페이지로** 이동 → 대조하며 편집
- **좌우 크기 조절** — 미리보기↔결과 사이 막대를 드래그해 폭 조절(미리보기는 한 페이지
  통째로 폭맞춤). **글씨 크기**(90~130%)와 **첫 사용 안내 투어**(? 버튼)도 제공.

### 한글 병기 LLM 보정 켜기

한국어+한자 모드의 한글 병기 보정은 **OpenAI API 키**가 있어야 동작합니다
(키가 없으면 자동으로 신뢰도 기반 병합 폴백 — 한자가 병기 없이 그대로 출력됩니다).

가장 쉬운 방법은 프로젝트 폴더의 **`.env`** 파일에 키를 넣는 것입니다(자동 로드):

```ini
# .env  (.env.example 복사해서 사용. 이 파일은 git에 올라가지 않습니다)
OPENAI_API_KEY=sk-...
```

서버를 (재)시작하면 화면 좌하단에 **"한글 병기 LLM 보정 켜짐"** 으로 표시됩니다.
사용 모델은 `OCR_LLM_MODEL`(기본 `gpt-4o`)로 변경할 수 있습니다.

## 빠른 시작

### Windows — 원클릭 (권장)

1. 최초 1회만 `setup.bat` 실행(가상환경·의존성 설치). `고문서OCR-실행.bat`이 없으면
   자동으로 설치를 시도합니다.
2. **`고문서OCR-실행.bat` 더블클릭** → 브라우저에서 자동으로
   **http://localhost:8000/app/** 가 열립니다.

### 수동 실행 (모든 OS)

```bash
# 1. 핵심 의존성 설치
pip install -r requirements.txt

# 2. OCR 엔진 설치 (실제 문자 인식). 미설치 시에도 서버·전처리·미리보기는 동작.
pip install "paddlepaddle>=3.1" paddleocr
#  ⚠️ paddlepaddle 3.0.0 은 CPU PIR 추론 버그로 모델 로딩이 깨집니다. 반드시 3.1 이상.

# 3. 서버 실행
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 **http://localhost:8000/app/** 접속.

## 오프라인(인터넷 없는 환경) 사용

이 프로그램은 **모델을 한 번만 받으면 그 뒤로는 인터넷 없이** 동작합니다(LLM 병기 보정
제외 — 그건 OpenAI API 호출이 필요). PaddleOCR은 첫 실행 시 인식 모델을 내려받습니다.

```
Windows : C:\Users\<사용자>\.paddlex\official_models\
macOS/Linux : ~/.paddlex/official_models/
```

### 모델을 받지 못하는 망(방화벽 등)일 때 — 폴더 복사 우회법

1. 인터넷이 자유로운 다른 PC에서 이 프로그램을 한 번 실행해 작은 파일로 OCR을 돌립니다.
   → 모델이 위 `.paddlex/official_models` 폴더에 받아집니다.
2. 그 `.paddlex` 폴더를 USB로 복사해 차단된 PC의 `C:\Users\<사용자>\` 아래에 붙여넣습니다.
3. 이제 차단된 PC에서도 인터넷 없이 OCR이 동작합니다.

> 모델 다운로드 서버 지정(PowerShell): `$env:PADDLE_PDX_MODEL_SOURCE="HuggingFace"`
> (또는 `ModelScope`, `BOS`). 런처는 기본으로 `HuggingFace`를 사용합니다.

## 아키텍처

```
backend/
  main.py        FastAPI 앱 · REST API · 정적 프론트 서빙 · 프론트 no-cache 미들웨어
  config.py      경로/설정(.env 자동 로드)
  db.py          SQLite 문서 메타데이터 저장소 (목록/진행상황/결과)
  pipeline.py    백그라운드 처리: 로드 → 전처리 → OCR → (LLM 보정) → 저장
  preprocess.py  업스케일·디노이즈·deskew·이진화 + 톤(밝기·대비·감마·샤픈)
  ocr_engine.py  PaddleOCR 래퍼 (버전 호환 · 미설치 폴백)
  dual_ocr.py    한글+한자 듀얼패스 (줄 박스 매칭)
  layout.py      다단(N단) 읽기순서 복원 (텍스트 줄 박스 x분포 기반)
  llm_correct.py OpenAI 기반 한글 병기 후보정 (충실성 우선 프롬프트)
  preview.py     전처리 미세조정 미리보기(다중 페이지 · 토큰 캐시)
frontend/
  index.html · styles.css · app.js   빌드 없는 단일 페이지 앱(폴링 진행바, 투어,
                                      글씨크기, 페이지 넘김, 좌우 크기 조절)
data/            업로드·미리보기·DB (gitignore)
고문서OCR-실행.bat / start.bat        Windows 원클릭 런처
```

처리는 백그라운드 스레드풀에서 수행되고, 프론트엔드는 `/api/documents`를
주기적으로 폴링해 진행상황을 표시합니다.

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/documents` | 파일 업로드(다중) + 처리 시작 |
| `GET` | `/api/documents` | 문서 목록(진행상황 포함) |
| `GET` | `/api/documents/{id}` | 문서 상세(결과 텍스트·페이지 수 포함) |
| `GET` | `/api/documents/{id}/preview?page=N` | 전처리 미리보기(페이지 지정 가능) |
| `GET` | `/api/documents/{id}/download` | 결과 텍스트(.txt) 다운로드 |
| `PUT` | `/api/documents/{id}/text` | 편집한 결과 텍스트 저장 |
| `POST` | `/api/documents/{id}/retry` | 다시 처리 |
| `DELETE` | `/api/documents/{id}` | 문서 삭제(진행 중이면 OCR도 중단) |
| `POST` | `/api/preview/load` | 조정용 파일 캐시(토큰·총 페이지 수 발급) |
| `POST` | `/api/preview/render` | 토큰+페이지+파라미터로 전처리 미리보기 PNG |
| `POST` | `/api/preview/measure` | 중앙 일부만 OCR해 적합도(신뢰도) 측정 |
| `GET` | `/api/health` | 상태 · OCR 엔진/LLM 사용 가능 여부 |

## 환경 변수 (선택, `.env` 또는 시스템 환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | (없음) | 있으면 한글 병기 LLM 보정 활성화 |
| `OCR_LLM_MODEL` | `gpt-4o` | 보정에 쓸 OpenAI 모델 |
| `OCR_DEFAULT_LANG` | `korean+han` | 기본 인식 언어 |
| `OCR_VERSION` | `PP-OCRv5` | PaddleOCR 모델 버전 |
| `OCR_MAX_WORKERS` | `1` | 동시 처리 문서 수 |
| `OCR_DATA_DIR` | `./data` | 데이터 저장 경로 |
