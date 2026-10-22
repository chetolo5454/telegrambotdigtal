// Case Tracker Web Application Logic

const state = {
  requests: [],
  names: {},
  changes: {},
  counts: {},
  filter: "fees",
  search: "",
  auth: null,
  settings: { auto_refresh_minutes: 10 },
  countdownSecs: 0,
  countdownTimer: null,
  loginPollTimer: null,
  auditEntries: []
};

const GROUPS_DEF = [
  { k: "fees", t: "تقدير ودفع الرسوم", f: (r) => r.caseCode === "202" || r.caseCode === "203", always: true },
  { k: "202", t: "تم تقدير الرسوم", f: (r) => r.caseCode === "202" },
  { k: "203", t: "تم دفع الرسوم", f: (r) => r.caseCode === "203" },
  { k: "201", t: "تحت المراجعة", f: (r) => r.caseCode === "201" },
  { k: "204", t: "قُيدت في جدول المحكمة", f: (r) => r.caseCode === "204" },
  { k: "207", t: "إبلاغ المحامي", f: (r) => r.caseCode === "207" },
  { k: "210", t: "غير مستوفي", f: (r) => r.caseCode === "210" },
  { k: "draft", t: "مسودات", f: (r) => r.stepCode === "1" },
  { k: "cancel", t: "ملغاة", f: (r) => r.stepCode === "6" },
  { k: "all", t: "الكل", f: () => true, always: true },
  { k: "unnamed", t: "بدون اسم", f: (r) => !state.names[r.requestNumber] }
];

const $ = (id) => document.getElementById(id);

// Toast Feedback
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

// Copy to Clipboard helper
function copyText(text, successMsg) {
  navigator.clipboard.writeText(text).then(() => {
    toast(successMsg || "تم النسخ بنجاح");
  }).catch(() => {
    toast("تعذّر النسخ إلى الحافظة");
  });
}

// Badge color mapping
function getBadgeClass(caseCode) {
  const map = {
    "202": "warn",
    "203": "ok",
    "204": "blue",
    "207": "purple",
    "210": "bad",
    "201": "info"
  };
  return map[caseCode] || "gray";
}

// Fetch Initial Data
async function loadData() {
  try {
    const res = await fetch("/api/requests");
    const data = await res.json();
    if (data.ok) {
      state.requests = data.requests || [];
      state.names = data.names || {};
      state.changes = data.changes || {};
      state.counts = data.counts || {};
      if (data.settings) {
        state.settings = data.settings;
        $("autoRefresh").value = String(state.settings.auto_refresh_minutes || 0);
      }
      render();
    }
  } catch (err) {
    console.error("Load error:", err);
  }
  checkAuthStatus();
}

// Check Session & Auth Status
async function checkAuthStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.ok) {
      state.auth = data.auth;
      updateAuthUI(data);
    }
  } catch (err) {
    console.error("Status check error:", err);
  }
}

function updateAuthUI(statusData) {
  const auth = statusData.auth || {};
  const dot = $("sessionStatusDot");
  const loginText = $("loginBtnText");
  const detail = $("sessionStatusDetail");
  const errBanner = $("errBanner");

  if (auth.logged_in) {
    dot.className = "status-dot online";
    loginText.textContent = "الجلسة نشطة";
    errBanner.style.display = "none";

    let remaining = "";
    if (auth.access_seconds_left > 0) {
      const mins = Math.round(auth.access_seconds_left / 60);
      remaining = ` (متبقي ${mins} دقيقة)`;
    }
    detail.textContent = `حساب: ${auth.user_phone || auth.user_nid || "مصر الرقمية"}${remaining}`;
  } else {
    dot.className = "status-dot offline";
    loginText.textContent = "تسجيل الدخول";
    detail.textContent = "غير متصل بالمنصة";
    $("errBannerMsg").textContent = "لم يتم تسجيل الدخول بعد أو انتهت صلاحية الجلسة. اضغط لتسجيل الدخول.";
    errBanner.style.display = "flex";
  }

  // Update modal session card
  $("modalSessionState").textContent = auth.logged_in ? "متصل بالمنصة" : "غير مسجل الدخول";
  $("modalUserNid").textContent = auth.user_nid || auth.user_phone || "—";
  $("modalExpiresIn").textContent = auth.access_seconds_left > 0
    ? `${Math.round(auth.access_seconds_left / 60)} دقيقة (يتجدد تلقائياً)`
    : "منتهي الصلاحية";

  // Update credentials card if present
  if (statusData.credentials) {
    state.credentials = statusData.credentials;
    if ($("modalCredPhone")) {
      $("modalCredPhone").textContent = statusData.credentials.phone || "—";
    }
    if ($("modalCredPass")) {
      $("modalCredPass").textContent = statusData.credentials.has_login_info
        ? "محفوظة وموجودة بملف login info.text ✅"
        : "غير موجودة بملف login info.text ❌";
    }
    if ($("modalTokenFileStatus")) {
      if (statusData.credentials.has_token_file) {
        $("modalTokenFileStatus").textContent = statusData.credentials.token_file_valid
          ? "يوجد توكن ساري المفعول داخل token.text ✅"
          : "يوجد ملف token.text (صلاحية التوكن منتهية) ⚠️";
      } else {
        $("modalTokenFileStatus").textContent = "الملف غير موجود";
      }
    }
  }

  // Header quick auto-login button label
  if ($("autoLoginHeaderBtnText")) {
    $("autoLoginHeaderBtnText").textContent = auth.logged_in
      ? "تجديد التوكن (بضغطة زر)"
      : "جلب التوكن بضغطة زر";
  }

  // Last fetched
  if (statusData.last_fetched_cairo) {
    $("syncStatus").textContent = `آخر تحديث ناجح: ${statusData.last_fetched_cairo} — إجمالي الطلبات: ${statusData.requests_count}`;
  }
}

// Refresh from Platform API
async function triggerRefresh() {
  const btn = $("refreshBtn");
  const btnText = $("refreshBtnText");
  btn.disabled = true;
  btnText.textContent = "جارٍ التحديث…";

  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      state.requests = data.requests || [];
      state.names = data.names || {};
      state.changes = data.changes || {};
      toast(data.new_changes_count ? `تم التحديث: تم رصد ${data.new_changes_count} تغيير جديد` : "تم التحديث بنجاح");
      render();
    } else {
      toast("تعذّر التحديث: " + (data.message || data.error));
      $("errBannerMsg").textContent = data.message || data.error;
      $("errBanner").style.display = "flex";
    }
  } catch (err) {
    toast("خطأ في الاتصال: " + err.message);
  } finally {
    btn.disabled = false;
    btnText.textContent = "تحديث الآن";
    resetCountdown();
    checkAuthStatus();
  }
}

// Render Filter Chips
function renderChips() {
  const container = $("filterChips");
  container.innerHTML = "";

  GROUPS_DEF.forEach((g) => {
    let count = 0;
    if (g.k === "unnamed") {
      count = state.requests.filter((r) => !state.names[r.requestNumber]).length;
    } else {
      count = state.requests.filter(g.f).length;
    }

    if (!count && !g.always) return;

    const btn = document.createElement("button");
    btn.className = "chip" + (state.filter === g.k ? " active" : "");
    btn.innerHTML = `${g.t} <small>(${count})</small>`;
    btn.onclick = () => {
      state.filter = g.k;
      render();
    };
    container.appendChild(btn);
  });
}

// Render Cases Table Rows
function renderRows() {
  const tbody = $("tableRows");
  tbody.innerHTML = "";

  const q = state.search.trim().toLowerCase();
  const currentGroup = GROUPS_DEF.find((x) => x.k === state.filter) || GROUPS_DEF[0];

  let filtered = state.requests.filter((r) => {
    if (state.filter === "unnamed") {
      return !state.names[r.requestNumber];
    }
    return currentGroup.f(r);
  });

  if (q) {
    filtered = filtered.filter((r) => {
      const name = (state.names[r.requestNumber] || "").toLowerCase();
      const reqNum = r.requestNumber.toLowerCase();
      const pays = (r.allPayments || []).join(" ").toLowerCase();
      return name.includes(q) || reqNum.includes(q) || pays.includes(q);
    });
  }

  // Sort descending by updatedAt
  filtered.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));

  if (!filtered.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="8" class="empty-state">
      ${state.requests.length ? "لا توجد طلبات تطابق هذا التصنيف أو البحث." : "لا توجد بيانات بعد. سجّل الدخول ثم اضغط «تحديث الآن»."}
    </td>`;
    tbody.appendChild(tr);
    return;
  }

  filtered.forEach((r, idx) => {
    const tr = document.createElement("tr");
    const change = state.changes[r.requestNumber];
    if (change) tr.classList.add("changed-row");

    // Index
    const tdIdx = document.createElement("td");
    tdIdx.textContent = idx + 1;
    tr.appendChild(tdIdx);

    // Request Number (Click to copy)
    const tdReq = document.createElement("td");
    tdReq.className = "num";
    tdReq.textContent = r.requestNumber;
    tdReq.title = "اضغط لنسخ رقم الطلب";
    tdReq.onclick = () => copyText(r.requestNumber, "تم نسخ رقم الطلب");
    tr.appendChild(tdReq);

    // Client Name (Editable with auto-save)
    const tdName = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "client-name-input";
    nameInput.placeholder = "أدخل اسم الموكل…";
    nameInput.value = state.names[r.requestNumber] || "";
    nameInput.onchange = async () => {
      const newName = nameInput.value.trim();
      try {
        const res = await fetch("/api/names", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ requestNumber: r.requestNumber, name: newName })
        });
        const data = await res.json();
        if (data.ok) {
          state.names = data.names;
          nameInput.classList.add("saved");
          setTimeout(() => nameInput.classList.remove("saved"), 800);
          if (state.filter === "unnamed") render();
        }
      } catch (e) {
        toast("تعذّر حفظ الاسم");
      }
    };
    tdName.appendChild(nameInput);
    tr.appendChild(tdName);

    // Status Badge & Delta Message
    const tdStatus = document.createElement("td");
    tdStatus.className = "status-cell";
    const badge = document.createElement("span");
    badge.className = `badge ${getBadgeClass(r.caseCode)}`;
    badge.textContent = r.caseMessage || r.stepMessage || r.caseCode;
    badge.title = `${r.stepMessage || ""} — ${r.caseMessage || ""}`;
    tdStatus.appendChild(badge);

    if (change) {
      const delta = document.createElement("span");
      delta.className = "delta-indicator";
      if (change.kind === "new") {
        delta.textContent = "● طلب جديد";
      } else if (change.kind === "payment") {
        delta.textContent = `● تغيّر رقم السداد: ${change.from || "—"} ← ${change.to || "—"}`;
      } else {
        delta.textContent = `● تغيّرت من: ${change.from}`;
      }
      tdStatus.appendChild(delta);
    }
    tr.appendChild(tdStatus);

    // Last Updated (Cairo time)
    const tdDate = document.createElement("td");
    tdDate.textContent = r.updatedAtCairo || r.updatedAt || "—";
    tr.appendChild(tdDate);

    // Payment Numbers
    const tdPays = document.createElement("td");
    tdPays.className = "num";
    const pays = r.allPayments || [];
    if (!pays.length) {
      tdPays.textContent = "—";
    } else {
      pays.forEach((p) => {
        const line = document.createElement("div");
        line.textContent = p;
        line.title = "اضغط لنسخ رقم السداد";
        line.onclick = () => copyText(p, "تم نسخ رقم السداد");
        tdPays.appendChild(line);
      });
      if (pays.length > 1) {
        const mTag = document.createElement("span");
        mTag.className = "badge info";
        mTag.style.marginTop = "4px";
        mTag.textContent = `${pays.length} أرقام سداد`;
        tdPays.appendChild(mTag);
      }
    }
    tr.appendChild(tdPays);

    // GARequestId (رقم الطلب بالجهة)
    const tdGA = document.createElement("td");
    tdGA.className = "num";
    tdGA.textContent = r.GARequestId || "—";
    tr.appendChild(tdGA);

    // Evidence Buttons
    const tdEvidence = document.createElement("td");
    tdEvidence.style.textAlign = "center";
    const btnGroup = document.createElement("div");
    btnGroup.className = "btn-group";

    const jsonBtn = document.createElement("button");
    jsonBtn.className = "btn small secondary";
    jsonBtn.textContent = "ملف JSON";
    jsonBtn.title = "تحميل ملف الأدلة الرقمية (بصمات رقمية وتفاصيل السداد)";
    jsonBtn.onclick = () => {
      window.open(`/api/evidence/${r.requestNumber}?download=1`, "_blank");
    };

    const htmlBtn = document.createElement("button");
    htmlBtn.className = "btn small ghost";
    htmlBtn.textContent = "عرض تقرير";
    htmlBtn.title = "فتح تقرير الأدلة الرقمية كصفحة منسقة للطباعة أو الحفظ";
    htmlBtn.onclick = () => {
      window.open(`/api/evidence/${r.requestNumber}/html`, "_blank");
    };

    btnGroup.append(jsonBtn, htmlBtn);
    tdEvidence.appendChild(btnGroup);
    tr.appendChild(tdEvidence);

    tbody.appendChild(tr);
  });
}

// Master Render
function render() {
  renderChips();
  renderRows();

  // Changes banner
  const chgKeys = Object.keys(state.changes || {});
  const chgBanner = $("chgBanner");
  if (chgKeys.length) {
    $("chgBannerMsg").textContent = `تم رصد تغيّر في حالة ${chgKeys.length} طلب منذ آخر اطلاع.`;
    chgBanner.style.display = "flex";
  } else {
    chgBanner.style.display = "none";
  }
}

// Auto-Refresh Countdown Timer
function resetCountdown() {
  clearInterval(state.countdownTimer);
  const mins = parseInt(state.settings.auto_refresh_minutes || 0);
  const badge = $("countdownBadge");

  if (mins <= 0) {
    badge.style.display = "none";
    return;
  }

  state.countdownSecs = mins * 60;
  badge.style.display = "inline-block";

  state.countdownTimer = setInterval(() => {
    state.countdownSecs--;
    if (state.countdownSecs <= 0) {
      clearInterval(state.countdownTimer);
      triggerRefresh();
    } else {
      const m = Math.floor(state.countdownSecs / 60);
      const s = state.countdownSecs % 60;
      badge.textContent = `${m}:${s < 10 ? "0" : ""}${s}`;
    }
  }, 1000);
}

// Event Listeners
$("refreshBtn").onclick = triggerRefresh;
$("errBannerAction").onclick = () => openModal("loginModal");

$("ackChgBtn").onclick = async () => {
  await fetch("/api/ack-changes", { method: "POST" });
  state.changes = {};
  render();
};

$("searchInput").oninput = (e) => {
  state.search = e.target.value;
  renderRows();
};

$("autoRefresh").onchange = async (e) => {
  const val = parseInt(e.target.value);
  state.settings.auto_refresh_minutes = val;
  await fetch("/api/settings", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ auto_refresh_minutes: val })
  });
  resetCountdown();
};

// Modal Open/Close helpers
function openModal(id) {
  $(id).style.display = "flex";
}
function closeModal(id) {
  $(id).style.display = "none";
}

$("loginModalBtn").onclick = () => openModal("loginModal");
$("closeLoginModal").onclick = () => closeModal("loginModal");
$("dismissLoginModal").onclick = () => closeModal("loginModal");

$("auditBtn").onclick = async () => {
  openModal("auditModal");
  loadAuditEntries();
};
$("closeAuditModal").onclick = () => closeModal("auditModal");
$("dismissAuditModal").onclick = () => closeModal("auditModal");

$("reconcileBtn").onclick = async () => {
  openModal("reconcileModal");
  loadReconciliation();
};
$("closeReconcileModal").onclick = () => closeModal("reconcileModal");
$("dismissReconcileModal").onclick = () => closeModal("reconcileModal");

// Login Modal Tabs Switcher
function selectLoginTab(tab) {
  const tabs = ["tabAuto", "tabBrowser", "tabManual"];
  tabs.forEach((t) => {
    const btn = $(t + "Btn");
    const content = $(t + "Content");
    if (btn) btn.classList.toggle("active", t === tab);
    if (content) content.style.display = (t === tab) ? "block" : "none";
  });
}

if ($("tabAutoBtn")) $("tabAutoBtn").onclick = () => selectLoginTab("tabAuto");
if ($("tabBrowserBtn")) $("tabBrowserBtn").onclick = () => selectLoginTab("tabBrowser");
if ($("tabManualBtn")) $("tabManualBtn").onclick = () => selectLoginTab("tabManual");

// --- Automated One-Click Login (CDP) ---
async function triggerAutoLogin() {
  const progress = $("autoLoginProgress");
  const statusText = $("autoLoginStatusText");
  const startBtn = $("startAutoLoginBtn");
  const headerBtn = $("autoLoginHeaderBtn");
  const bannerBtn = $("autoLoginBannerBtn");

  const setButtonsDisabled = (val) => {
    if (startBtn) startBtn.disabled = val;
    if (headerBtn) headerBtn.disabled = val;
    if (bannerBtn) bannerBtn.disabled = val;
  };

  setButtonsDisabled(true);
  if (progress) progress.style.display = "flex";
  if (statusText) statusText.textContent = "جارٍ قراءة بيانات login info.text والاتصال بالبوابة...";
  toast("جارٍ بدء تسجيل الدخول التلقائي وجلب التوكن...");

  try {
    const res = await fetch("/api/auto-login", { method: "POST" });
    const data = await res.json();
    if (!data.ok) {
      toast("خطأ: " + (data.error || "تعذّر بدء تسجيل الدخول"));
      setButtonsDisabled(false);
      if (progress) progress.style.display = "none";
      return;
    }

    // Poll status until done
    clearInterval(state.autoLoginPollTimer);
    state.autoLoginPollTimer = setInterval(async () => {
      try {
        const sRes = await fetch("/api/auto-login-status");
        const sData = await sRes.json();
        if (sData.status_message && statusText) {
          statusText.textContent = sData.status_message;
        }

        if (!sData.in_progress) {
          clearInterval(state.autoLoginPollTimer);
          setButtonsDisabled(false);
          if (progress) progress.style.display = "none";

          if (sData.success) {
            toast("🎉 تم تسجيل الدخول وجلب التوكن بنجاح!");
            closeModal("loginModal");
            triggerRefresh();
            checkAuthStatus();
          } else if (sData.error) {
            toast("❌ فشل تسجيل الدخول: " + sData.error);
            if (statusText) statusText.textContent = "فشل: " + sData.error;
          }
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1200);

  } catch (err) {
    setButtonsDisabled(false);
    if (progress) progress.style.display = "none";
    toast("خطأ في الاتصال: " + err.message);
  }
}

// --- Import from token.text ---
async function triggerImportTokenFile() {
  toast("جارٍ استيراد التوكن من ملف token.text...");
  try {
    const res = await fetch("/api/import-token-file", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      toast("✅ تم استيراد التوكن الساري بنجاح وتحديث الدعاوى!");
      closeModal("loginModal");
      triggerRefresh();
      checkAuthStatus();
    } else {
      toast("❌ " + (data.error || "تعذّر استيراد التوكن من الملف"));
    }
  } catch (err) {
    toast("خطأ في الاتصال: " + err.message);
  }
}

// Wire Auto-Login & Import Buttons
if ($("autoLoginHeaderBtn")) $("autoLoginHeaderBtn").onclick = triggerAutoLogin;
if ($("startAutoLoginBtn")) $("startAutoLoginBtn").onclick = triggerAutoLogin;
if ($("autoLoginBannerBtn")) $("autoLoginBannerBtn").onclick = triggerAutoLogin;
if ($("importTokenBannerBtn")) $("importTokenBannerBtn").onclick = triggerImportTokenFile;
if ($("importTokenFileModalBtn")) $("importTokenFileModalBtn").onclick = triggerImportTokenFile;

// Browser Login Trigger & Polling
$("startBrowserLoginBtn").onclick = async () => {
  const progress = $("browserLoginProgress");
  const statusText = $("browserLoginStatusText");
  const btn = $("startBrowserLoginBtn");

  btn.disabled = true;
  progress.style.display = "flex";
  statusText.textContent = "جارٍ تشغيل المتصفح...";

  try {
    await fetch("/api/login-browser", { method: "POST" });

    // Poll status
    clearInterval(state.loginPollTimer);
    state.loginPollTimer = setInterval(async () => {
      const res = await fetch("/api/login-status");
      const d = await res.json();
      if (d.status_message) {
        statusText.textContent = d.status_message;
      }
      if (!d.in_progress) {
        clearInterval(state.loginPollTimer);
        btn.disabled = false;
        if (d.success) {
          toast("تم تسجيل الدخول بنجاح!");
          closeModal("loginModal");
          triggerRefresh();
        } else if (d.error) {
          toast("فشل تسجيل الدخول: " + d.error);
        }
      }
    }, 1500);
  } catch (err) {
    btn.disabled = false;
    statusText.textContent = "خطأ: " + err.message;
  }
};

// Manual Token Save
$("saveManualTokensBtn").onclick = async () => {
  const acc = $("manualAccessToken").value.trim();
  const ref = $("manualRefreshToken").value.trim();
  if (!acc) {
    toast("يرجى إدخال Access Token على الأقل");
    return;
  }

  try {
    const res = await fetch("/api/set-tokens", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ accessToken: acc, refreshToken: ref })
    });
    const data = await res.json();
    if (data.ok) {
      toast("تم حفظ التوكن وتفعيل الجلسة بنجاح!");
      closeModal("loginModal");
      triggerRefresh();
    } else {
      toast("خطأ: " + (data.error || "تعذّر حفظ التوكن"));
    }
  } catch (e) {
    toast("خطأ في الاتصال: " + e.message);
  }
};

// Logout
$("logoutBtn").onclick = async () => {
  if (confirm("هل أنت متأكد من رغبتك في تسجيل الخروج وحذف بيانات الجلسة؟")) {
    await fetch("/api/logout", { method: "POST" });
    toast("تم تسجيل الخروج");
    closeModal("loginModal");
    checkAuthStatus();
  }
};

// Audit Log Viewer
async function loadAuditEntries() {
  const tbody = $("auditRows");
  tbody.innerHTML = '<tr><td colspan="6" class="empty-state">جارٍ تحميل سجل التدقيق...</td></tr>';
  try {
    const res = await fetch("/api/audit");
    const data = await res.json();
    state.auditEntries = data.entries || [];
    renderAuditRows();
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">تعذّر جلب سجل التدقيق</td></tr>';
  }
}

function renderAuditRows() {
  const tbody = $("auditRows");
  tbody.innerHTML = "";
  const q = ($("auditSearchInput").value || "").trim().toLowerCase();

  let list = state.auditEntries;
  if (q) {
    list = list.filter((e) => (e.requestNumber || "").toLowerCase().includes(q));
  }

  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">لا توجد سجلات تدقيق</td></tr>';
    return;
  }

  // Newest first
  [...list].reverse().forEach((e) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${e.at ? new Date(e.at).toLocaleString("ar-EG") : "—"}</td>
      <td class="num">${e.requestNumber}</td>
      <td><span class="badge ${getBadgeClass(e.caseCode)}">${e.caseCode}</span></td>
      <td>${e.caseMessage || "—"}</td>
      <td class="num">${(e.payments || []).join(" + ") || "—"}</td>
      <td>${e.firstObservation ? '<span class="badge info">رصد أولي</span>' : '<span class="badge warn">تغيير</span>'}</td>
    `;
    tbody.appendChild(tr);
  });
}
$("auditSearchInput").oninput = renderAuditRows;

$("exportAuditJsonBtn").onclick = () => {
  const blob = new Blob([JSON.stringify(state.auditEntries, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `audit-log-${Date.now()}.json`;
  a.click();
};

// Bank Reconciliation Viewer
async function loadReconciliation() {
  const tbody = $("reconcileRows");
  tbody.innerHTML = '<tr><td colspan="6" class="empty-state">جارٍ مطابقة أرقام السداد مع مراحل الدعاوى...</td></tr>';
  try {
    const res = await fetch("/api/reconcile");
    const data = await res.json();
    const rows = data.rows || [];
    tbody.innerHTML = "";
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">لا توجد دعاوى لها أرقام سداد حتى الآن</td></tr>';
      return;
    }
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="num">${r.requestNumber}</td>
        <td><b>${r.name || "—"}</b></td>
        <td class="num">${r.paymentNumbers || "—"}</td>
        <td><span class="badge ${r.paidEventsCount > 0 ? "ok" : "gray"}">${r.paidEventsCount} عمليات دفع</span></td>
        <td>${r.firstPaidCairo || "—"}</td>
        <td><code>${r.writtenBy || "—"}</code></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">تعذّر جلب بيانات المطابقة</td></tr>';
  }
}

// Backup & Restore Names
$("backupBtn").onclick = () => {
  window.open("/api/backup-names", "_blank");
};

$("restoreBtn").onclick = () => {
  $("restoreFileInput").click();
};

$("restoreFileInput").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const fd = new FormData();
  fd.append("file", file);

  try {
    const res = await fetch("/api/restore-names", { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
      toast(`تم استرجاع ${data.restored_count} اسم موكل بنجاح`);
      loadData();
    } else {
      toast("فشل الاسترجاع: " + (data.error || "الملف غير صالح"));
    }
  } catch (err) {
    toast("خطأ في قراءة الملف");
  }
  e.target.value = "";
};

// Dark / Light Theme Toggle
const themeBtn = $("themeToggleBtn");
const savedTheme = localStorage.getItem("tracker-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.setAttribute("data-theme", savedTheme);

themeBtn.onclick = () => {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("tracker-theme", next);
};

// Start application
loadData();
resetCountdown();
