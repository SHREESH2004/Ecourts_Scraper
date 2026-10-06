function safeJudgmentUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

async function loadSupremeCourtJudge() {
  initSidebar("judges");
  const judgeName = new URLSearchParams(window.location.search).get("name");
  const tbody = document.getElementById("sc-judge-cases");
  const error = document.getElementById("sc-judge-error");

  if (!judgeName) {
    error.style.display = "flex";
    document.getElementById("sc-judge-error-message").textContent = "No judge was specified.";
    tbody.innerHTML = "";
    return;
  }

  document.getElementById("sc-judge-title").textContent = judgeName;
  document.getElementById("sc-judge-breadcrumb").textContent = judgeName;

  try {
    const response = await API.get(`/api/supreme-court/judges/${encodeURIComponent(judgeName)}`);
    const { summary, cases } = response.data;
    document.getElementById("sc-judge-total-cases").textContent = formatNumber(summary.total_cases);
    document.getElementById("sc-judge-unique-cases").textContent = formatNumber(summary.unique_cases);
    document.getElementById("sc-judge-first-date").textContent = formatDate(summary.earliest_judgment);
    document.getElementById("sc-judge-last-date").textContent = formatDate(summary.latest_judgment);
    document.getElementById("sc-judge-summary").style.display = "grid";
    document.getElementById("sc-judge-case-count").textContent = `${formatNumber(cases.length)} Cases`;

    if (cases.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 24px;">No case records found.</td></tr>';
      return;
    }

    tbody.innerHTML = cases.map(caseRecord => {
      const judgmentUrl = safeJudgmentUrl(caseRecord.judgment_url);
      const judgment = judgmentUrl
        ? `<a href="${escapeHTML(judgmentUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline btn-sm">Open</a>`
        : '<span style="color: var(--text-tertiary);">Unavailable</span>';
      return `
        <tr>
          <td class="cell-mono">${escapeHTML(caseRecord.case_id || "—")}</td>
          <td class="cell-primary">${escapeHTML(caseRecord.title || "—")}</td>
          <td class="cell-mono">${formatDate(caseRecord.judgment_date)}</td>
          <td>${escapeHTML(caseRecord.bench || "—")}</td>
          <td class="cell-mono">${escapeHTML(caseRecord.citation || "—")}</td>
          <td>${judgment}</td>
        </tr>
      `;
    }).join("");
    renderIcons();
  } catch (err) {
    console.error("Failed to load Supreme Court judge details:", err);
    tbody.innerHTML = "";
    error.style.display = "flex";
    document.getElementById("sc-judge-error-message").textContent = err.message;
    renderIcons();
  }
}

document.addEventListener("DOMContentLoaded", loadSupremeCourtJudge);
