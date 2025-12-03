// Path: static/app.js
// Overwrite your existing file with this content.

const metaApi = document.querySelector('meta[name="api-base"]');
const API_BASE = (metaApi && metaApi.content) ? metaApi.content.replace(/\/$/, "") : "";

let token = localStorage.getItem("access_token") || null;
let currentUsername = localStorage.getItem("username") || null;

const authSection = document.getElementById("auth-section");
const mainSection = document.getElementById("main-section");
const welcomeLabel = document.getElementById("welcome-label");

function showMain() {
  authSection.style.display = "none";
  mainSection.style.display = "block";
  welcomeLabel.textContent = `Logged in as ${currentUsername}`;
  loadCompaniesAndDashboard();
}

function showAuth() {
  mainSection.style.display = "none";
  authSection.style.display = "flex";
}

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (token) {
    headers["Authorization"] = "Bearer " + token;
  }
  return fetch(API_BASE + path, { ...options, headers });
}

// ---------- Register ----------
document.getElementById("btn-register").onclick = async () => {
  const u = document.getElementById("reg-username").value.trim();
  const p = document.getElementById("reg-password").value.trim();
  const msg = document.getElementById("reg-msg");
  msg.textContent = "";

  if (!u || !p) {
    msg.textContent = "Username and password required.";
    return;
  }

  const res = await apiFetch("/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: u, password: p }),
  });

  if (res.ok) {
    msg.textContent = "Registered successfully. You can login now.";
  } else {
    const data = await res.json();
    msg.textContent = data.detail || "Registration failed.";
  }
};

// ---------- Login ----------
document.getElementById("btn-login").onclick = async () => {
  const u = document.getElementById("login-username").value.trim();
  const p = document.getElementById("login-password").value.trim();
  const msg = document.getElementById("login-msg");
  msg.textContent = "";

  if (!u || !p) {
    msg.textContent = "Username and password required.";
    return;
  }

  const body = new URLSearchParams();
  body.append("username", u);
  body.append("password", p);
  body.append("grant_type", "password");

  const res = await fetch(API_BASE + "/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (res.ok) {
    const data = await res.json();
    token = data.access_token;
    currentUsername = u;
    localStorage.setItem("access_token", token);
    localStorage.setItem("username", currentUsername);
    msg.textContent = "";
    showMain();
  } else {
    const data = await res.json();
    msg.textContent = data.detail || "Login failed.";
  }
};

// ---------- Logout ----------
document.getElementById("btn-logout").onclick = () => {
  token = null;
  currentUsername = null;
  localStorage.removeItem("access_token");
  localStorage.removeItem("username");
  showAuth();
};

// ---------- Load companies & dashboard ----------
async function loadCompaniesAndDashboard() {
  await Promise.all([loadCompanies(), loadDashboard()]);
  // auto-refresh sector analytics after data changes
  loadSectorAnalytics();
}


async function loadCompanies() {
  const res = await apiFetch("/companies");
  const container = document.getElementById("company-list");
  container.innerHTML = "";

  if (!res.ok) {
    container.textContent = "Error loading companies.";
    return;
  }

  const data = await res.json();
  if (data.length === 0) {
    container.textContent = "No companies yet. Add some above.";
    return;
  }

  const ul = document.createElement("ul");
  data.forEach((c) => {
    const li = document.createElement("li");
    li.textContent = `${c.name} (${c.ticker}) – ${c.segment}`;
    const btn = document.createElement("button");
    btn.textContent = "Delete";
    btn.onclick = () => deleteCompany(c.id);
    li.appendChild(btn);
    ul.appendChild(li);
  });
  container.appendChild(ul);
}

async function deleteCompany(id) {
  if (!confirm("Delete this company?")) return;
  const res = await apiFetch(`/companies/${id}`, { method: "DELETE" });
  if (res.status === 204) {
    await loadCompaniesAndDashboard();
  } else {
    alert("Error deleting company");
  }
}

// ---------- Add company ----------
document.getElementById("btn-add-company").onclick = async () => {
  const name = document.getElementById("new-name").value.trim();
  const ticker = document.getElementById("new-ticker").value.trim();
  const segment = document.getElementById("new-segment").value.trim();
  const msg = document.getElementById("add-msg");
  msg.textContent = "";

  if (!name || !ticker || !segment) {
    msg.textContent = "All fields are required.";
    return;
  }

  const res = await apiFetch("/companies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, ticker, segment }),
  });

  if (res.ok) {
    document.getElementById("new-name").value = "";
    document.getElementById("new-ticker").value = "";
    document.getElementById("new-segment").value = "";
    msg.textContent = "Company added.";
    await loadCompaniesAndDashboard();
  } else {
    const data = await res.json();
    msg.textContent = data.detail || "Error adding company.";
  }
};

// ---------- Dashboard ----------
async function loadDashboard() {
  const container = document.getElementById("dashboard-table");
  container.innerHTML = "Loading...";

  const res = await apiFetch("/dashboard");
  if (!res.ok) {
    container.textContent = "Error loading dashboard.";
    return;
  }
  const data = await res.json();

  if (!data.companies || data.companies.length === 0) {
    container.textContent = "No data. Add companies in the left panel.";
    return;
  }

  const table = document.createElement("table");
  table.classList.add("data-table");

  const headerRow = document.createElement("tr");
  [
    "Name",
    "Segment",
    "Price",
    "Revenue",
    "Net Income",
    "Net Margin",
    "ROE",
    "D/E",
    "Current Ratio",
    "1Y Return",
  ].forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h;
    headerRow.appendChild(th);
  });
  table.appendChild(headerRow);

  data.companies.forEach((c) => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.onclick = () => loadCompanyDetail(c.id);

    function addCell(text) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }

    addCell(c.name);
    addCell(c.segment);
    addCell(formatNumber(c.price));
    addCell(formatNumber(c.revenue));
    addCell(formatNumber(c.net_income));
    addCell(formatPct(c.net_margin));
    addCell(formatPct(c.roe));
    addCell(formatNumber(c.debt_to_equity, 2));
    addCell(formatNumber(c.current_ratio, 2));
    addCell(formatPct(c.one_year_return));

    table.appendChild(tr);
  });

  container.innerHTML = "";
  container.appendChild(table);
}

// ---------- Detail view ----------
async function loadCompanyDetail(id) {
  // Request analytics in background (non-blocking)
  loadCompanyAnalytics(id).catch(() => {});

  const container = document.getElementById("detail-content");
  container.innerHTML = "Loading detail...";

  const res = await apiFetch(`/companies/${id}/detail`);
  if (!res.ok) {
    container.textContent = "Error loading detail.";
    return;
  }

  const data = await res.json();
  const { info, ratios, income_statement, balance_sheet, cash_flow } = data;

  const wrapper = document.createElement("div");

  // Header row with title and download button
  const headerRow = document.createElement("div");
  headerRow.style.display = "flex";
  headerRow.style.justifyContent = "space-between";
  headerRow.style.alignItems = "center";
  headerRow.style.marginBottom = "10px";

  const title = document.createElement("h2");
  title.textContent = `Company Detail — ${info && info.longName ? info.longName : (ratios && ratios.name ? ratios.name : "")}`;
  title.style.margin = 0;
  headerRow.appendChild(title);

  // Download XLSX button in header
  const downloadBtn = document.createElement("button");
  downloadBtn.textContent = "Download XLSX";
  downloadBtn.style.padding = "8px 12px";
  downloadBtn.style.borderRadius = "6px";
  downloadBtn.style.cursor = "pointer";
  downloadBtn.onclick = () => downloadXlsx(id, (info && info.longName) || (ratios && ratios.name) || "company");
  headerRow.appendChild(downloadBtn);

  wrapper.appendChild(headerRow);

  // Ratios block (single declaration)
  const ratiosDiv = document.createElement("div");
  ratiosDiv.classList.add("ratios");

  const ratioList = [
    ["Price", ratios ? ratios.price : null],
    ["Revenue (last FY)", ratios ? ratios.revenue : null],
    ["Net Income (last FY)", ratios ? ratios.net_income : null],
    ["Net Margin", ratios ? ratios.net_margin : null],
    ["ROE", ratios ? ratios.roe : null],
    ["Debt/Equity", ratios ? ratios.debt_to_equity : null],
    ["Current Ratio", ratios ? ratios.current_ratio : null],
    ["1Y Return", ratios ? ratios.one_year_return : null],
  ];

  const ul = document.createElement("ul");
  ratioList.forEach(([label, value]) => {
    const li = document.createElement("li");
    const display = (value === null || value === undefined) ? "-" : (label.includes("Margin") || label === "1Y Return" ? formatPct(value) : formatNumber(value));
    li.innerHTML = `<strong>${label}:</strong> ${display}`;
    ul.appendChild(li);
  });
  ratiosDiv.appendChild(ul);
  wrapper.appendChild(ratiosDiv);


  // ---------- Sector Analytics ----------
    async function loadSectorAnalytics() {
  const container = document.getElementById("sector-analytics-text");
  if (!container) return;

  container.textContent = "Generating sector insights (via Gemini)...";

  const res = await apiFetch("/analytics/sector");
  if (!res.ok) {
    container.textContent = "Error generating sector insights.";
    return;
  }

  const data = await res.json();
  container.textContent = data.text || "No analysis generated.";
  }
  const btnSector = document.getElementById("btn-refresh-sector-analytics");
  if (btnSector) {
      btnSector.onclick = () => loadSectorAnalytics();
      
  }

  // Statements
  function buildStatementBlock(title, st) {
    const block = document.createElement("div");
    block.classList.add("statement-block");
    block.style.marginTop = "18px";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.justifyContent = "space-between";
    header.style.alignItems = "center";

    const h = document.createElement("h3");
    h.textContent = title;
    header.appendChild(h);

    // Add small download-per-sheet (optional) disabled for now
    // const smallBtn = document.createElement("button");
    // smallBtn.textContent = "Download sheet";
    // smallBtn.onclick = () => alert("Sheet download not implemented separately.");
    // header.appendChild(smallBtn);

    block.appendChild(header);

    if (!st) {
      const p = document.createElement("p");
      p.textContent = "No data.";
      block.appendChild(p);
      return block;
    }

    const table = document.createElement("table");
    table.classList.add("data-table");
    table.style.width = "100%";
    table.style.borderCollapse = "collapse";

    const headerRow = document.createElement("tr");
    const emptyTh = document.createElement("th");
    emptyTh.textContent = "";
    headerRow.appendChild(emptyTh);
    st.columns.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c;
      headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    st.index.forEach((idx, i) => {
      const row = document.createElement("tr");
      const idxTd = document.createElement("td");
      idxTd.textContent = idx;
      row.appendChild(idxTd);
      st.data[i].forEach((v) => {
        const td = document.createElement("td");
        td.textContent = v === null ? "" : v;
        row.appendChild(td);
      });
      table.appendChild(row);
    });

    block.appendChild(table);
    return block;
  }

  wrapper.appendChild(buildStatementBlock("Income Statement (2–3 years)", income_statement));
  wrapper.appendChild(buildStatementBlock("Balance Sheet (2–3 years)", balance_sheet));
  wrapper.appendChild(buildStatementBlock("Cash Flow (2–3 years)", cash_flow));

  container.innerHTML = "";
  container.appendChild(wrapper);
}

// ---------- Download Report ----------
async function downloadXlsx(companyId, companyName){
  if (!token) { alert("You must be logged in to download."); return; }
  try {

    const url = API_BASE + `/companies/${companyId}/download`;
    console.log("Download URL:", url);

    const res = await fetch(url, {
      method: "GET",
      headers: { Authorization: "Bearer " + token }
    });

    if (!res.ok) {
      const txt = await res.text();
      alert("Download failed: " + (txt || res.statusText));
      return;
    }

    const blob = await res.blob();
    const downloadUrl = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = downloadUrl;

    const safeName = (companyName || "company")
      .replace(/\s+/g, "_")
      .replace(/[^\w\-_.]/g, "");

    a.download = `${safeName}_financials.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();

    URL.revokeObjectURL(downloadUrl);
    alert("Download started");

  } catch (err) {
    console.error(err);
    alert("Download error");
  }
}

// ---------- Helpers ----------
function formatNumber(x, decimals = 0) {
  if (x === null || x === undefined || isNaN(x)) return "-";
  const num = Number(x);
  if (Math.abs(num) >= 1e9) return (num / 1e9).toFixed(decimals) + "B";
  if (Math.abs(num) >= 1e6) return (num / 1e6).toFixed(decimals) + "M";
  if (Math.abs(num) >= 1e3) return (num / 1e3).toFixed(decimals) + "K";
  return num.toFixed(decimals);
}

async function loadCompanyAnalytics(id) {
  const container = document.getElementById("company-analytics-text");
  if (!container) return;

  container.textContent = "Generating company insights (via Gemini)...";

  const res = await apiFetch(`/analytics/company/${id}`);
  if (!res.ok) {
    container.textContent = "Error generating company insights.";
    return;
  }

  const data = await res.json();
  container.textContent = data.text || "No analysis generated.";
}
function formatPct(x) {
  if (x === null || x === undefined || isNaN(x)) return "-";
  return (Number(x) * 100).toFixed(1) + "%";
}

// ---------- Init ----------
if (token && currentUsername) {
  showMain();
} else {
  showAuth();
}
