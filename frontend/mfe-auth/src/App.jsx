import React from 'react'
import { Routes, Route } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import { PageNotFound, GuestRoute } from '@data-hygiene/ui'

const App = () => {
  return (
    <Routes>
      <Route element={<GuestRoute />}>
        <Route path="/login" element={<LoginPage />} />
        {/* For Auth MFE, the root also shows login, but it should be protected */}
        <Route path="/" element={<LoginPage />} />
      </Route>
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  )
}

export default App
