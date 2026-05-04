import React from "react";
import { Stack, Typography, Box } from "@mui/material";

const InconsistentFieldsList = ({ invalidFields = [], SuggestionsCount, status }) => {
  const errors = invalidFields;
  const MAX_VISIBLE = 3;

  const visibleErrors = errors.slice(0, MAX_VISIBLE);
  const remaining = errors.length - MAX_VISIBLE;

  return (
    <Stack direction="row" flexWrap="wrap" gap={0.4} alignItems="center">
      {visibleErrors.map((e, i) => (
        <Box
          key={i}
          sx={{
            px: 1,
            py: 0.1,
            fontSize: "0.68rem",
            fontWeight: 600,
            color: "#333",
            backgroundColor: "#f0f0f0",
            border: "1px solid #d0d0d0",
            borderRadius: "2px",
            lineHeight: 1.6,
            whiteSpace: "nowrap",
          }}
        >
          {e}
        </Box>
      ))}

      {remaining > 0 && (
        <Typography sx={{ fontSize: "0.68rem", color: "#888", alignSelf: "center" }}>
          +{remaining} more
        </Typography>
      )}

      {status?.toLowerCase() === "pending" && SuggestionsCount === true && (
        <Typography sx={{ fontSize: "0.68rem", color: "#555", fontStyle: "italic", ml: 0.5 }}>
          · suggestions available
        </Typography>
      )}
    </Stack>
  );
};

export default InconsistentFieldsList;