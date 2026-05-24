import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import AssociationsPage from '@/pages/AssociationsPage'
import Home from '@/pages/Home'
import NarrativesPage from '@/pages/NarrativesPage'
import PlayDetailPage from '@/pages/PlayDetailPage'
import RelationsPage from '@/pages/RelationsPage'
import RolesPage from '@/pages/RolesPage'
import ThemesPage from '@/pages/ThemesPage'

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/roles" element={<RolesPage />} />
          <Route path="/relations" element={<RelationsPage />} />
          <Route path="/themes" element={<ThemesPage />} />
          <Route path="/narratives" element={<NarrativesPage />} />
          <Route path="/associations" element={<AssociationsPage />} />
          <Route path="/plays/:playId" element={<PlayDetailPage />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  )
}
