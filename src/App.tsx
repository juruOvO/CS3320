import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import DashboardPage from '@/pages/DashboardPage'
import PlayDetailPage from '@/pages/PlayDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/roles" element={<Navigate to="/" replace />} />
          <Route path="/relations" element={<Navigate to="/" replace />} />
          <Route path="/themes" element={<Navigate to="/" replace />} />
          <Route path="/narratives" element={<Navigate to="/" replace />} />
          <Route path="/associations" element={<Navigate to="/" replace />} />
          <Route path="/plays/:playId" element={<PlayDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
