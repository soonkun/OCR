/* 고문서 OCR 복원 — 프론트엔드 (빌드 없는 바닐라 JS) */
(() => {
  "use strict";

  const API = "/api";
  const $ = (id) => document.getElementById(id);

  let documents = [];          // 목록 캐시
  let selectedId = null;       // 현재 선택 문서
  let pollTimer = null;        // 목록 폴링 타이머
  let textDirty = false;       // 결과 편집 여부
  let detailPage = 0;          // 결과 화면에서 보고 있는 페이지(0-기반)
  let detailPages = 1;         // 현재 문서의 총 페이지 수

  // ---- 유틸 ----------------------------------------------------------
  const STATUS_LABEL = {
    queued: "대기 중",
    processing: "처리 중",
    done: "완료",
    error: "오류",
  };

  function toast(msg, isErr = false) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.toggle("err", isErr);
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (el.hidden = true), 2600);
  }

  async function api(path, opts = {}) {
    const res = await fetch(API + path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString("ko-KR", { month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit" });
  }

  // ---- 전처리 조정 + 업로드 ------------------------------------------
  let pendingFiles = [];       // 조정 중인 업로드 대기 파일
  let previewToken = null;     // 서버 캐시 토큰
  let renderTimer = null;      // 미리보기 디바운스
  let showRaw = false;         // 원본/처리본 탭
  let previewPages = 1;        // 미리보기 대상 파일의 총 페이지 수
  let previewPage = 0;         // 현재 보고 있는 페이지(0-기반)

  // 슬라이더 파라미터: id, 출력표시 id, 표시 포맷
  const PARAMS = {
    brightness: ["s-brightness", "v-brightness", (v) => `${+v}`],
    contrast: ["s-contrast", "v-contrast", (v) => (+v).toFixed(2)],
    gamma: ["s-gamma", "v-gamma", (v) => (+v).toFixed(2)],
    sharpen: ["s-sharpen", "v-sharpen", (v) => (+v).toFixed(1)],
    denoise_strength: ["s-denoise", "v-denoise", (v) => `${+v}`],
    sauvola_k: ["s-sauvola", "v-sauvola", (v) => (+v).toFixed(2)],
  };

  function readOptions() {
    const o = {
      grayscale: $("opt-grayscale").checked,
      upscale: $("opt-upscale").checked,
      deskew: $("opt-deskew").checked,
      binarize: $("opt-binarize").checked,
    };
    for (const k in PARAMS) o[k] = parseFloat($(PARAMS[k][0]).value);
    o.denoise = o.denoise_strength > 0;   // 세기 0이면 디노이즈 끔
    return o;
  }

  function syncOutputs() {
    for (const k in PARAMS) $(PARAMS[k][1]).textContent = PARAMS[k][2]($(PARAMS[k][0]).value);
    $("ctl-sauvola").hidden = !$("opt-binarize").checked;
  }

  function setProcTab(proc) {
    showRaw = !proc;
    $("tab-proc").classList.toggle("active", proc);
    $("tab-raw").classList.toggle("active", !proc);
    renderPreview();
  }

  function updatePageNav() {
    const nav = $("tune-pagenav");
    nav.hidden = previewPages <= 1;
    $("page-indicator").textContent = `${previewPage + 1} / ${previewPages}`;
    $("page-prev").disabled = previewPage <= 0;
    $("page-next").disabled = previewPage >= previewPages - 1;
  }

  function gotoPage(delta) {
    const next = Math.max(0, Math.min(previewPages - 1, previewPage + delta));
    if (next === previewPage) return;
    previewPage = next;
    updatePageNav();
    $("measure-result").textContent = "";  // 페이지 바뀌면 이전 측정값 지움
    renderPreview();
  }

  async function renderPreview() {
    if (!previewToken) return;
    $("tune-spin").hidden = false;
    const body = showRaw ? { token: previewToken, page: previewPage, raw: true }
                         : { token: previewToken, page: previewPage, ...readOptions() };
    try {
      const res = await fetch(API + "/preview/render", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).detail) || res.statusText);
      const url = URL.createObjectURL(await res.blob());
      const img = $("tune-img");
      if (img._url) URL.revokeObjectURL(img._url);
      img._url = url; img.src = url;
    } catch (e) {
      toast("미리보기 실패: " + e.message, true);
    } finally {
      $("tune-spin").hidden = true;
    }
  }

  function scheduleRender() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => { if (!showRaw) renderPreview(); }, 300);
  }

  async function measure() {
    if (!previewToken) return;
    $("measure-result").textContent = "측정 중…";
    try {
      const r = await api("/preview/measure", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: previewToken, page: previewPage, ...readOptions() }),
      });
      $("measure-result").innerHTML =
        `평균 신뢰도 <b>${r.mean_score}</b> · 고신뢰 ${r.high_conf}/${r.lines}줄`
        + (r.sample ? `<br><span style="opacity:.7">“${escapeHtml(r.sample)}”</span>` : "");
    } catch (e) {
      $("measure-result").textContent = "측정 실패: " + e.message;
    }
  }

  function resetParams() {
    const d = { "s-brightness": 0, "s-contrast": 1.0, "s-gamma": 1.0,
                "s-sharpen": 0, "s-denoise": 10, "s-sauvola": 0.2 };
    for (const id in d) $(id).value = d[id];
    $("opt-grayscale").checked = true; $("opt-upscale").checked = true;
    $("opt-deskew").checked = true; $("opt-binarize").checked = false;
    syncOutputs(); scheduleRender();
  }

  function closeTune() {
    $("tune-modal").hidden = true;
    pendingFiles = []; previewToken = null;
    previewPages = 1; previewPage = 0;
  }

  async function openTune(fileList) {
    pendingFiles = [...fileList];
    if (!pendingFiles.length) return;
    const f0 = pendingFiles[0];
    $("tune-sub").textContent = pendingFiles.length > 1
      ? `${f0.name} 외 ${pendingFiles.length - 1}개 — 첫 장으로 설정을 맞춥니다`
      : f0.name;
    $("measure-result").textContent = "";
    $("tune-modal").hidden = false;
    $("tab-proc").classList.add("active"); $("tab-raw").classList.remove("active");
    showRaw = false;
    $("tune-img").removeAttribute("src");
    previewPages = 1; previewPage = 0; updatePageNav();
    try {
      const fd = new FormData(); fd.append("file", f0);
      const r = await api("/preview/load", { method: "POST", body: fd });
      previewToken = r.token;
      previewPages = r.pages || 1; previewPage = 0;
      updatePageNav();
      renderPreview();
    } catch (e) {
      toast("미리보기 로드 실패: " + e.message, true);
      closeTune();
    }
  }

  async function startProcessing() {
    if (!pendingFiles.length) return;
    const fd = new FormData();
    fd.append("lang", $("lang").value);
    fd.append("options", JSON.stringify(readOptions()));
    pendingFiles.forEach((f) => fd.append("files", f));
    try {
      const out = await api("/documents", { method: "POST", body: fd });
      toast(`${out.created.length}개 문서 업로드됨`);
      closeTune();
      await refresh();
      if (out.created[0]) selectDoc(out.created[0].id);
    } catch (e) {
      toast("업로드 실패: " + e.message, true);
    }
  }

  function setupTune() {
    for (const k in PARAMS)
      $(PARAMS[k][0]).addEventListener("input", () => { syncOutputs(); scheduleRender(); });
    ["opt-grayscale", "opt-upscale", "opt-deskew", "opt-binarize"].forEach((id) =>
      $(id).addEventListener("change", () => { syncOutputs(); scheduleRender(); }));
    $("tab-proc").onclick = () => setProcTab(true);
    $("tab-raw").onclick = () => setProcTab(false);
    $("page-prev").onclick = () => gotoPage(-1);
    $("page-next").onclick = () => gotoPage(1);
    $("btn-measure").onclick = measure;
    $("btn-reset").onclick = resetParams;
    $("tune-close").onclick = closeTune;
    $("tune-cancel").onclick = closeTune;
    $("tune-start").onclick = startProcessing;
    syncOutputs();
  }

  function setupDropzone() {
    const dz = $("dropzone");
    const input = $("file-input");
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      openTune(input.files);
      input.value = "";
    });
    ["dragenter", "dragover"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
    );
    dz.addEventListener("drop", (e) => {
      if (e.dataTransfer?.files) openTune(e.dataTransfer.files);
    });
  }

  // ---- 목록 렌더링 ---------------------------------------------------
  function renderList() {
    const list = $("doc-list");
    $("doc-count").textContent = documents.length;
    list.innerHTML = "";
    if (!documents.length) {
      list.innerHTML = '<p style="font-size:12px;color:var(--text-dim);text-align:center;padding:14px 0">아직 문서가 없습니다.</p>';
      return;
    }
    for (const doc of documents) {
      const card = document.createElement("div");
      card.className = "doc-card" + (doc.id === selectedId ? " active" : "");
      card.onclick = () => selectDoc(doc.id);
      card.innerHTML = `
        <div class="name">${escapeHtml(doc.filename)}</div>
        <div class="row">
          <span class="status-dot s-${doc.status}"></span>
          <div class="mini-track"><div class="mini-bar" style="width:${doc.progress}%"></div></div>
        </div>`;
      list.appendChild(card);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---- 상세 보기 -----------------------------------------------------
  async function selectDoc(id) {
    if (selectedId !== id) { textDirty = false; detailPage = 0; }
    selectedId = id;
    renderList();
    await renderDetail();
  }

  function scrollResultToPage(pageNum) {
    const ta = $("d-text");
    const idx = ta.value.indexOf(`──── ${pageNum}페이지 ────`);
    if (idx < 0) return;
    const line = ta.value.slice(0, idx).split("\n").length - 1;
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 20;
    ta.scrollTop = Math.max(0, line * lh - 8);
  }

  function gotoDetailPage(delta) {
    const next = Math.max(0, Math.min(detailPages - 1, detailPage + delta));
    if (next === detailPage) return;
    detailPage = next;
    $("preview-box").innerHTML =
      `<img src="${API}/documents/${selectedId}/preview?page=${detailPage}&t=${Date.now()}" alt="미리보기" />`;
    lastDetailKey = `${selectedId}:p${detailPage}`;
    $("d-page-indicator").textContent = `${detailPage + 1} / ${detailPages}`;
    $("d-page-prev").disabled = detailPage <= 0;
    $("d-page-next").disabled = detailPage >= detailPages - 1;
    scrollResultToPage(detailPage + 1);  // 오른쪽 텍스트를 해당 페이지로 스크롤
  }

  let lastDetailKey = "";  // 불필요한 재렌더 방지용 시그니처

  async function renderDetail() {
    if (!selectedId) {
      $("empty-state").hidden = false;
      $("detail-view").hidden = true;
      return;
    }
    let doc;
    try {
      doc = await api(`/documents/${selectedId}`);
    } catch (e) {
      $("empty-state").hidden = false;
      $("detail-view").hidden = true;
      selectedId = null;
      return;
    }

    $("empty-state").hidden = true;
    $("detail-view").hidden = false;

    $("d-title").textContent = doc.filename;
    const meta = [];
    meta.push(STATUS_LABEL[doc.status] || doc.status);
    if (doc.pages > 1) meta.push(`${doc.pages}페이지`);
    meta.push(`언어: ${doc.lang}`);
    if (doc.created_at) meta.push(fmtTime(doc.created_at));
    $("d-meta").textContent = meta.join("  ·  ");

    // 진행바
    $("d-progress").style.width = `${doc.progress}%`;
    $("d-stage").textContent = doc.status === "error"
      ? (doc.error || "오류 발생") : doc.stage;
    $("d-progress-wrap").style.opacity = doc.status === "done" ? "0.5" : "1";

    // 버튼 상태
    $("btn-retry").hidden = !(doc.status === "error" || doc.status === "done");
    $("btn-download").hidden = doc.status !== "done";
    $("btn-save-text").hidden = doc.status !== "done";

    // 미리보기 + 결과 화면 페이지 넘김 (시그니처 바뀔 때만 갱신해 깜빡임 방지)
    const pages = doc.pages || 1;
    detailPages = pages;
    const nav = $("d-pagenav");
    const box = $("preview-box");
    if (doc.status === "done" && pages > 1) {
      // 완료 + 여러 페이지: 선택한 페이지 이미지 + 넘김 버튼(이미지↔텍스트 대조).
      if (detailPage >= pages) detailPage = pages - 1;
      if (detailPage < 0) detailPage = 0;
      nav.hidden = false;
      $("d-page-indicator").textContent = `${detailPage + 1} / ${pages}`;
      $("d-page-prev").disabled = detailPage <= 0;
      $("d-page-next").disabled = detailPage >= pages - 1;
      const key = `${doc.id}:p${detailPage}`;
      if (key !== lastDetailKey) {
        box.innerHTML = `<img src="${API}/documents/${doc.id}/preview?page=${detailPage}&t=${Date.now()}" alt="미리보기" />`;
        lastDetailKey = key;
      }
    } else {
      // 처리 중에는 진행률을 키에 넣어 매 폴링마다 현재 처리 페이지를 받아온다.
      nav.hidden = true;
      const key = `${doc.id}:${doc.preview_path || ""}:`
        + (doc.status === "done" ? "done" : Math.round(doc.progress));
      if (key !== lastDetailKey) {
        if (doc.preview_path) {
          box.innerHTML = `<img src="${API}/documents/${doc.id}/preview?t=${Date.now()}" alt="전처리 미리보기" />`;
        } else {
          box.innerHTML = '<span class="preview-placeholder">처리 후 표시됩니다</span>';
        }
        lastDetailKey = key;
      }
    }

    // 결과 텍스트 (사용자가 편집 중이면 덮어쓰지 않음)
    const ta = $("d-text");
    if (!textDirty) ta.value = doc.text || "";
  }

  // ---- 액션 ----------------------------------------------------------
  function setupActions() {
    $("btn-delete").onclick = async () => {
      if (!selectedId) return;
      if (!confirm("이 문서를 삭제할까요?")) return;
      try {
        await api(`/documents/${selectedId}`, { method: "DELETE" });
        selectedId = null;
        lastDetailKey = "";
        await refresh();
        await renderDetail();
        toast("삭제되었습니다");
      } catch (e) { toast("삭제 실패: " + e.message, true); }
    };

    $("btn-retry").onclick = async () => {
      if (!selectedId) return;
      try {
        await api(`/documents/${selectedId}/retry`, { method: "POST" });
        textDirty = false;
        lastDetailKey = "";
        toast("다시 처리합니다");
        await refresh();
      } catch (e) { toast("실패: " + e.message, true); }
    };

    $("btn-download").onclick = () => {
      if (selectedId) window.location = `${API}/documents/${selectedId}/download`;
    };

    $("d-page-prev").onclick = () => gotoDetailPage(-1);
    $("d-page-next").onclick = () => gotoDetailPage(1);

    $("d-text").addEventListener("input", () => { textDirty = true; });

    $("btn-save-text").onclick = async () => {
      if (!selectedId) return;
      try {
        await api(`/documents/${selectedId}/text`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: $("d-text").value }),
        });
        textDirty = false;
        toast("저장되었습니다");
      } catch (e) { toast("저장 실패: " + e.message, true); }
    };
  }

  // ---- 폴링 ----------------------------------------------------------
  async function refresh() {
    try {
      documents = await api("/documents");
      renderList();
      // 선택된 문서가 처리 중이면 상세도 갱신
      const cur = documents.find((d) => d.id === selectedId);
      if (cur && cur.status !== "done") await renderDetail();
      else if (cur && cur.status === "done") await renderDetail();
    } catch (_) { /* 일시적 네트워크 오류 무시 */ }
  }

  function startPolling() {
    const tick = async () => {
      const anyActive = documents.some(
        (d) => d.status === "processing" || d.status === "queued");
      await refresh();
      // 진행 중인 작업이 있으면 빠르게, 없으면 느리게 폴링
      const interval = anyActive ? 1000 : 4000;
      pollTimer = setTimeout(tick, interval);
    };
    tick();
  }

  async function loadEngineStatus() {
    try {
      const h = await api("/health");
      const el = $("engine-status");
      if (h.paddle_available) {
        let s = '<span class="ok">●</span> OCR 엔진 준비됨 (PP-OCRv5)';
        if (h.llm_available) {
          s += '<br><span class="ok">●</span> 한글 병기 LLM 보정 켜짐';
        } else {
          s += '<br><span class="warn">●</span> 한글 병기 보정 꺼짐 — OPENAI_API_KEY 설정 시 활성화';
        }
        el.innerHTML = s;
      } else {
        el.innerHTML = '<span class="warn">●</span> OCR 엔진 미설치 — 전처리만 동작 (pip install paddlepaddle paddleocr)';
      }
    } catch (_) {}
  }

  // ---- 첫 사용 안내 투어 ---------------------------------------------
  const TOUR_KEY = "ocr_tour_v1";   // 이 값이 'done'이면 자동으로 다시 띄우지 않음
  const TOUR_STEPS = [
    { sel: null, place: "center",
      title: "고문서 OCR 복원에 오신 걸 환영합니다",
      text: "저화질 고문서 스캔본을 텍스트로 복원하는 도구예요. 30초만에 사용법을 안내할게요." },
    { sel: "#dropzone", place: "right",
      title: "① 파일 올리기",
      text: "여기에 이미지·PDF를 끌어다 놓거나 클릭해 선택하세요. 여러 개도 한 번에 됩니다." },
    { sel: "#lang", place: "right",
      title: "② 인식 언어 선택",
      text: "‘한국어+한자(한글 병기)’ 등 문서에 맞는 언어를 고르세요. 한자는 한글 독음과 함께 보정됩니다." },
    { sel: "#doc-list", place: "right",
      title: "③ 진행 상황 확인",
      text: "업로드한 문서가 여기 쌓이고, 전처리→인식→보정 진행률을 실시간으로 볼 수 있어요." },
    { sel: "#detail", place: "left",
      title: "④ 결과 보기·편집",
      text: "문서를 누르면 전처리 미리보기와 인식 결과가 여기 표시돼요. 직접 고치고 TXT로 내려받을 수 있습니다." },
    { sel: null, place: "center",
      title: "준비 끝!",
      text: "파일을 올리면 전처리 조정 화면이 열려요. 미리보기를 보며 다듬은 뒤 ‘처리 시작’을 누르면 됩니다. 이 안내는 상단 ? 버튼으로 다시 볼 수 있어요." },
  ];
  let tourIdx = 0;

  function positionTour(step) {
    const tour = $("tour"), spot = $("tour-spot"), pop = $("tour-pop"), arrow = $("tour-arrow");
    // body{zoom}이 걸리면 getBoundingClientRect 는 화면(zoom 반영) 좌표를 주지만,
    // position:fixed 자식의 left/top 은 zoom 이전(로컬) 좌표로 해석된다. 어긋나지
    // 않도록 화면 좌표·뷰포트를 z로 나눠 로컬 좌표로 변환해 계산한다.
    const z = parseFloat(getComputedStyle(document.body).zoom) || 1;
    const vw = innerWidth / z, vh = innerHeight / z;
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    const target = step.sel ? document.querySelector(step.sel) : null;
    if (!target) {            // 환영/마무리: 가운데 정렬 + 전체 어둡게
      tour.classList.add("tour-center");
      spot.hidden = true;
      arrow.className = "tour-arrow hidden";
      pop.style.left = `${(vw - pw) / 2}px`;
      pop.style.top = `${(vh - ph) / 2}px`;
      return;
    }
    tour.classList.remove("tour-center");
    spot.hidden = false;
    const b = target.getBoundingClientRect();
    const rl = b.left / z, rt = b.top / z, rw = b.width / z, rh = b.height / z;
    const rr = rl + rw, rb = rt + rh, rcx = rl + rw / 2, rcy = rt + rh / 2;
    const pad = 6;
    spot.style.left = `${rl - pad}px`;
    spot.style.top = `${rt - pad}px`;
    spot.style.width = `${rw + pad * 2}px`;
    spot.style.height = `${rh + pad * 2}px`;

    // 말풍선을 타깃 옆 빈 곳에 배치(우선 place, 공간 없으면 자동 폴백)
    const gap = 18;
    let left, top, dir;
    if (step.place === "left" && rl - gap - pw > 8) {
      left = rl - gap - pw; top = rcy - ph / 2; dir = "right";
    } else if (rr + gap + pw < vw - 8) {
      left = rr + gap; top = rcy - ph / 2; dir = "left";
    } else if (rb + gap + ph < vh - 8) {
      left = rcx - pw / 2; top = rb + gap; dir = "up";
    } else {
      left = rcx - pw / 2; top = rt - gap - ph; dir = "down";
    }
    left = Math.max(12, Math.min(left, vw - pw - 12));
    top = Math.max(12, Math.min(top, vh - ph - 12));
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;

    // 화살표: 방향 클래스(-16px 오프셋은 CSS) + 타깃 중심에 맞춘 수직/수평 위치
    arrow.className = `tour-arrow ${dir}`;
    arrow.style.top = arrow.style.bottom = arrow.style.left = arrow.style.right = "";
    if (dir === "left" || dir === "right") {
      const ay = Math.max(12, Math.min(rcy - top - 8, ph - 28));
      arrow.style.top = `${ay}px`;
    } else {
      const ax = Math.max(12, Math.min(rcx - left - 8, pw - 28));
      arrow.style.left = `${ax}px`;
    }
  }

  function showTourStep() {
    const step = TOUR_STEPS[tourIdx];
    $("tour-step").textContent = `${tourIdx + 1} / ${TOUR_STEPS.length}`;
    $("tour-title").textContent = step.title;
    $("tour-text").textContent = step.text;
    $("tour-prev").style.visibility = tourIdx === 0 ? "hidden" : "visible";
    $("tour-next").textContent = tourIdx === TOUR_STEPS.length - 1 ? "시작하기" : "다음";
    positionTour(step);
  }

  function startTour(force) {
    if (!force && localStorage.getItem(TOUR_KEY) === "done") return;
    tourIdx = 0;
    $("tour").hidden = false;
    showTourStep();
  }

  function endTour() {
    $("tour").hidden = true;
    try { localStorage.setItem(TOUR_KEY, "done"); } catch (_) {}
  }

  function setupTour() {
    $("tour-next").onclick = () =>
      (tourIdx >= TOUR_STEPS.length - 1) ? endTour() : (tourIdx++, showTourStep());
    $("tour-prev").onclick = () => { if (tourIdx > 0) { tourIdx--; showTourStep(); } };
    $("tour-skip").onclick = endTour;
    $("help-btn").onclick = () => startTour(true);
    addEventListener("resize", () => { if (!$("tour").hidden) positionTour(TOUR_STEPS[tourIdx]); });
  }

  // ---- 글씨 크기(UI 배율) -------------------------------------------
  const SCALE_KEY = "ocr_ui_scale";   // 저장 단위: 퍼센트(예: 110)
  const SCALE_MIN = 90, SCALE_MAX = 130, SCALE_STEP = 5;

  function applyScale(pct) {
    pct = Math.max(SCALE_MIN, Math.min(SCALE_MAX, Math.round(pct / SCALE_STEP) * SCALE_STEP));
    // body{zoom:var(--ui-zoom)} + .app 높이 보정이 이 변수를 함께 따라간다.
    document.documentElement.style.setProperty("--ui-zoom", pct / 100);
    $("scale-range").value = pct;
    $("scale-val").textContent = `${pct}%`;
    try { localStorage.setItem(SCALE_KEY, pct); } catch (_) {}
    // 투어가 떠 있으면 새 배율에 맞춰 위치를 다시 잡는다.
    if (!$("tour").hidden) positionTour(TOUR_STEPS[tourIdx]);
  }

  function setupScale() {
    const saved = parseInt(localStorage.getItem(SCALE_KEY) || "110", 10);
    $("scale-range").addEventListener("input", (e) => applyScale(parseInt(e.target.value, 10)));
    $("scale-down").onclick = () => applyScale(parseInt($("scale-range").value, 10) - SCALE_STEP);
    $("scale-up").onclick = () => applyScale(parseInt($("scale-range").value, 10) + SCALE_STEP);
    applyScale(Number.isFinite(saved) ? saved : 110);
  }

  // ---- 미리보기 ↔ 결과 좌우 크기 조절(드래그 구분선) ----------------
  const SPLIT_KEY = "ocr_split_pct";   // 왼쪽(미리보기) 칸 폭 비율(%)

  function setupSplitter() {
    const panes = $("panes"), left = $("preview-pane"), divider = $("pane-divider");
    const saved = parseFloat(localStorage.getItem(SPLIT_KEY));
    if (Number.isFinite(saved)) left.style.flex = `0 0 ${saved}%`;

    let dragging = false;
    const onMove = (e) => {
      if (!dragging) return;
      const rect = panes.getBoundingClientRect();
      let pct = ((e.clientX - rect.left) / rect.width) * 100;
      pct = Math.max(20, Math.min(78, pct));   // 양쪽이 사라지지 않게 제한
      left.style.flex = `0 0 ${pct}%`;
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      divider.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      const rect = panes.getBoundingClientRect();
      const pct = (left.getBoundingClientRect().width / rect.width) * 100;
      try { localStorage.setItem(SPLIT_KEY, pct.toFixed(1)); } catch (_) {}
    };
    divider.addEventListener("mousedown", (e) => {
      dragging = true;
      divider.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    // 더블클릭으로 50:50 초기화
    divider.addEventListener("dblclick", () => {
      left.style.flex = "1 1 0";
      try { localStorage.removeItem(SPLIT_KEY); } catch (_) {}
    });
  }

  // ---- 시작 ----------------------------------------------------------
  function init() {
    setupDropzone();
    setupTune();
    setupActions();
    setupTour();
    setupScale();
    setupSplitter();
    loadEngineStatus();
    startPolling();
    // 레이아웃이 안정된 뒤 첫 사용자에게 안내 투어를 띄운다.
    setTimeout(() => startTour(false), 400);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
