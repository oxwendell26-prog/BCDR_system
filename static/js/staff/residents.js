document.addEventListener("DOMContentLoaded", function () {
    var section = document.getElementById("residents-section");
    var searchInput = document.getElementById("resident-search");
    var noResults = document.getElementById("no-results");
    var tabs = document.querySelectorAll(".filter-tab");
    var rows = document.querySelectorAll(".resident-row");

    if (!section || !searchInput) return;

    var activeFilter = section.getAttribute("data-default-filter") || "all";

    function highlightActiveTab() {
        tabs.forEach(function (tab) {
            var isActive = tab.getAttribute("data-filter") === activeFilter;
            tab.classList.toggle("is-active", isActive);
            tab.setAttribute("aria-pressed", String(isActive));
        });
    }

    function applyFilters() {
        var term = searchInput.value.trim().toLowerCase();
        var visibleCount = 0;

        rows.forEach(function (row) {
            var matchesStatus = activeFilter === "all" || row.getAttribute("data-status") === activeFilter;
            var matchesSearch = term === "" || row.getAttribute("data-search").indexOf(term) !== -1;
            var show = matchesStatus && matchesSearch;
            row.hidden = !show;
            if (show) {
                visibleCount += 1;
            }
        });

        if (noResults) {
            noResults.hidden = rows.length === 0 || visibleCount > 0;
        }
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            activeFilter = tab.getAttribute("data-filter");
            highlightActiveTab();
            applyFilters();
        });
    });

    searchInput.addEventListener("input", applyFilters);

    highlightActiveTab();
    applyFilters();
});