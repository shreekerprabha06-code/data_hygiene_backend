import React, { useState, useEffect } from "react";
import { Box, Typography } from "@mui/material";
import ListHeader from "../components/ListHeader";
import RecordList from "../components/RecordList";
import ErrorPage from "../components/ErrorPage";
import { usePaginatedRecords } from "../hooks/usePaginatedRecords";
import { useRefresh } from "../context/RefreshContext";

const MODE_CONFIG = {
  landing:   { title: "Data Hygiene Dashboard", showStatusFilters: true,  showStageFilters: true },
  active:    { title: "My Active List",          defaultStatus: "pending",            showAgeFilters: true },
  completed: { title: "My Completed List",       defaultStatus: "accepted,rejected",  showStatusFilters: true, allowedFilters: ["accepted", "rejected"] },
  onhold:    { title: "On Hold Records",         defaultStatus: "On Hold",            showAgeFilters: true },
  all:       { title: "All Records",             showStatusFilters: true },
};

const AGE_TO_SERVER = { "<3": "green", "3-6": "yellow", ">6": "red" };
const STAGE_FILTER_VALUES = ["validation inprogress,validation initiated", "standardization inprogress"];

const RecordsListPage = ({ mode = "landing" }) => {
  const config = MODE_CONFIG[mode] || MODE_CONFIG.landing;
  const { registerRefresh } = useRefresh();

  const [filter, setFilter] = useState([]);

  const handleFilterChange = (value) => {
    if (value === "") {
      setFilter([]);
    } else {
      setFilter((prev) =>
        prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]
      );
    }
  };

  const extraParams = React.useMemo(() => {
    if (!config.showStatusFilters) {
      const params = { status: config.defaultStatus };
      if (filter.length > 0) params.age = filter.map((f) => AGE_TO_SERVER[f] || f).join(",");
      return params;
    }

    const params = {};
    if (config.defaultStage)  params.stage  = config.defaultStage;
    if (config.defaultStatus) params.status = config.defaultStatus;

    if (filter.length > 0) {
      const statuses = filter.filter((v) => !STAGE_FILTER_VALUES.includes(v));
      const stages   = filter.filter((v) =>  STAGE_FILTER_VALUES.includes(v));
      if (statuses.length > 0) params.status = statuses.join(",");
      if (stages.length   > 0) params.stage  = stages.join(",");
    }

    return params;
  }, [mode, filter, config.showStatusFilters, config.defaultStage, config.defaultStatus]);

  const {
    records, totalRecords, totalPages, page, loading, error,
    searchInput, setSearchInput, search,
    loadMore, retry, refresh, meta,
    patchRecords, removeRecords, updateCounts, isReadyState,
  } = usePaginatedRecords({ extraParams, activeFilters: filter });

  // Auto-refresh when only Val/Std filters are active but local list is empty
  useEffect(() => {
    if (loading || !isReadyState) return;

    const hasVal = filter.includes("validation inprogress,validation initiated");
    const hasStd = filter.includes("standardization inprogress");
    const otherCount = filter.length - (hasVal ? 1 : 0) - (hasStd ? 1 : 0);

    // Only proceed if at least one is selected and NO other filters are active
    if ((hasVal || hasStd) && otherCount === 0) {
      let serverCount = 0;
      if (hasVal) serverCount += (meta?.VALIDATION_INITIATED || 0) + (meta?.VALIDATION_IN_PROGRESS || 0);
      if (hasStd) serverCount += (meta?.STANDARDIZATION_IN_PROGRESS || 0);

      if (serverCount > 0 && records.length === 0) {
        refresh();
      }
    }
  }, [meta, records.length, filter, loading, refresh, isReadyState]);

  useEffect(() => {
    registerRefresh(refresh);
  }, [refresh, registerRefresh]);

  const isSearching = loading && searchInput !== search;

  if (error) {
    return <ErrorPage message={error?.message || "Something went wrong"} onRetry={retry} />;
  }

  return (
    <Box sx={{ backgroundColor: "#ebebebff", minHeight: "100vh" }}>
      <ListHeader
        title={config.title}
        search={searchInput}
        onSearchChange={setSearchInput}
        filter={filter}
        onFilterChange={handleFilterChange}
        counts={meta}
        showAgeFilters={config.showAgeFilters}
        showStatusFilters={config.showStatusFilters}
        showStageFilters={config.showStageFilters}
        allowedFilters={config.allowedFilters}
        loading={isSearching}
        totalRecords={totalRecords}
        onRefresh={refresh}
      />

      <Box sx={{ px: 3, py: 2 }}>
        <RecordList
          records={records}
          totalRecords={totalRecords}
          totalPages={totalPages}
          page={page}
          loading={loading}
          onLoadMore={loadMore}
          patchRecords={patchRecords}
          removeRecords={removeRecords}
          updateCounts={updateCounts}
          activeFilters={filter}
          isReadyState={isReadyState}
        />

        {!loading && records.length === 0 && (
          <Box sx={{ textAlign: "center", py: 8, backgroundColor: "#ebebebff", border: "1px solid #e0e0e0", borderTop: "none" }}>
            <Typography variant="h6" color="text.secondary" sx={{ fontSize: 14 }}>
              {(() => {
                const hasVal = filter.includes("validation inprogress,validation initiated");
                const hasStd = filter.includes("standardization inprogress");
                const otherCount = filter.length - (hasVal ? 1 : 0) - (hasStd ? 1 : 0);
                if (hasVal && hasStd && otherCount === 0) return "No records left for validation or standardization.";
                if (hasVal && otherCount === 0) return "Validation completed. No records left to validate.";
                if (hasStd && otherCount === 0) return "Standardization completed. No records left to standardize.";
                return filter.length > 0 ? "No records match the selected filter." : "No records found in this category.";
              })()}
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default RecordsListPage;