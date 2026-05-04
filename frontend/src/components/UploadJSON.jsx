import React, { useState, useRef } from "react";
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  CircularProgress,
  Box,
  Typography,
  Snackbar,
  Alert,
  Tooltip,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import InsertDriveFileOutlinedIcon from "@mui/icons-material/InsertDriveFileOutlined";
import { API_URL } from "../config";
import { useRefresh } from "../context/RefreshContext";

const UploadJSON = () => {
  const { triggerRefresh } = useRefresh();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  const fileInputRef = useRef(null);

  const handleSnackbarClose = () => setSnackbar((s) => ({ ...s, open: false }));

  const showNotification = (message, type) =>
    setSnackbar({ open: true, message, severity: type });

  const handleOpenDialog = () => {
    setSelectedFile(null);
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    if (loading) return;
    setDialogOpen(false);
    setSelectedFile(null);
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.type === "application/json" || file.name.endsWith(".json")) {
      setSelectedFile(file);
    } else {
      showNotification("Only JSON files are accepted.", "error");
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (loading) return;
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (file.type === "application/json" || file.name.endsWith(".json")) {
      setSelectedFile(file);
    } else {
      showNotification("Only JSON files are accepted.", "error");
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    const formData = new FormData();
    formData.append("file", selectedFile);
    setLoading(true);
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
      setDialogOpen(false);
      setSelectedFile(null);
      triggerRefresh(); // ← triggers RecordsListPage refresh
    } catch (err) {
      showNotification(err.message || "Upload failed. Please try again.", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Tooltip title="Upload execution data in JSON" placement="bottom" arrow>
        <Button
          onClick={handleOpenDialog}
          startIcon={<UploadFileIcon sx={{ fontSize: "0.9rem !important" }} />}
          sx={{
            fontFamily: "'Inter', sans-serif",
            fontWeight: 600,
            fontSize: "0.75rem",
            textTransform: "none",
            letterSpacing: 0.3,
            color: "#1a1a1a",
            backgroundColor: "#f0f0f0",
            border: "1px solid #d8d8d8",
            px: 1.8,
            py: 0.5,
            minHeight: "30px",
            borderRadius: "2px",
            boxShadow: "none",
            "&:hover": {
              backgroundColor: "#e4e4e4",
              boxShadow: "none",
            },
          }}
        >
          Upload
        </Button>
      </Tooltip>

      <Dialog
        open={dialogOpen}
        onClose={handleCloseDialog}
        maxWidth="xs"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: "12px",
            backgroundColor: "#fafafa",
            border: "1px solid #e8e8e8",
            boxShadow: "0 8px 32px rgba(0,0,0,0.08)",
          },
        }}
      >
        <DialogTitle
          sx={{
            fontFamily: "'Inter', sans-serif",
            fontWeight: 700,
            fontSize: "0.95rem",
            color: "#111",
            pb: 0.5,
            pt: 2.5,
            px: 3,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          Upload Execution Data
          <IconButton
            onClick={handleCloseDialog}
            disabled={loading}
            size="small"
            sx={{ color: "#bbb", "&:hover": { color: "#555" } }}
          >
            <CloseIcon sx={{ fontSize: "1rem" }} />
          </IconButton>
        </DialogTitle>

        <DialogContent sx={{ px: 3, pt: 2, pb: 1 }}>
          <Typography
            sx={{
              fontFamily: "'Inter', sans-serif",
              fontSize: "0.75rem",
              color: "#888",
              mb: 2,
            }}
          >
            Select a JSON file from your system to upload execution data.
          </Typography>

          <Box
            onClick={() => { if (!loading) fileInputRef.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); if (!loading) setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            sx={{
              maxWidth: "50vw",
              border: `1.5px dashed ${loading ? "#e0e0e0" : dragOver ? "#555" : selectedFile ? "#4caf50" : "#ccc"}`,
              borderRadius: "10px",
              p: 3.5,
              textAlign: "center",
              cursor: loading ? "not-allowed" : "pointer",
              backgroundColor: loading ? "#f7f7f7" : dragOver ? "#f0f0f0" : selectedFile ? "#f6fff6" : "#fff",
              opacity: loading ? 0.6 : 1,
              transition: "all 0.15s ease",
              pointerEvents: loading ? "none" : "auto",
              "&:hover": !loading ? {
                borderColor: "#999",
                backgroundColor: "#f5f5f5",
              } : {},
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              style={{ display: "none" }}
              onChange={handleFileChange}
              disabled={loading}
            />

            {selectedFile ? (
              <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0.8 }}>
                <InsertDriveFileOutlinedIcon sx={{ color: loading ? "#bbb" : "#4caf50", fontSize: "2.2rem" }} />
                <Typography
                  sx={{
                    fontFamily: "'Inter', sans-serif",
                    fontSize: "0.82rem",
                    fontWeight: 600,
                    color: loading ? "#aaa" : "#2e7d32",
                    maxWidth: "70vw",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {selectedFile.name}
                </Typography>
                <Typography sx={{ fontFamily: "'Inter', sans-serif", fontSize: "0.7rem", color: "#aaa" }}>
                  {(selectedFile.size / 1024).toFixed(1)} KB {!loading && "· Click to change file"}
                </Typography>
              </Box>
            ) : (
              <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0.8 }}>
                <UploadFileIcon sx={{ color: "#ccc", fontSize: "2.2rem" }} />
                <Typography sx={{ fontFamily: "'Inter', sans-serif", fontSize: "0.82rem", color: "#555" }}>
                  Drag & drop or{" "}
                  <span style={{ color: "#1a1a1a", fontWeight: 600, textDecoration: "underline" }}>
                    browse
                  </span>
                </Typography>
                <Typography sx={{ fontFamily: "'Inter', sans-serif", fontSize: "0.7rem", color: "#bbb" }}>
                  JSON files only
                </Typography>
              </Box>
            )}
          </Box>
        </DialogContent>

        <DialogActions sx={{ px: 3, pb: 2.5, pt: 1.5, gap: 1 }}>
          <Button
            onClick={handleUpload}
            disabled={!selectedFile || loading}
            variant="contained"
            disableElevation
            sx={{
              fontFamily: "'Inter', sans-serif",
              fontWeight: 700,
              fontSize: "0.78rem",
              textTransform: "none",
              px: 2.5,
              borderRadius: "6px",
              backgroundColor: "#1a1a1a",
              color: "#fff",
              "&:hover": { backgroundColor: "#333" },
              "&:disabled": { backgroundColor: "#e8e8e8", color: "#bbb" },
            }}
          >
            {loading ? (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <CircularProgress size={12} sx={{ color: "#aaa" }} />
                Uploading...
              </Box>
            ) : (
              "Upload"
            )}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={handleSnackbarClose}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
        sx={{ zIndex: 9999 }}
      >
        <Alert
          onClose={handleSnackbarClose}
          severity={snackbar.severity}
          variant="filled"
          sx={{ width: "100%" }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  );
};

export default UploadJSON;