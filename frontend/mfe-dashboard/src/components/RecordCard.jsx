import React, { useState, useEffect } from "react";
import InconsistentFieldsList from "./InconsistentFieldsList";
import { useNavigate } from "react-router-dom";
import { Box, Typography, IconButton } from "@mui/material";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";

/**
 * Derives the progress percentage and display label from the Stage / isValid fields.
 *
 * Stage values (case-insensitive):
 *   validation_inprogress          → 25 %
 *   validation_completed + isValid:true  → show "Valid" message  (no bar)
 *   validation_completed + isValid:false → 50 %
 *   standardization_inprogress     → 75 %
 *   standardization_completed      → 100 % then auto-dismiss after 3 s
 */
const getStageInfo = (stage, isValid) => {
  if (!stage) return null;

  // Normalize: lowercase, trim, then collapse any run of spaces/underscores → single underscore
  const s = stage.toLowerCase().trim().replace(/[\s_]+/g, "_");

  console.debug("[RecordCard] Stage raw:", stage, "→ normalized:", s, "isValid:", isValid);

  if (s === "validation_initiated" || s === "validation_inprogress") {
    return { pct: 25, label: "Validation in progress", isValid: null };
  }
  if (s === "validation_completed") {
    if (isValid === true)
      return { pct: null, label: "This record is valid", isValid: true };
    return { pct: 50, label: "Validation done — proceeding to standardization", isValid: false };
  }
  // Synthetic flash stage — shown for 1.5s before record is removed when validation filter active
  if (s === "validation_completing") {
    return { pct: 50, label: "Validation complete ✓", isValid: null };
  }
  if (s === "validation_failed") {
    return { pct: null, label: "Validation failed", isValid: null };
  }
  if (s === "standardization_inprogress") {
    return { pct: 75, label: "Standardization in progress…", isValid: null };
  }
  // standardization_completing is a synthetic stage set by the WS hook just
  // before removing a card — gives a 1.5s flash of the completed bar.
  if (s === "standardization_completing") {
    return { pct: 100, label: "Standardization complete ✓", isValid: null };
  }
  // standardization_completed = record is fully done and came from the API.
  // Show the normal Status + Inconsistent Fields panel (no progress bar).
  if (s === "standardization_completed") return null;
  if (s === "standardization_failed") {
    return { pct: null, label: "Standardization failed", color: "#ef4444", isValid: null };
  }

  console.warn("[RecordCard] Unrecognised stage value:", stage);
  return null;
};


/** Pipeline style progress */
const PipelineProgress = ({ pct, label }) => {
  const segments = [
    { threshold: 25, name: "Validation In Progress" },
    { threshold: 50, name: "Validation Completed" },
    { threshold: 75, name: "Standardization In Progress" },
    { threshold: 100, name: "Standardization Completed" },
  ];

  const themeColor = "#1b1b1b";

  return (
    <Box sx={{ display: "flex", flexDirection: "column", justifyContent: "center", width: "100%", maxWidth: 500 }}>
      {/* 4 Pipes */}
      <Box sx={{ display: "flex", gap: 0.8, height: 8, mb: 0.8 }}>
        {segments.map((seg) => {
          const isPassed = pct >= seg.threshold;
          const isCurrent = pct === seg.threshold;
          return (
            <Box
              key={seg.threshold}
              sx={{
                flex: 1,
                borderRadius: 99,
                backgroundColor: isPassed ? themeColor : "#e6e6e6",
                opacity: isPassed && !isCurrent ? 0.7 : 1, // dims previous completed pipes slightly
                transition: "background-color 0.4s ease, opacity 0.4s ease",
              }}
            />
          );
        })}
      </Box>
      
      {/* Pipe Labels */}
      <Box sx={{ display: "flex", gap: 0.8 }}>
        {segments.map((seg) => {
          const isPassed = pct >= seg.threshold;
          const isCurrent = pct === seg.threshold;
          return (
            <Typography
              key={seg.threshold}
              sx={{
                flex: 1,
                fontSize: 10,
                fontWeight: isCurrent ? 700 : 600,
                color: isCurrent ? themeColor : isPassed ? "#6b7280" : "#a1a1aa",
                textAlign: "center",
                lineHeight: 1.1,
              }}
            >
              {seg.name}
            </Typography>
          );
        })}
      </Box>
    </Box>
  );
};

const RecordCard = ({ record, index = 0, mode }) => {
  const [isClicked, setIsClicked] = useState(false);
  const invalidFields = record["InvalidFields"];
  const navigate = useNavigate();
  const status = record.Status?.toLowerCase();
  const isCompleted = status === "accepted" || status === "approved";
  const isEven = index % 2 === 0;

  const stageInfo = getStageInfo(record.Stage, record.isValid);

  // Show the stage panel only when there is actionable stage info
  const showStagePanelInsteadOfStatus = !!stageInfo;

  const stopAndNavigate = (e) => {
    e.stopPropagation();
    setIsClicked(true);
    navigate(`/details/${record.ExecutionId}`);
  };

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "space-between",
        px: 3,
        height: 78,
        width: "97%",
        mb: "6px",
        py: 2,
        backgroundColor: "#ffffff",
        boxShadow: "0 2px 8px rgba(0,0,0,0.07)",
        transition: "background-color 0.1s ease, box-shadow 0.1s ease",
        gap: 2,
        alignItems: "center",
      }}
    >
      {/* Execution ID */}
      <Box sx={{ width: "18%", pr: 2, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Execution ID
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", wordBreak: "break-all", lineHeight: 1.2 }}>
          {record.ExecutionId}
        </Typography>
      </Box>

      {/* Updated On */}
      <Box sx={{ width: "7%", pr: 2, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Updated On
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", lineHeight: 1.2 }}>
          {new Date(record.updatedOn).toLocaleDateString()}
        </Typography>
      </Box>

      {/* Benchmark Category */}
      <Box sx={{ width: "8%", pr: 2, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Benchmark Category
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", lineHeight: 1.2 }}>
          {record.BenchmarkCategory}
        </Typography>
      </Box>

      {/* Benchmark Type */}
      <Box sx={{ width: "10%", pr: 2, flexShrink: 0 }}>
        <Typography sx={{ fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Benchmark Type
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", lineHeight: 1.2 }}>
          {record.BenchmarkType}
        </Typography>
      </Box>

      {/* ──────────────────────────────────────────────────────────
           STAGE PANEL  ↔  STATUS + INCONSISTENT FIELDS
          When stage info is present (and not yet dismissed), we
          replace the right section with the progress panel.
      ────────────────────────────────────────────────────────── */}
      {showStagePanelInsteadOfStatus ? (
        /* ── Stage progress / valid message ── */
        <Box
          sx={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            gap: 1.5,
            pr: 2,
            overflow: "hidden",
          }}
        >
          {stageInfo.isValid === true ? (
            /* "This record is valid" message */
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <CheckCircleOutlineIcon sx={{ fontSize: 18, color: "#22c55e" }} />
              <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: "#22c55e" }}>
                This record is valid
              </Typography>
            </Box>
          ) : (
            /* 25 / 50 / 75 % bars */
            <PipelineProgress pct={stageInfo.pct} label={stageInfo.label} />
          )}
        </Box>
      ) : (
        /* ── Normal: Status + Inconsistent Fields ── */
        <>
          {/* Status */}
          <Box sx={{ width: "6%", pr: 2, flexShrink: 0 }}>
            <Typography sx={{ fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Status
            </Typography>
            <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#111", lineHeight: 1.2 }}>
              {record.Status?.toLowerCase() === "rejected"
                ? "L0 Data"
                : record.Status?.toLowerCase() === "pending"
                ? "ACTION REQUIRED"
                : record.Status}
            </Typography>
          </Box>

          {/* Inconsistent Fields */}
          <Box sx={{ width: "39%", pr: 2, flexShrink: 0 }}>
            <Typography
              sx={{
                fontSize: 11, color: "#777", fontWeight: 700, mb: 0.3,
                textTransform: "uppercase", letterSpacing: 0.5,
                visibility: isCompleted ? "hidden" : "visible",
              }}
            >
              Inconsistent Fields
            </Typography>
            <Box sx={{ visibility: isCompleted ? "hidden" : "visible", minHeight: 22 }}>
              <InconsistentFieldsList
                invalidFields={invalidFields}
                SuggestionsCount={record.suggestionsCount}
                status={record.Status}
              />
            </Box>
          </Box>
        </>
      )}

      {/* Actions — hide when record is still in-pipeline (stage panel showing) or has no valid status */}
      {!showStagePanelInsteadOfStatus && record.Status && record.Status !== "N/A" && (
        <Box sx={{ display: "flex", gap: 0.5, alignItems: "center", pt: 0.5, flexShrink: 0 }}>
          <IconButton
            size="medium"
            onClick={stopAndNavigate}
            title="View Details"
            sx={{
              border: "1px solid #c8c8c8",
              borderRadius: "2px",
              p: 0.5,
              mt: 1,
              backgroundColor: isClicked ? "#fef7f7ff" : "#000",
              color: "#ffffffff",
              borderColor: "#000",
              "&:hover": { backgroundColor: "#fef7f7ff", color: "#000", borderColor: "#000" },
            }}
          >
            <VisibilityOutlinedIcon sx={{ fontSize: 15 }} />
          </IconButton>
        </Box>
      )}
    </Box>
  );
};

export default RecordCard;
