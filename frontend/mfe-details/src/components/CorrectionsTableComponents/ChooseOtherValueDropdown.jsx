import React, { useState } from "react";
import { Box, Typography, Autocomplete, TextField, CircularProgress } from "@mui/material";
import { SELECTED } from "../../utils/correctionsTableConstants";
import { API_URL } from "../../config";
import { useUniqueValues } from "../../hooks/useUniqueValues";

const ChooseOtherValueDropdown = ({
  invalidField,
  isSelected,
  onCustomMetadataFetch,
  onSelectCustom,
  onClearCustom,
  isPending = true,
  theme,
}) => {
  const primaryField = invalidField?.split(",")[0].trim() || "";
  const { options, loading, fetchOptions } = useUniqueValues(primaryField);
  const [fetchingMeta, setFetchingMeta] = useState(false);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(null);

  if (!isPending) return;

  const handleOpen = () => {
    if (!isPending) return;
    setOpen(true);
    fetchOptions();
  };

  const handleChange = async (newVal) => {
    if (!isPending) return;
    setValue(newVal);
    if (!newVal) {
      if (onClearCustom) onClearCustom();
      return;
    }

    setFetchingMeta(true);
    try {
      const res = await fetch(`${API_URL}/metadata-values/${encodeURIComponent(primaryField)}/${encodeURIComponent(newVal)}`);
      const json = await res.json();

      let records = [];
      if (json?.metadata_records && Array.isArray(json.metadata_records)) {
        records = json.metadata_records;
      } else if (json?.data) {
        records = [{ metadata: json.data }];
      } else if (json?.metadata) {
        records = [{ metadata: json.metadata }];
      } else {
        records = [{ metadata: json }];
      }

      onCustomMetadataFetch({ value: newVal, records });
    } catch (err) {
      console.error("metadata-values fetch error:", err);
    } finally {
      setFetchingMeta(false);
    }
  };

  const p = theme || SELECTED;

  return (
    <Box
      sx={{
        mx: 1.5,
        mb: 1,
        py: 0.35,
        px: 1,
        display: "flex",
        alignItems: "center",
        gap: 1.5,
        borderRadius: 2,
        opacity: isPending ? 1 : 0.5,
        pointerEvents: isPending ? "auto" : "none",
      }}
    >

      <Box sx={{ flex: 1, px: 1.5, py: 0.5 }}>
        <Typography sx={{ fontSize: 11, fontWeight: 600, color: "#303030", mb: 0.5 }}>
          Choose other {invalidField}:
        </Typography>
        <Autocomplete
          size="small"
          open={open}
          onOpen={handleOpen}
          onClose={() => setOpen(false)}
          options={options}
          loading={loading}
          value={value}
          disabled={!isPending}
          onChange={(_, newVal) => handleChange(newVal)}
          sx={{ maxWidth: 300 }}
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder="Search or select..."
              sx={{
                "& .MuiOutlinedInput-root.Mui-focused fieldset": {
                  borderColor: "#000",
                },
              }}
              slotProps={{
                input: {
                  ...params.InputProps,
                  endAdornment: (
                    <React.Fragment>
                      {loading || fetchingMeta ? (
                        <CircularProgress sx={{ color: "#000" }} size={20} />
                      ) : null}
                      {params.InputProps.endAdornment}
                    </React.Fragment>
                  ),
                },
              }}
            />
          )}
        />
      </Box>
    </Box>
  );
};

export default ChooseOtherValueDropdown;