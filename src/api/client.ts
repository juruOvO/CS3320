import axios from 'axios'
import type {
  AssociationResponse,
  CharacterRoleResponse,
  FilterOptionsResponse,
  GlobalFilters,
  NarrativeResponse,
  OverviewResponse,
  RelationNetworkResponse,
  ThemeResponse,
} from './types'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
type MockService = typeof import('./mockService')
let mockServicePromise: Promise<MockService> | null = null

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 8000,
})

function getMockService() {
  mockServicePromise ??= import('./mockService')
  return mockServicePromise
}

async function getRemote<T>(path: string, params?: Record<string, string | undefined> | GlobalFilters) {
  const response = await http.get<T>(path, { params })
  return response.data
}

export const apiClient = {
  getFilterOptions: (filters: GlobalFilters = {}): Promise<FilterOptionsResponse> =>
    useMock ? getMockService().then((mock) => mock.getFilterOptions(filters)) : getRemote('/filter-options', filters),

  getOverview: (filters: GlobalFilters): Promise<OverviewResponse> =>
    useMock ? getMockService().then((mock) => mock.getOverview(filters)) : getRemote('/overview', filters),

  getCharacterRoles: (filters: GlobalFilters): Promise<CharacterRoleResponse> =>
    useMock ? getMockService().then((mock) => mock.getCharacterRoles(filters)) : getRemote('/character-roles', filters),

  getRelations: (filters: GlobalFilters): Promise<RelationNetworkResponse> =>
    useMock ? getMockService().then((mock) => mock.getRelations(filters)) : getRemote('/relations', filters),

  getThemes: (filters: GlobalFilters): Promise<ThemeResponse> =>
    useMock ? getMockService().then((mock) => mock.getThemes(filters)) : getRemote('/themes', filters),

  getNarratives: (filters: GlobalFilters): Promise<NarrativeResponse> =>
    useMock ? getMockService().then((mock) => mock.getNarratives(filters)) : getRemote('/narratives', filters),

  getAssociations: (filters: GlobalFilters): Promise<AssociationResponse> =>
    useMock ? getMockService().then((mock) => mock.getAssociations(filters)) : getRemote('/associations', filters),
}
