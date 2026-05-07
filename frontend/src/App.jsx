import React, { useState, useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import RecordsListPage from './pages/RecordsListPage'
import DetailsPage from './pages/DetailsPage'
import { RefreshProvider } from './context/RefreshContext'
import MasterListPage from './pages/MasterListPage'
import LoginPage from './pages/LoginPage'

const App = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(!!sessionStorage.getItem('jwt_token'));

  useEffect(() => {
    const handleAuthFailure = () => setIsAuthenticated(false);
    window.addEventListener('auth-failed', handleAuthFailure);
    
    // Check on mount in case it was cleared
    if (!sessionStorage.getItem('jwt_token')) {
      setIsAuthenticated(false);
    }
    
    return () => window.removeEventListener('auth-failed', handleAuthFailure);
  }, []);

  if (!isAuthenticated) {
    return <LoginPage onLogin={() => setIsAuthenticated(true)} />;
  }

  return (
    <>
    <RefreshProvider>
      <Routes>
        <Route path="/" element={<RecordsListPage key="landing" mode="landing" />} />
        <Route path="/active" element={<RecordsListPage key="active" mode="active" />} />
        <Route path="/completed" element={<RecordsListPage key="completed" mode="completed" />} />
        <Route path="/on-hold" element={<RecordsListPage key="onhold" mode="onhold" />} />
        <Route path="/all" element={<RecordsListPage key="all" mode="all" />} />
        <Route path="/:id" element={<DetailsPage />} />
        <Route path="/masterlist" element={<MasterListPage />} />
      </Routes>
      </RefreshProvider>
    </>
  )
}

export default App