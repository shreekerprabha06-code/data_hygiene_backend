import React from "react";
import { Box, Paper, Typography } from "@mui/material";

const COLUMNS = 3;

const ExecutionInfoBox = ({ executionInfo }) => {
  const entries = Object.entries(executionInfo);

  return (
    <Box
      sx={{
        border: "1px solid #d0d0d0",
        background: "#ffffff",
        borderRadius: 2,
        p: 2.5,
        mb: 3.5,
      }}
    >
      <Typography variant="body2" sx={{ fontWeight: 800, color: "#0a0a0a", mb: 1.5, fontSize: 13, textTransform: "uppercase", letterSpacing: 1 }}>
        Execution Information
      </Typography>

      <Paper
        elevation={0}
        sx={{
          border: "1px solid #d0d0d0",
          borderRadius: 2,
          bgcolor: "#f5f5f5",
          overflow: "hidden",
        }}
      >
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: `repeat(${COLUMNS}, 1fr)` },
          }}
        >
          {entries.map(([key, value], index) => {
            const isLastInRow = (index + 1) % COLUMNS === 0;
            const isLastRow = index >= entries.length - (entries.length % COLUMNS || COLUMNS);

            return (
              <Box
                key={key}
                sx={{
                  p: 1.75,
                  borderRight: { md: isLastInRow ? "none" : "1px solid #d0d0d0" },
                  borderBottom: isLastRow ? "none" : "1px solid #d0d0d0"
                }}
              >
                <Typography sx={{ fontSize: 10, color: "#555555", fontWeight: 700, mb: 0.5, textTransform: "uppercase", letterSpacing: 0.8 }}>
                  {key}
                </Typography>
                <Typography sx={{ fontSize: 14, color: "#0a0a0a", fontWeight: 700 }}>
                  {value ? value : "—"}
                </Typography>
              </Box>
            );
          })}
        </Box>
      </Paper>
    </Box>
  );
};

export default ExecutionInfoBox;