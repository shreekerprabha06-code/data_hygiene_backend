import React from "react";
import { Box, Skeleton, Paper, Typography, Stack, Divider } from "@mui/material";

const DetailsSkeleton = () => {
  return (
    <Box sx={{ backgroundColor: "#ebebebff", minHeight: "100vh", p: 3, pt: 1 }}>
      {/* Execution Information Header Matching ExecutionInfoBox */}
      <Box sx={{ border: "1px solid #d0d0d0", background: "#ffffff", borderRadius: 2, p: 2.5, mb: 3.5 }}>
        <Typography variant="body2" sx={{ fontWeight: 800, color: "#0a0a0a", mb: 1.5, fontSize: 13, textTransform: "uppercase", letterSpacing: 1 }}>
          Execution Information
        </Typography>
        <Paper elevation={0} sx={{ border: "1px solid #d0d0d0", borderRadius: 2, bgcolor: "#f5f5f5", overflow: "hidden" }}>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" } }}>
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <Box key={i} sx={{ p: 1.75, borderRight: "1px solid #d0d0d0", borderBottom: i <= 3 ? "1px solid #d0d0d0" : "none" }}>
                <Skeleton variant="text" width="40%" height={12} sx={{ mb: 0.5 }} />
                <Skeleton variant="text" width="80%" height={20} />
              </Box>
            ))}
          </Box>
        </Paper>
      </Box>

      {/* Table Skeletons Matching CorrectionsTable Panels */}
      {[1, 2, 3].map((panel) => (
        <Paper key={panel} sx={{ mb: 2, borderRadius: 2, overflow: "hidden", border: "1px solid #e0e0e0" }}>
          {/* Panel Header */}
          <Box sx={{ p: 2, display: "flex", justifyContent: "space-between", alignItems: "center", bgcolor: "#fff" }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
              <Skeleton variant="text" width={150} height={24} />
              <Skeleton variant="rectangular" width={60} height={20} sx={{ borderRadius: 1 }} />
            </Box>
            <Skeleton variant="circular" width={24} height={24} />
          </Box>
          <Divider />
          {/* Panel Body (Existing Data Row Area) */}
          <Box sx={{ p: 2, bgcolor: "#fcfcfc" }}>
            <Stack direction="row" spacing={4}>
               {[1, 2, 3, 4].map(cell => (
                 <Box key={cell} sx={{ flex: 1 }}>
                   <Skeleton variant="text" width="60%" height={12} />
                   <Skeleton variant="text" width="90%" height={20} />
                 </Box>
               ))}
            </Stack>
          </Box>
          <Divider />
          {/* Suggestions Area */}
          <Box sx={{ p: 1.5, bgcolor: "#fff" }}>
            <Skeleton variant="text" width="100px" height={15} sx={{ mb: 1, ml: 1 }} />
            <Box sx={{ px: 1 }}>
               <Skeleton variant="rectangular" height={60} sx={{ mb: 1, borderRadius: 2 }} />
               <Skeleton variant="rectangular" height={60} sx={{ borderRadius: 2 }} />
            </Box>
          </Box>
        </Paper>
      ))}
    </Box>
  );
};

export default DetailsSkeleton;
