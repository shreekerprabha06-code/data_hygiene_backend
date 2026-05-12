import React, { Suspense, lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import RecordsListPage from './pages/RecordsListPage'
import { Loader, ProtectedRoute, PageNotFound, GuestRoute } from '@data-hygiene/ui'

const DetailsPage = lazy(() => import('details/DetailsPage'));
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
          <Route path="/" element={<RecordsListPage key="landing" mode="landing" />} />
          <Route path="/active" element={<RecordsListPage key="active" mode="active" />} />
          <Route path="/completed" element={<RecordsListPage key="completed" mode="completed" />} />
          <Route path="/on-hold" element={<RecordsListPage key="onhold" mode="onhold" />} />
          <Route path="/all" element={<RecordsListPage key="all" mode="all" />} />
          <Route path="/details/:id" element={<DetailsPage />} />
        </Route>
        
        {/* Standalone 404 */}
        <Route path="*" element={<PageNotFound />} />
      </Routes>
    </Suspense>
  )
}

export default App