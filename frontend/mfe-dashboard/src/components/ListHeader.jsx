import React, { useState } from "react";
import {
  Box,
  Typography,
  TextField,
  Stack,
  CircularProgress,
  InputAdornment,
  Checkbox,
  Popover,
  Divider,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";

const ListHeader = ({
  title,
  search,
  onSearchChange,
  filter,
  onFilterChange,
  counts = {},
  showAgeFilters = false,
  showStatusFilters = false,
  showStageFilters = false,
  allowedFilters,
  loading,
  totalRecords,
  countLabel,
}) => {
  const [anchorEl, setAnchorEl] = useState(null);

  const AGE_FILTERS = [
    { label: "< 3 DAYS", value: "<3" },
    { label: "3 - 6 DAYS", value: "3-6" },
    { label: "> 6 DAYS", value: ">6" },
  ];

  const STATUS_FILTERS = [
    { label: "ACTION REQUIRED", value: "pending" },
    { label: "ACCEPTED", value: "accepted" },
    { label: "L0 DATA", value: "rejected" },
    { label: "ON HOLD", value: "On Hold" },
  ];

  const STAGE_FILTERS = [
    { label: "VALIDATION IN PROGRESS", value: "validation inprogress,validation initiated" },
    { label: "STANDARDIZATION IN PROGRESS", value: "standardization inprogress" },
  ];

  const baseFilters = showAgeFilters
    ? AGE_FILTERS
    : showStatusFilters
      ? STATUS_FILTERS
      : [];

  const visibleFilters = baseFilters.filter(
    (f) => !f.value || !allowedFilters || allowedFilters.includes(f.value)
  );

  const handleFilterClick = (value) => {
    onFilterChange(value);
  };

  // Map filter value → summary key from API / WS response
  const STATUS_KEY_MAP = {
    pending: "PENDING",
    accepted: "ACCEPTED",
    rejected: "REJECTED",
    "On Hold": "ON HOLD",
    "validation inprogress,validation initiated": "VALIDATION_IN_PROGRESS",
    "standardization inprogress": "STANDARDIZATION_IN_PROGRESS",
  };
  const AGE_KEY_MAP = { "<3": "green", "3-6": "yellow", ">6": "red" };

  const getCount = (filterValue) => {
    if (!counts) return null;

    if (filterValue === "validation inprogress,validation initiated") {
      const init = counts.VALIDATION_INITIATED || 0;
      const prog = counts.VALIDATION_IN_PROGRESS || 0;
      // If both are 0, might mean the keys aren't in this message; 
      // but usually we want to show 0 if explicitly present.
      // We'll return the sum if either exists.
      if (counts.VALIDATION_INITIATED === undefined && counts.VALIDATION_IN_PROGRESS === undefined) return null;
      return init + prog;
    }

    const key = STATUS_KEY_MAP[filterValue] ?? AGE_KEY_MAP[filterValue];
    const val = key !== undefined ? counts[key] : undefined;
    return val !== undefined ? val : null;
  };

  return (
    <Box>

      {/* Page Header */}
      <Box sx={{ px: 3, pt: 3, pb: 1.5, backgroundColor: "#ebebebff" }}>
        <Typography
          sx={{ fontSize: 20, fontWeight: 700, color: "#000", lineHeight: 1.2 }}
        >
          {title}
        </Typography>
      </Box>

      {/* Filter + Search Row */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 3,
          py: 0.75,
          flexWrap: "wrap",
          minHeight: 48,
        }}
      >
        {/* Search */}
        <TextField
          placeholder="Search for a ExecutionID/ BenchmarkType/ BenchmarkCategory"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          variant="outlined"
          size="small"
          sx={{
            width: 380,
            mr: 1,
            "& .MuiOutlinedInput-root": {
              borderRadius: "2px",
              fontSize: 12,
              height: 40,
              backgroundColor: "#fff",
              "& fieldset": { borderColor: "#bbb" },
              "&:hover fieldset": { borderColor: "#555" },
              "&.Mui-focused fieldset": { borderColor: "#000", borderWidth: "1px" },
            },
            "& input": { px: 1, py: 0.5, fontSize: 12 },
          }}
          slotProps={{
            input: {
              endAdornment: loading ? (
                <InputAdornment position="end">
                  <CircularProgress size={12} color="inherit" />
                </InputAdornment>
              ) : null,
            },
          }}
        />

        {/* Unified Filter Dropdown */}
        <Box>
          <Box
            onClick={(e) => setAnchorEl(e.currentTarget)}
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 1,
              px: 1.5,
              height: 40,
              minWidth: 160,
              border: "1px solid #bbb",
              borderRadius: "2px",
              backgroundColor: "#fff",
              cursor: "pointer",
              "&:hover": { borderColor: "#555" },
            }}
          >
            <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", letterSpacing: 0.5 }}>
              {showAgeFilters ? "AGE" : "STATE"}
              {filter.length > 0 && (
                <Box component="span" sx={{ color: "#777", ml: 0.5, fontWeight: 400 }}>
                  ({filter.length})
                </Box>
              )}
            </Typography>
            <KeyboardArrowDownIcon sx={{ fontSize: 18, color: "#777" }} />
          </Box>

          <Popover
            open={Boolean(anchorEl)}
            anchorEl={anchorEl}
            onClose={() => setAnchorEl(null)}
            anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
            transformOrigin={{ vertical: "top", horizontal: "left" }}
            slotProps={{
              paper: {
                sx: {
                  mt: 0.5,
                  borderRadius: "2px",
                  boxShadow: "0 4px 20px rgba(0,0,0,0.08)",
                  border: "1px solid #ddd",
                  minWidth: 200,
                },
              },
            }}
          >
            <Stack sx={{ p: 1 }} gap={0.5}>
              {visibleFilters.map((f) => {
                const isActive = f.value === "" ? filter.length === 0 : filter.includes(f.value);
                return (
                  <Box
                    key={f.value || "all"}
                    onClick={() => handleFilterClick(f.value)}
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 1,
                      px: 1,
                      py: 1,
                      cursor: "pointer",
                      borderRadius: "2px",
                      "&:hover": { backgroundColor: "#f5f5f5" },
                    }}
                  >
                    <Checkbox
                      checked={isActive}
                      size="small"
                      sx={{ p: 0, color: "#999", "&.Mui-checked": { color: "#000" } }}
                    />
                    <Typography sx={{ fontSize: 12, fontWeight: 550, color: "#111", display: "flex", alignItems: "center", gap: 0.5 }}>
                      {f.label}
                      <Box component="span" sx={{ fontSize: 11, fontWeight: 400, color: "#888" }}>
                        ({loading ? "0" : getCount(f.value)?.toLocaleString() || "0"})
                      </Box>
                    </Typography>
                  </Box>
                );
              })}

              {/* Stage filters — only on pages that opt in (landing/dashboard) */}
              {showStageFilters && (
                <>
                  <Divider sx={{ my: 0.5 }} />
                  {STAGE_FILTERS.map((f) => {
                    const isActive = filter.includes(f.value);
                    return (
                      <Box
                        key={f.value}
                        onClick={() => handleFilterClick(f.value)}
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 1,
                          px: 1,
                          py: 1,
                          cursor: "pointer",
                          borderRadius: "2px",
                          "&:hover": { backgroundColor: "#f5f5f5" },
                        }}
                      >
                        <Checkbox
                          checked={isActive}
                          size="small"
                          sx={{ p: 0, color: "#999", "&.Mui-checked": { color: "#000" } }}
                        />
                        <Typography sx={{ fontSize: 12, fontWeight: 550, color: "#111", display: "flex", alignItems: "center", gap: 0.5 }}>
                          {f.label}
                          <Box component="span" sx={{ fontSize: 11, fontWeight: 400, color: "#888" }}>
                            ({loading ? "0" : getCount(f.value)?.toLocaleString() || "0"})
                          </Box>
                        </Typography>
                      </Box>
                    );
                  })}
                </>
              )}
            </Stack>
          </Popover>
        </Box>

        <Box sx={{ flex: 1 }} />

        {/* Record Count */}
        {totalRecords !== undefined && (
          <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#000", pr: 1 }}>
            No.of Records: {totalRecords}
          </Typography>
        )}
      </Box>
    </Box>
  );
};

export default ListHeader;