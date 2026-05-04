import React, { useState, useRef } from "react";
import {
  Box,
  Typography,
  Button,
  CircularProgress,
  Snackbar,
  Alert,
  TextField,
  InputAdornment,
} from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import InsertDriveFileOutlinedIcon from "@mui/icons-material/InsertDriveFileOutlined";
import Navbar from "../components/Navbar";
import RecordList from "../components/RecordList";
import ErrorPage from "../components/ErrorPage";
import { usePaginatedRecords } from "../hooks/usePaginatedRecords";
import { API_URL } from "../config";

const PIPELINE_STAGES = [
  "validation initiated",
  "validation inprogress",
  "validation completed",
  "validation failed",
  "standardization inprogress",
  "standardization failed",
].join(",");

const UploadPage = () => {
  const fileInputRef = useRef(null);

  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  const handleSnackbarClose = () => setSnackbar((s) => ({ ...s, open: false }));
  const showNotification = (message, severity) =>
    setSnackbar({ open: true, message, severity });

  const acceptFile = (file) => {
    if (!file) return;
    if (file.type === "application/json" || file.name.endsWith(".json")) {
      setSelectedFile(file);
    } else {
      showNotification("Only JSON files are accepted.", "error");
    }
  };

  const handleFileChange = (e) => acceptFile(e.target.files[0]);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (!uploading) acceptFile(e.dataTransfer.files[0]);
  };

  const extraParams = { stage: PIPELINE_STAGES };

  const {
    records,
    totalRecords,
    totalPages,
    page,
    loading,
    error,
    searchInput,
    setSearchInput,
    search,
    loadMore,
    retry,
    refresh,
    patchRecords,
    removeRecords,
    isReadyState,
  } = usePaginatedRecords({ extraParams });

  const isSearching = loading && searchInput !== search;

  const handleUpload = async () => {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append("file", selectedFile);
    setUploading(true);
    try {
      const response = await fetch(`${API_URL}/upload-execution-data`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw new Error(err?.detail || `Server error: ${response.status}`);
      }
      showNotification("File uploaded successfully!", "success");
      setSelectedFile(null);
      refresh();
    } catch (err) {
      showNotification(err.message || "Upload failed. Please try again.", "error");
    } finally {
      setUploading(false);
    }
  };

  if (error) {
    return <ErrorPage message={error?.message || "Something went wrong"} onRetry={retry} />;
  }

  return (
    <Box sx={{ backgroundColor: "#ebebebff", minHeight: "100vh" }}>
      <Navbar />

      <Box sx={{ px: 3, pt: 10, pb: 1.5, backgroundColor: "#ebebebff" }}>
        <Typography sx={{ fontSize: 20, fontWeight: 700, color: "#000", lineHeight: 1.2 }}>
          Upload Execution Data
        </Typography>
      </Box>

      {/* Upload Area */}
      <Box sx={{ px: 3, py: 2 }}>
        <Box
          onClick={() => { if (!uploading) fileInputRef.current?.click(); }}
          onDragOver={(e) => { e.preventDefault(); if (!uploading) setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          sx={{
            border: `1.5px dashed ${uploading ? "#e0e0e0" : dragOver ? "#555" : selectedFile ? "#4caf50" : "#ccc"}`,
            borderRadius: "6px",
            p: 3,
            textAlign: "center",
            cursor: uploading ? "not-allowed" : "pointer",
            backgroundColor: uploading ? "#f7f7f7" : dragOver ? "#f0f0f0" : selectedFile ? "#f6fff6" : "#fff",
            opacity: uploading ? 0.6 : 1,
            transition: "all 0.15s ease",
            pointerEvents: uploading ? "none" : "auto",
            "&:hover": !uploading ? { borderColor: "#999", backgroundColor: "#f5f5f5" } : {},
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={handleFileChange}
            disabled={uploading}
          />

          {selectedFile ? (
            <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0.8 }}>
              <InsertDriveFileOutlinedIcon sx={{ color: uploading ? "#bbb" : "#4caf50", fontSize: "2rem" }} />
              <Typography sx={{ fontSize: "0.82rem", fontWeight: 600, color: uploading ? "#aaa" : "#2e7d32", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
                {selectedFile.name}
              </Typography>
              <Typography sx={{ fontSize: "0.7rem", color: "#aaa" }}>
                {(selectedFile.size / 1024).toFixed(1)} KB {!uploading && "· Click to change file"}
              </Typography>
            </Box>
          ) : (
            <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0.8 }}>
              <UploadFileIcon sx={{ color: "#ccc", fontSize: "2rem" }} />
              <Typography sx={{ fontSize: "0.82rem", color: "#555" }}>
                Drag & drop or{" "}
                <span style={{ color: "#1a1a1a", fontWeight: 600, textDecoration: "underline" }}>browse</span>
              </Typography>
              <Typography sx={{ fontSize: "0.7rem", color: "#bbb" }}>JSON files only</Typography>
            </Box>
          )}
        </Box>

        {selectedFile && (
          <Box sx={{ mt: 1.5, display: "flex", justifyContent: "flex-end" }}>
            <Button
              onClick={handleUpload}
              disabled={uploading}
              variant="contained"
              disableElevation
              sx={{
                fontWeight: 700,
                fontSize: "0.78rem",
                textTransform: "none",
                px: 2.5,
                borderRadius: "4px",
                backgroundColor: "#1a1a1a",
                color: "#fff",
                "&:hover": { backgroundColor: "#333" },
                "&:disabled": { backgroundColor: "#e8e8e8", color: "#bbb" },
              }}
            >
              {uploading ? (
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <CircularProgress size={12} sx={{ color: "#aaa" }} />
                  Uploading...
                </Box>
              ) : "Upload"}
            </Button>
          </Box>
        )}
      </Box>

      {/* Search + Records */}
      <Box sx={{ px: 3, pb: 0.75 }}>
        <TextField
          placeholder="Search for an ExecutionID / BenchmarkType / BenchmarkCategory"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          variant="outlined"
          size="small"
          sx={{
            width: 380,
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
              endAdornment: isSearching ? (
                <InputAdornment position="end">
                  <CircularProgress size={12} color="inherit" />
                </InputAdornment>
              ) : null,
            },
          }}
        />
      </Box>

      <Box sx={{ px: 3, py: 1 }}>
        <RecordList
          records={records}
          totalRecords={totalRecords}
          totalPages={totalPages}
          page={page}
          loading={loading}
          onLoadMore={loadMore}
          patchRecords={patchRecords}
          removeRecords={removeRecords}
          isReadyState={isReadyState}
          // no activeFilters — show everything on UploadPage
        />

        {!loading && records.length === 0 && (
          <Box sx={{ textAlign: "center", py: 8, backgroundColor: "#ebebebff", border: "1px solid #e0e0e0", borderTop: "none" }}>
            <Typography variant="h6" color="text.secondary" sx={{ fontSize: 14 }}>
              No records currently in the pipeline.
            </Typography>
          </Box>
        )}
      </Box>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={handleSnackbarClose}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
        sx={{ zIndex: 9999 }}
      >
        <Alert onClose={handleSnackbarClose} severity={snackbar.severity} variant="filled" sx={{ width: "100%" }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default UploadPage;