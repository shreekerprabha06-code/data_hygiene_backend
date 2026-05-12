import React, { Suspense,lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Loader, ProtectedRoute, PageNotFound, GuestRoute } from '@data-hygiene/ui'
const DetailsPage = lazy(() => import('./pages/DetailsPage'));
const LoginPage = lazy(() => import('auth/LoginPage'));

const App = () => {
  return (
    <Suspense fallback={<Loader />}>
      <Routes>
        {/* Standalone Login */}
        <Route element={<GuestRoute />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>
        
        <Route element={<ProtectedRoute />}>
          <Route path="/details/:id" element={<DetailsPage />} />
          <Route path="/" element={<div>Please select a record from the dashboard.</div>} />
        </Route>
        
        {/* Standalone 404 */}
        <Route path="*" element={<PageNotFound />} />
      </Routes>
    </Suspense>
  )
}

export default App