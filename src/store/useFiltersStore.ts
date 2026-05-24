import { create } from 'zustand'
import type { GlobalFilters } from '@/api/types'

interface FiltersState {
  filters: GlobalFilters
  setFilter: <K extends keyof GlobalFilters>(key: K, value: GlobalFilters[K]) => void
  resetFilters: () => void
}

const initialFilters: GlobalFilters = {
  period: undefined,
  genre: undefined,
  playId: undefined,
  roleType: undefined,
  characterId: undefined,
  theme: undefined,
  narrativePattern: undefined,
}

export const useFiltersStore = create<FiltersState>((set) => ({
  filters: initialFilters,
  setFilter: (key, value) =>
    set((state) => ({
      filters: {
        ...state.filters,
        [key]: value || undefined,
        ...(key === 'playId' ? { characterId: undefined } : {}),
      },
    })),
  resetFilters: () => set({ filters: initialFilters }),
}))
