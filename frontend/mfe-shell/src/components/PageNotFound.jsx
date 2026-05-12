import React from "react";
import { Box, Typography } from "@mui/material";

const PageNotFound = () => {
    return (
        <Box sx={{
            height: '100vh',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            backgroundColor: '#f4f4f4'
        }}>
            <Typography variant="h1" fontWeight={900} sx={{ color: '#000', mb: 1 }}>404</Typography>
            <Typography variant="h5" fontWeight={600} sx={{ mb: 2 }}>Page Not Found</Typography>
            <Typography color="textSecondary" sx={{ mb: 4 }}>The page you are looking for does not exist.</Typography>
            <Typography
                onClick={() => window.location.href = '/'}
                sx={{
                    cursor: 'pointer',
                    color: '#000',
                    textDecoration: 'underline',
                    fontWeight: 700
                }}
            >
                Go back home
            </Typography>
        </Box>
    );
};  

export default PageNotFound;
