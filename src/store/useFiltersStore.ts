import { create } from 'zustand'
import type { GlobalFilters } from '@/api/types'

interface FiltersState {
  filters: GlobalFilters
  setFilter: <K extends keyof GlobalFilters>(key: K, value: GlobalFilters[K]) => void
  setFilters: (updates: Partial<GlobalFilters>) => void
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
  setFilters: (updates) =>
    set((state) => {
      const nextFilters = Object.fromEntries(
        Object.entries({ ...state.filters, ...updates }).map(([key, value]) => [key, value || undefined]),
      ) as GlobalFilters

      if ('playId' in updates && !('characterId' in updates)) {
        nextFilters.characterId = undefined
      }

      return { filters: nextFilters }
    }),
  resetFilters: () => set({ filters: initialFilters }),
}))
