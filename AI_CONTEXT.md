# AI 개발 컨텍스트 / 작업 히스토리

> 이 문서는 **나중에 AI(또는 사람)가 이 저장소를 이어받아 작업할 때** 참고하는 핸드오프 문서다.
> 코드만 봐선 알기 어려운 "왜 이렇게 했는지", 실측으로 검증된 결정, 알려진 한계,
> 다음에 할 일을 정리했다. (최종 갱신: 2026-06-15)

---

## 1. 프로젝트 목표

한글+한자가 섞인 **저화질 고문서**(예: 1962년 농촌진흥청 「技術과 訓練」)를
**현대 독자가 읽을 수 있는 텍스트로 복원**한다.

- 출력은 **한글 병기 형식**: 한자어를 `한글독음(漢字)`로 쓴다.
  예) 原文 `農業의 發達을` → `농업(農業)의 발달(發達)을`
- **원문 존중이 최우선**: 1962년 당시의 옛 표기·옛 표현을 함부로 현대화하지 않는다.
- 흐려서 안 보이는 글자는 문맥으로 유추하되, 추정·옛말은 **페이지별 `― 주석 ―`** 에 명시.

---

## 2. 처리 파이프라인 (기본 모드 `lang="korean+han"`)

`backend/pipeline.py` 의 `_process()` 가 페이지마다 다음을 수행한다:

1. **전처리** `preprocess.py` — 흑백·밝기·대비·감마·선명도·디노이즈·업스케일·기울기보정.
   **이진화(binarize)는 기본 OFF** (아래 §4 참조).
2. **2단 컬럼 분리** `layout.py` — 본문 영역 잉크 프로파일로 가운데 거터를 찾아 좌/우 칸으로
   나눠 OCR. 옛 학술지의 2단 조판에서 좌·우가 뒤섞이던 읽기 순서를 바로잡는다.
3. **듀얼패스 OCR** `dual_ocr.py` — 두 PaddleOCR 모델(한글/한자)을 칸마다 돌려 줄 단위로 정렬.
   (단일 모델이 한글·한자를 동시에 못 읽기 때문 — §4)
4. **LLM 보정** `llm_correct.py` — OpenAI(gpt-4o)가 두 OCR 후보를 종합해 **문단 단위**로 복원,
   한글 병기·옛표기 보존·주석. 토큰 절약 위해 여러 페이지를 묶어 호출.
   `OPENAI_API_KEY` 없으면 신뢰도 기반 폴백(병기 없는 원시 병합).

---

## 3. 제공자 / 모델

- **LLM 제공자: OpenAI** (2026-06-15에 Anthropic→OpenAI로 전환. 이유: 사용자의 Claude 결제가
  안 됨). 기본 모델 `gpt-4o`. `OCR_LLM_MODEL` 환경변수로 변경.
- 호출: `chat.completions`(스트리밍, `temperature=0`, `max_tokens=8000`).
- ⚠️ **GPT-5/o계열로 바꾸려면 코드 수정 필요**: 최신 모델은 `max_tokens` 대신
  `max_completion_tokens`를 요구하고 `temperature=0`을 거부하는 경우가 많다. 그냥 모델명만
  바꾸면 호출이 실패해 폴백된다. → `llm_correct._call()`을 모델 계열별로 분기해야 함.
- 비용: gpt-4o 기준 **페이지당 약 $0.03~0.04**. 빽빽한 본문 1쪽 ≈ OCR 후보 약 2,000자.

---

## 4. 실측으로 검증된 핵심 결정 (코드만 봐선 모르는 것)

- **단일 모델로 한글+한자 동시 인식 불가**: `korean` PP-OCRv5 사전 = 한글 11,172 / 한자 0.
  `chinese_cht`(→PP-OCRv6_medium_rec) = 한자 15,565 / 한글 0. → **듀얼패스가 유일한 방법**.
  한자 독음은 문맥마다 다르므로(樂=락/악/요) 단순 사전변환이 아니라 **LLM**이 필요.
- **이진화는 흐린 활자에 해롭다**: Sauvola/adaptive 이진화 시 OCR 고신뢰 줄이 **50→14로 폭락**.
  PP-OCRv5는 자연사진 학습 모델이라 그레이/컬러를 선호. → 기본 OFF, 얼룩 심할 때만 UI로 켬.
  (이건 "사람 눈에 선명 = OCR에 좋음"이 **틀리는** 대표 예외. 그래서 UI에 시각 미리보기 +
  OCR 신뢰도 측정 둘 다 제공.)
- **충실성 vs 환각**: 초기 프롬프트(창의적)는 1962 통화개혁을 GPT가 아는 지식으로 유창하게
  **지어냈다**. → 충실성 우선 프롬프트 + `temperature=0`으로 교정. 그래도 OCR이 너무 깨지면
  한계(GIGO)는 남는다. 일부 세부 숫자는 추정일 수 있어 원문 대조 권장.
- **2단 컬럼 분리가 가독성에 가장 큰 레버**였다. 절 번호(1→2→3)가 순서대로 복원됨.
- **Python 3.9 호환**: macOS 시스템 파이썬(3.9)에서 `main.py`의 FastAPI 폼 `str | None`(3.10+
  구문)이 런타임 평가에서 깨진다 → `eval_type_backport` 의존성으로 해결.
- **3채널 정규화** `ocr_engine._ensure_bgr`: 이진화/흑백(1채널) 이미지를 PaddleOCR에 넣으면
  깨지던 버그 수정. 입력을 항상 3채널 BGR로.

---

## 5. 프론트엔드 (`frontend/`, 빌드 없는 바닐라 JS)

- **전처리 미세조정 모달**: 파일 선택 → 슬라이더(밝기·대비·감마·선명도·디노이즈) + 토글로
  **실시간 미리보기**(원본/처리본 비교) + **"OCR 적합도 측정"**(중앙 일부만 빠르게 OCR해
  신뢰도 표시) → "이 설정으로 처리 시작". 서버 캐시 토큰으로 재업로드 없이 재처리.
- **라이트 모드 기본**. 진행바·문서목록·결과 편집/다운로드.
- 미리보기 엔드포인트: `/api/preview/load`, `/api/preview/render`, `/api/preview/measure`.

---

## 6. 실행 방법

- **macOS**: `./setup.sh` → `./run.sh` (또는 `고문서OCR-실행.command` 더블클릭)
- **Windows**: `setup.bat` 더블클릭(또는 `start.bat`이 venv 없으면 자동 설치 후 실행)
- **LLM 보정 켜기**: `cp/copy .env.example .env` 후 `.env`에 `OPENAI_API_KEY=sk-...`
- PaddleOCR은 첫 실행 시 모델 다운로드(이후 오프라인 가능). 윈도우는 paddle import 시
  **Microsoft Visual C++ 재배포 패키지**가 필요할 수 있음(흔한 함정).

---

## 7. 알려진 한계 / 다음에 할 일

- **OCR 속도**: CPU에서 페이지당 ~39초(server 검출모델). 110쪽이면 김. → 경량 mobile 검출모델/
  렌더 해상도 조정으로 속도 개선 여지.
- **GPT-5 평가 (보류됨)**: §3의 `_call` 강건화 후 같은 페이지로 gpt-4o vs gpt-5 A/B → 품질↔비용
  비교 필요. 추론모델은 충실성·독음 정확도에 유리할 가능성.
- **윈도우 실측 미완**: 크로스플랫폼으로 작성했으나 실제 윈도우 머신 테스트는 아직.
- **컬럼 분리**: 전폭 제목이 좌·우로 쪼개지는 경미한 문제(본문은 정상).
- **충실성의 대가**: OCR이 깨진 만큼 결과도 조각. 근본 개선은 OCR 품질(전처리·해상도·모델).

---

## 8. 파일 지도

```
backend/
  main.py        FastAPI: 업로드·문서 API·미리보기 엔드포인트·정적 서빙
  config.py      설정·경로·.env 자동로드·LLM/배치 파라미터
  pipeline.py    문서 처리 오케스트레이션(전처리→컬럼→OCR→LLM)
  preprocess.py  이미지 전처리 + 미세조정 파라미터
  layout.py      2단 컬럼(거터) 감지·분리
  dual_ocr.py    한글/한자 듀얼패스 OCR + 줄 정렬 + 폴백 병합
  ocr_engine.py  PaddleOCR 래퍼(_ensure_bgr, 줄 단위 추출)
  llm_correct.py OpenAI 한글 병기 보정(문단 재구성·주석·페이지 배치)
  preview.py     미세조정 미리보기 캐시·로더·크롭
  db.py          SQLite 문서 상태 저장
frontend/        index.html · app.js · styles.css (조정 모달 포함)
setup.sh/.bat    의존성 설치 (mac/win)
run.sh / start.bat / 고문서OCR-실행.command   실행 런처
.env.example     OPENAI_API_KEY 설정 템플릿 (복사해서 .env로)
```

## 9. 주요 환경변수

`OPENAI_API_KEY`(필수, LLM 보정), `OCR_LLM_MODEL`(기본 gpt-4o),
`OCR_LLM_BATCH_CHARS`(6000)·`OCR_LLM_BATCH_MAX_PAGES`(8),
`OCR_HANGUL_LANG`(korean)·`OCR_HANJA_LANG`(chinese_cht),
`PADDLE_PDX_MODEL_SOURCE`(HuggingFace), `OCR_DATA_DIR`, `OCR_MAX_WORKERS`.
