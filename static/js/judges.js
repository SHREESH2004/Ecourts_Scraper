const judgeDirectoryState = {
  query: "",
  court: "all",
  sortBy: "record_count",
  order: "desc",
  page: 1,
  limit: 20,
  totalPages: 1
};

async function fetchJudges() {
  const tbody = document.getElementById("judges-tbody");
  const empty = document.getElementById("judges-empty");
  const error = document.getElementById("judges-error");
  const pagination = document.getElementById("judges-pagination");
  const countBadge = document.getElementById("judges-count-badge");

  empty.style.display = "none";
  error.style.display = "none";
  tbody.innerHTML = Array.from({ length: 6 }, () => `
    <tr>
      <td><div class="skeleton" style="height: 20px; width: 65%;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 75%;"></div></td>
      <td style="text-align: right;"><div class="skeleton" style="height: 20px; width: 45px; margin-left: auto;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 90px;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 90px;"></div></td>
      <td></td>
    </tr>
  `).join("");

  try {
    const result = await API.get("/api/judge-directory", {
      q: judgeDirectoryState.query,
      court: judgeDirectoryState.court,
      sort: judgeDirectoryState.sortBy,
      order: judgeDirectoryState.order,
      page: judgeDirectoryState.page,
      limit: judgeDirectoryState.limit
    });

    judgeDirectoryState.totalPages = Math.max(1, result.total_pages);
    if (judgeDirectoryState.page > judgeDirectoryState.totalPages) {
      judgeDirectoryState.page = judgeDirectoryState.totalPages;
      return fetchJudges();
    }

    countBadge.textContent = `${formatNumber(result.total)} Judges Found`;
    if (result.items.length === 0) {
      tbody.innerHTML = "";
      empty.style.display = "flex";
      pagination.style.display = "none";
      renderIcons();
      return;
    }

    tbody.innerHTML = result.items.map(judge => {
      const isSupremeCourt = judge.court_type === "supreme_court";
      const detailUrl = isSupremeCourt
        ? `/supreme-court-judge.html?name=${encodeURIComponent(judge.judge_name)}`
        : `/judge.html?name=${encodeURIComponent(judge.judge_name)}`;
      const courtBadge = isSupremeCourt
        ? "badge-amber"
        : "badge-blue";

      return `
        <tr class="clickable" onclick="window.location.href='${detailUrl}'">
          <td class="cell-primary">
            <div style="font-weight: 500; font-size: 13px;">${escapeHTML(judge.judge_name)}</div>
          </td>
          <td>
            <span class="badge ${courtBadge}">${escapeHTML(judge.court_name)}</span>
          </td>
          <td style="text-align: right;">
            <span class="badge badge-mono badge-blue">${formatNumber(judge.record_count)}</span>
          </td>
          <td class="cell-mono" style="color: var(--text-tertiary);">${formatDate(judge.first_seen)}</td>
          <td class="cell-mono" style="color: var(--text-tertiary);">${formatDate(judge.last_seen)}</td>
          <td style="text-align: center;">
            <a href="${detailUrl}" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();" title="View judge details">
              <i data-lucide="chevron-right" style="width: 15px; height: 15px;"></i>
            </a>
          </td>
        </tr>
      `;
    }).join("");

    pagination.style.display = "flex";
    const start = (judgeDirectoryState.page - 1) * judgeDirectoryState.limit + 1;
    const end = Math.min(judgeDirectoryState.page * judgeDirectoryState.limit, result.total);
    document.getElementById("pagination-info").textContent =
      `Showing ${start}-${end} of ${formatNumber(result.total)} judges`;
    document.getElementById("page-num-display").textContent =
      `${judgeDirectoryState.page} / ${judgeDirectoryState.totalPages}`;
    document.getElementById("prev-page-btn").disabled = judgeDirectoryState.page <= 1;
    document.getElementById("next-page-btn").disabled =
      judgeDirectoryState.page >= judgeDirectoryState.totalPages;
    renderIcons();
  } catch (err) {
    console.error("Failed to load judges:", err);
    tbody.innerHTML = "";
    error.style.display = "flex";
    document.getElementById("judges-error-msg").textContent =
      err.message || "Error communicating with backend API";
    pagination.style.display = "none";
    renderIcons();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initSidebar("judges");

  const search = document.getElementById("judge-search-input");
  const sortSelect = document.getElementById("judge-sort-select");
  const courtSelect = document.getElementById("judge-court-select");
  const orderButton = document.getElementById("sort-order-btn");

  const params = new URLSearchParams(window.location.search);
  const initialCourt = params.get("court");
  if (["all", "other", "supreme"].includes(initialCourt)) {
    judgeDirectoryState.court = initialCourt;
    courtSelect.value = initialCourt;
  }

  search.addEventListener("input", debounce(() => {
    judgeDirectoryState.query = search.value.trim();
    judgeDirectoryState.page = 1;
    fetchJudges();
  }, 280));

  document.getElementById("clear-search-btn").addEventListener("click", () => {
    search.value = "";
    judgeDirectoryState.query = "";
    judgeDirectoryState.page = 1;
    fetchJudges();
  });

  courtSelect.addEventListener("change", () => {
    judgeDirectoryState.court = courtSelect.value;
    judgeDirectoryState.page = 1;
    const url = new URL(window.location.href);
    if (judgeDirectoryState.court === "all") {
      url.searchParams.delete("court");
    } else {
      url.searchParams.set("court", judgeDirectoryState.court);
    }
    window.history.replaceState({}, "", url);
    fetchJudges();
  });

  sortSelect.addEventListener("change", () => {
    judgeDirectoryState.sortBy = sortSelect.value;
    judgeDirectoryState.page = 1;
    fetchJudges();
  });

  orderButton.addEventListener("click", () => {
    judgeDirectoryState.order = judgeDirectoryState.order === "desc" ? "asc" : "desc";
    orderButton.innerHTML = judgeDirectoryState.order === "desc"
      ? '<i data-lucide="arrow-down-narrow-wide" style="width: 15px; height: 15px;"></i>'
      : '<i data-lucide="arrow-up-narrow-wide" style="width: 15px; height: 15px;"></i>';
    renderIcons();
    fetchJudges();
  });

  document.querySelectorAll("#judges-table th.sortable").forEach(header => {
    header.addEventListener("click", () => {
      const sortBy = header.dataset.sort;
      if (judgeDirectoryState.sortBy === sortBy) {
        judgeDirectoryState.order = judgeDirectoryState.order === "desc" ? "asc" : "desc";
      } else {
        judgeDirectoryState.sortBy = sortBy;
        judgeDirectoryState.order = "desc";
        sortSelect.value = sortBy;
      }
      fetchJudges();
    });
  });

  document.getElementById("limit-select").addEventListener("change", event => {
    judgeDirectoryState.limit = Number.parseInt(event.target.value, 10);
    judgeDirectoryState.page = 1;
    fetchJudges();
  });

  document.getElementById("prev-page-btn").addEventListener("click", () => {
    if (judgeDirectoryState.page > 1) {
      judgeDirectoryState.page -= 1;
      fetchJudges();
    }
  });

  document.getElementById("next-page-btn").addEventListener("click", () => {
    if (judgeDirectoryState.page < judgeDirectoryState.totalPages) {
      judgeDirectoryState.page += 1;
      fetchJudges();
    }
  });

  document.getElementById("retry-judges-btn").addEventListener("click", fetchJudges);

  const previewButton = document.getElementById("preview-scrape-btn");
  previewButton.addEventListener("click", () => {
    const activeCourt = courtSelect.options[courtSelect.selectedIndex].text;
    const filters = [
      `Court: ${activeCourt}`,
      `Sort: ${judgeDirectoryState.sortBy} (${judgeDirectoryState.order})`,
      `Page: ${judgeDirectoryState.page} of ${judgeDirectoryState.totalPages}`,
      `Limit: ${judgeDirectoryState.limit} per page`
    ];
    if (judgeDirectoryState.query) {
      filters.unshift(`Search: "${judgeDirectoryState.query}"`);
    }
    showToast(`Preview: Would scrape data with filters: ${filters.join(" | ")}`, "info");
  });

  fetchJudges();
});
