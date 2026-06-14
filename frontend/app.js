/* 고문서 OCR 복원 — 프론트엔드 (빌드 없는 바닐라 JS) */
(() => {
  "use strict";

  const API = "/api";
  const $ = (id) => document.getElementById(id);

  let documents = [];          // 목록 캐시
  let selectedId = null;       // 현재 선택 문서
  let pollTimer = null;        // 목록 폴링 타이머
  let textDirty = false;       // 결과 편집 여부

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

  // ---- 업로드 --------------------------------------------------------
  function collectOptions() {
    const fd = new FormData();
    fd.append("lang", $("lang").value);
    fd.append("upscale", $("opt-upscale").checked);
    fd.append("denoise", $("opt-denoise").checked);
    fd.append("deskew", $("opt-deskew").checked);
    fd.append("binarize", $("opt-binarize").checked);
    fd.append("grayscale", $("opt-grayscale").checked);
    return fd;
  }

  async function uploadFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const fd = collectOptions();
    files.forEach((f) => fd.append("files", f));
    try {
      const out = await api("/documents", { method: "POST", body: fd });
      toast(`${out.created.length}개 문서 업로드됨`);
      await refresh();
      // 첫 업로드 문서를 자동 선택
      if (out.created[0]) selectDoc(out.created[0].id);
    } catch (e) {
      toast("업로드 실패: " + e.message, true);
    }
  }

  function setupDropzone() {
    const dz = $("dropzone");
    const input = $("file-input");
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      uploadFiles(input.files);
      input.value = "";
    });
    ["dragenter", "dragover"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((ev) =>
      dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
    );
    dz.addEventListener("drop", (e) => {
      if (e.dataTransfer?.files) uploadFiles(e.dataTransfer.files);
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
    if (selectedId !== id) textDirty = false;
    selectedId = id;
    renderList();
    await renderDetail();
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

    // 미리보기 (시그니처 바뀔 때만 갱신해 깜빡임 방지)
    const previewKey = `${doc.id}:${doc.preview_path || ""}`;
    if (previewKey !== lastDetailKey) {
      const box = $("preview-box");
      if (doc.preview_path) {
        box.innerHTML = `<img src="${API}/documents/${doc.id}/preview?t=${Date.now()}" alt="전처리 미리보기" />`;
      } else {
        box.innerHTML = '<span class="preview-placeholder">처리 후 표시됩니다</span>';
      }
      lastDetailKey = previewKey;
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
          s += '<br><span class="warn">●</span> 한글 병기 보정 꺼짐 — ANTHROPIC_API_KEY 설정 시 활성화';
        }
        el.innerHTML = s;
      } else {
        el.innerHTML = '<span class="warn">●</span> OCR 엔진 미설치 — 전처리만 동작 (pip install paddlepaddle paddleocr)';
      }
    } catch (_) {}
  }

  // ---- 시작 ----------------------------------------------------------
  function init() {
    setupDropzone();
    setupActions();
    loadEngineStatus();
    startPolling();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
