import React from "react";
import { Navigate, Outlet,useLocation } from "react-router-dom";

const GuestRoute = () => {
  const isAuthenticated = !!localStorage.getItem("auth_token");
  const location = useLocation()
  const from = location?.state?.from || "/";

  if (isAuthenticated) {
    // If already logged in, instantly bounce to the home page
    return <Navigate to={from} replace />;
  }

  return <Outlet />;
};

export default GuestRoute;
