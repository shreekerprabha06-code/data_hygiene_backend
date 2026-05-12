import React, { useState } from "react";
import { AppBar, Toolbar, Typography, Box, Menu, MenuItem, Tooltip, Stack, Divider, Chip } from "@mui/material";
import { useNavigate, useLocation } from "react-router-dom";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import ArrowForwardIosIcon from "@mui/icons-material/ArrowForwardIos";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import LogoutIcon from "@mui/icons-material/Logout";
import { getSession, logout } from "@data-hygiene/core";
import UploadJSON from "./UploadJSON";

const NAV_LINKS = [
  { label: "Dashboard", path: "/" },
  {
    category: "My List",
    items: [
      { label: "Active List", path: "/active" },
      { label: "On Hold", path: "/on-hold" },
      { label: "Completed List", path: "/completed" }
      
    ],
  },
  { label: "Master List", path: "/masterlist" },
];

const Navbar = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [anchorEl, setAnchorEl] = useState(null);
  const open = Boolean(anchorEl);
  
  const user = getSession();

  const handleOpen = (e) => setAnchorEl(e.currentTarget);
  const handleClose = () => setAnchorEl(null);

  const handleNavigate = (path) => {
    navigate(path);
    handleClose();
  };

  const dropdownLinks = NAV_LINKS;

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{ backgroundColor: "#000000", borderBottom: "1px solid #222" }}
    >
      <Toolbar sx={{ justifyContent: "space-between", minHeight: "55px !important", px: 3 }}>
        {/* Left: Logo + Dropdown trigger box */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
          {/* AMD Wordmark */}
          <Typography
            variant="h6"
            fontWeight={800}
            onClick={() => navigate("/")}
            sx={{
              cursor: "pointer",
              letterSpacing: -0.5,
              fontSize: "1.1rem",
              color: "#fff",
              fontFamily: "'Inter', sans-serif",
              transition: "color 0.2s ease",
              "&:hover": { color: "#ccc" },
            }}
          >
            AMD_DH
          </Typography>

          {/* Thin vertical divider */}
          <Box sx={{ width: "1px", height: 18, backgroundColor: "#444" }} />

          {/* Dropdown trigger — full-height dark box, label left, arrow right */}
          <Box
            onClick={handleOpen}
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-start",
              gap: 1.5,
              px: 2,
              height: "55px",
              cursor: "pointer",
              backgroundColor: "#000000ff",
              transition: "background-color 0.15s ease",
              "&:hover": { color: "#1d1c1cff" },
            }}
          >
            <Typography
              sx={{
                color: "#fff",
                fontSize: "0.78rem",
                fontWeight: 600,
                fontFamily: "'Inter', sans-serif",
                letterSpacing: 0.8,
                textTransform: "uppercase",
                userSelect: "none",
              }}
            >
              {"Data Hygiene"}
            </Typography>

            <KeyboardArrowDownIcon
              sx={{
                fontSize: 16,
                color: "#fff",
                transition: "transform 0.2s ease",
                transform: open ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </Box>

          {/* Dropdown panel — seamless extension of the trigger box */}
          <Menu
            anchorEl={anchorEl}
            open={open}
            onClose={handleClose}
            disableScrollLock
            PaperProps={{
              elevation: 0,
              sx: {
                mt: 0,
                width: anchorEl?.offsetWidth ?? 180,
                borderRadius: 0,
                backgroundColor: "#111",
                border: "none",
                borderTop: "1px solid #2a2a2a",
                "& .MuiList-root": { py: 0 },
                boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
                transformOrigin: "top left",
                overflow: "visible",
                animation: "rollDown 0.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
                "@keyframes rollDown": {
                  from: { transform: "scaleY(0)", opacity: 0 },
                  to: { transform: "scaleY(1)", opacity: 1 },
                },
              },
            }}
            transformOrigin={{ horizontal: "left", vertical: "top" }}
            anchorOrigin={{ horizontal: "left", vertical: "bottom" }}
          >
            {dropdownLinks.map((item, idx) => {
              if (item.category) {
                return (
                  <MenuItem
                    key={item.category}
                    sx={{
                      fontSize: "0.78rem",
                      fontFamily: "'Inter', sans-serif",
                      fontWeight: 400,
                      color: "rgba(255,255,255,0.65)",
                      letterSpacing: 0.8,
                      textTransform: "uppercase",
                      backgroundColor: "transparent",
                      px: 2,
                      py: 1.25,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      position: "relative",
                      overflow: "visible",
                      borderBottom: idx < dropdownLinks.length - 1 ? "1px solid #1e1e1e" : "none",
                      transition: "all 0.12s ease",
                      "& .sub-menu": { display: "none" },
                      "&:hover": {
                        backgroundColor: "#1c1c1c",
                        color: "#fff",
                        "& .sub-menu": { display: "block" },
                      },
                    }}
                  >
                    {item.category}
                    <ArrowForwardIosIcon sx={{ fontSize: 10, ml: 1, opacity: 0.5 }} />

                    {/* CSS-only Cascading Sub-Menu */}
                    <Box
                      className="sub-menu"
                      sx={{
                        position: "absolute",
                        left: "100%",
                        top: 0,
                        backgroundColor: "#111",
                        border: "1px solid #2a2a2a",
                        minWidth: 160,
                        zIndex: 1000,
                        boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
                        pointerEvents: "auto",
                      }}
                    >
                      {item.items.map((subItem, sIdx) => (
                        <Box
                          key={subItem.path}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleNavigate(subItem.path);
                          }}
                          sx={{
                            fontSize: "0.78rem",
                            fontFamily: "'Inter', sans-serif",
                            fontWeight: 400,
                            color: "rgba(255,255,255,0.65)",
                            letterSpacing: 0.8,
                            textTransform: "uppercase",
                            backgroundColor: "transparent",
                            px: 2,
                            py: 1.5,
                            borderBottom: sIdx < item.items.length - 1 ? "1px solid #1e1e1e" : "none",
                            transition: "all 0.12s ease",
                            "&:hover": {
                              backgroundColor: "#1c1c1c",
                              color: "#fff",
                            },
                          }}
                        >
                          {subItem.label}
                        </Box>
                      ))}
                    </Box>
                  </MenuItem>
                );
              }
              return (
                <MenuItem
                  key={item.path}
                  onClick={() => handleNavigate(item.path)}
                  sx={{
                    fontSize: "0.78rem",
                    fontFamily: "'Inter', sans-serif",
                    fontWeight: 400,
                    color: "rgba(255,255,255,0.65)",
                    letterSpacing: 0.8,
                    textTransform: "uppercase",
                    backgroundColor: "transparent",
                    px: 2,
                    py: 1.25,
                    borderBottom: idx < dropdownLinks.length - 1 ? "1px solid #1e1e1e" : "none",
                    transition: "all 0.12s ease",
                    "&:hover": {
                      backgroundColor: "#1c1c1c",
                      color: "#fff",
                    },
                  }}
                >
                  {item.label}
                </MenuItem>
              );
            })}
          </Menu>
        </Box>

        {/* Right: Actions */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 3 }}>
          {user.username && (
            <Tooltip
              title={
                <Box sx={{ p: 1.5, minWidth: 220 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 800, color: "#fff", mb: 0.5 }}>
                    User Profile
                  </Typography>
                  <Divider sx={{ bgcolor: "rgba(255,255,255,0.15)", my: 1 }} />
                  <Stack gap={1.5}>
                    <Box>
                      <Typography sx={{ fontSize: "0.65rem", fontWeight: 700, color: "rgba(255,255,255,0.5)", textTransform: "uppercase", mb: 0.25 }}>
                        Email Address
                      </Typography>
                      <Typography sx={{ fontSize: "0.85rem", color: "#fff" }}>{user.emailid}</Typography>
                    </Box>
                    <Box>
                      <Typography sx={{ fontSize: "0.65rem", fontWeight: 700, color: "rgba(255,255,255,0.5)", textTransform: "uppercase", mb: 0.25 }}>
                        Designation
                      </Typography>
                      <Typography sx={{ fontSize: "0.85rem", color: "#fff" }}>{user.role}</Typography>
                    </Box>
                    <Box>
                      <Typography sx={{ fontSize: "0.65rem", fontWeight: 700, color: "rgba(255,255,255,0.5)", textTransform: "uppercase", mb: 0.5 }}>
                        Expertise
                      </Typography>
                      <Stack direction="row" flexWrap="wrap" gap={0.75}>
                        {user.expertise?.map((exp) => (
                          <Chip
                            key={exp}
                            label={exp}
                            size="small"
                            sx={{
                              height: 20,
                              fontSize: "0.7rem",
                              fontWeight: 600,
                              bgcolor: "rgba(255,255,255,0.1)",
                              color: "#fff",
                              borderRadius: "4px",
                              border: "1px solid rgba(255,255,255,0.1)",
                              "& .MuiChip-label": { px: 1 },
                            }}
                          />
                        ))}
                      </Stack>
                    </Box>
                  </Stack>
                </Box>
              }
              slotProps={{
                tooltip: {
                  sx: {
                    bgcolor: "#0a0a0a",
                    color: "#fff",
                    border: "1px solid #333",
                    boxShadow: "0 12px 40px rgba(0,0,0,0.9)",
                    borderRadius: 2,
                    p: 0,
                  }
                },
                arrow: {
                  sx: { color: "#0a0a0a" }
                }
              }}
              arrow
            >
              <Box sx={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 1, px: 1, py: 0.5, borderRadius: 1, transition: "background-color 0.2s", "&:hover": { bgcolor: "rgba(255,255,255,0.05)" } }}>
                <AccountCircleIcon sx={{ fontSize: 22, color: "rgba(255,255,255,0.8)" }} />
                <Typography sx={{ fontSize: "0.85rem", fontWeight: 700, color: "#fff", fontFamily: "'Inter', sans-serif" }}>
                  {user.username}
                </Typography>
              </Box>
            </Tooltip>
          )}

          <UploadJSON />

          <Typography
            onClick={logout}
            sx={{
              fontFamily: "'Inter', sans-serif",
              fontWeight: 700,
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: 0.5,
              color: "#fff",
              backgroundColor: "rgba(255,255,255,0.1)",
              border: "1px solid rgba(255,255,255,0.2)",
              px: 2,
              py: 0.6,
              borderRadius: "4px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 1,
              transition: "all 0.2s",
              "&:hover": {
                backgroundColor: "rgba(255,255,255,0.15)",
                borderColor: "rgba(255,255,255,0.3)",
              },
            }}
          >
            <LogoutIcon sx={{ fontSize: 16 }} />
            Logout
          </Typography>
        </Box>
      </Toolbar>
    </AppBar>
  );
};

export default Navbar;
