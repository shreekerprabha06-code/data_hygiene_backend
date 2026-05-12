import React from "react";
import { Box, Skeleton, Typography } from "@mui/material";

const RecordCardSkeleton = () => {
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
        gap: 2,
        alignItems: "center",
      }}
    >
      {/* Execution ID */}
      <Box sx={{ width: "18%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="60%" height={15} sx={{ mb: 0.5 }} />
        <Skeleton variant="text" width="90%" height={20} />
      </Box>

      {/* Updated On */}
      <Box sx={{ width: "7%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="80%" height={15} sx={{ mb: 0.5 }} />
        <Skeleton variant="text" width="100%" height={20} />
      </Box>

      {/* Benchmark Category */}
      <Box sx={{ width: "8%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="90%" height={15} sx={{ mb: 0.5 }} />
        <Skeleton variant="text" width="70%" height={20} />
      </Box>

      {/* Benchmark Type */}
      <Box sx={{ width: "10%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="90%" height={15} sx={{ mb: 0.5 }} />
        <Skeleton variant="text" width="80%" height={20} />
      </Box>

      {/* Status */}
      <Box sx={{ width: "6%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="80%" height={15} sx={{ mb: 0.5 }} />
        <Skeleton variant="text" width="100%" height={20} />
      </Box>

      {/* Inconsistent Fields */}
      <Box sx={{ width: "39%", pr: 2, flexShrink: 0 }}>
        <Skeleton variant="text" width="40%" height={15} sx={{ mb: 0.5 }} />
        <Box sx={{ display: "flex", gap: 1 }}>
          <Skeleton variant="rectangular" width={60} height={20} sx={{ borderRadius: 1 }} />
          <Skeleton variant="rectangular" width={80} height={20} sx={{ borderRadius: 1 }} />
        </Box>
      </Box>

      {/* Action Button */}
      <Box sx={{ flexShrink: 0 }}>
        <Skeleton variant="rectangular" width={32} height={32} sx={{ borderRadius: "2px" }} />
      </Box>
    </Box>
  );
};

const DashboardSkeleton = () => {
  return (
    <Box sx={{ py: 1 }}>
      {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
        <RecordCardSkeleton key={i} />
      ))}
    </Box>
  );
};

export default DashboardSkeleton;
