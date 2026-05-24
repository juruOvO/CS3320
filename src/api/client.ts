import axios from 'axios'
import {
  getAssociations,
  getCharacterRoles,
  getFilterOptions,
  getNarratives,
  getOverview,
  getPlayDetail,
  getRelations,
  getThemes,
} from './mockService'
import type {
  AssociationResponse,
  CharacterRoleResponse,
  FilterOptionsResponse,
  GlobalFilters,
  NarrativeResponse,
  OverviewResponse,
  PlayDetailResponse,
  RelationNetworkResponse,
  ThemeResponse,
} from './types'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 8000,
})

async function getRemote<T>(path: string, params?: Record<string, string | undefined> | GlobalFilters) {
  const response = await http.get<T>(path, { params })
  return response.data
}

export const apiClient = {
  getFilterOptions: (): Promise<FilterOptionsResponse> =>
    useMock ? getFilterOptions() : getRemote('/filter-options'),

  getOverview: (filters: GlobalFilters): Promise<OverviewResponse> =>
    useMock ? getOverview(filters) : getRemote('/overview', filters),

  getCharacterRoles: (filters: GlobalFilters): Promise<CharacterRoleResponse> =>
    useMock ? getCharacterRoles(filters) : getRemote('/character-roles', filters),

  getRelations: (filters: GlobalFilters): Promise<RelationNetworkResponse> =>
    useMock ? getRelations(filters) : getRemote('/relations', filters),

  getThemes: (filters: GlobalFilters): Promise<ThemeResponse> =>
    useMock ? getThemes(filters) : getRemote('/themes', filters),

  getNarratives: (filters: GlobalFilters): Promise<NarrativeResponse> =>
    useMock ? getNarratives(filters) : getRemote('/narratives', filters),

  getAssociations: (filters: GlobalFilters): Promise<AssociationResponse> =>
    useMock ? getAssociations(filters) : getRemote('/associations', filters),

  getPlayDetail: (playId: string): Promise<PlayDetailResponse> =>
    useMock ? getPlayDetail(playId) : getRemote(`/plays/${playId}`),
}
