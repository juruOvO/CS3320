export interface GlobalFilters {
  period?: string
  genre?: string
  playId?: string
  roleType?: string
  characterId?: string
  theme?: string
  narrativePattern?: string
}

export interface FilterOptionsResponse {
  periods: string[]
  genres: string[]
  plays: Array<{ id: string; title: string }>
  roleTypes: string[]
  themes: string[]
  narrativePatterns: string[]
}

export interface PlayRecord {
  id: string
  title: string
  period: string
  genre: string
  authorEra: string
  sceneCount: number
  narrativePattern: string
  summary: string
}

export interface CharacterRecord {
  id: string
  playId: string
  name: string
  gender: string
  ageGroup: string
  identity: string
  personalityTags: string[]
  roleMain: string
  roleSubtype: string
  confidence: number
  actionScore: number
  emotionScore: number
  appearanceCount: number
  evidence: string[]
}

export interface RelationRecord {
  playId: string
  source: string
  target: string
  relationType: string
  weight: number
  scenes: string[]
}

export interface ThemeRecord {
  playId: string
  theme: string
  weight: number
  evidenceSegments: string[]
}

export interface NarrativeSegmentRecord {
  playId: string
  scene: string
  stage: string
  tension: number
  action: number
  emotion: number
  performanceForm: string
  label: string
  description: string
}

export interface OverviewResponse {
  summary: {
    playCount: number
    characterCount: number
    inferredRoleCount: number
    themeCount: number
    relationCount: number
    avgSceneCount: number
  }
  periodGenreDistribution: Array<{ period: string; genre: string; value: number }>
  roleDistribution: Array<{ roleType: string; value: number }>
  topThemes: Array<{ theme: string; value: number }>
  narrativePatterns: Array<{ pattern: string; value: number }>
  apiGuide: Array<{ endpoint: string; description: string }>
  playList: Array<{ id: string; title: string; period: string; genre: string; sceneCount: number }>
}

export interface CharacterRoleResponse {
  sankeyNodes: Array<{ name: string; category: string }>
  sankeyLinks: Array<{ source: string; target: string; value: number }>
  heatmap: Array<{ period: string; roleType: string; feature: string; value: number }>
  timeline: Array<{ period: string; roleType: string; value: number }>
  characters: CharacterRecord[]
}

export interface RelationNetworkResponse {
  nodes: Array<{ id: string; name: string; playId: string; roleType: string; size: number; centrality: number }>
  links: Array<{ source: string; target: string; relationType: string; weight: number; scenes: string[] }>
  adjacency: Array<{ source: string; target: string; value: number }>
  metrics: Array<{ genre: string; density: number; avgDegree: number; clustering: number; centralization: number; modularity: number }>
  relationTrend: Array<{ scene: string; relationType: string; value: number }>
}

export interface ThemeResponse {
  sunburst: {
    name: string
    children: Array<{ name: string; children: Array<{ name: string; value: number }> }>
  }
  cooccurrenceNodes: Array<{ id: string; value: number }>
  cooccurrenceLinks: Array<{ source: string; target: string; value: number }>
  genreDistribution: Array<{ genre: string; theme: string; value: number }>
  combinations: Array<{ combination: string[]; value: number }>
  playProfiles: Array<{ playId: string; title: string; topThemes: string[] }>
}

export interface NarrativeResponse {
  stages: Array<{ stage: string; order: number; description: string }>
  tensionSeries: Array<{ playId: string; scene: string; tension: number; action: number; emotion: number }>
  performanceDistribution: Array<{ stage: string; form: string; value: number }>
  patternClusters: Array<{ playId: string; title: string; genre: string; x: number; y: number; pattern: string }>
  turningPoints: Array<{ playId: string; scene: string; label: string; description: string }>
}

export interface AssociationResponse {
  sankeyNodes: Array<{ name: string; category: string }>
  sankeyLinks: Array<{ source: string; target: string; value: number }>
  matrix: Array<{ relationFeature: string; targetFeature: string; value: number }>
  clusters: Array<{ playId: string; title: string; genre: string; x: number; y: number; pattern: string }>
  rules: Array<{ id: string; title: string; support: number; confidence: number; description: string; samples: string[] }>
}

export interface PlayDetailResponse {
  play: PlayRecord
  characters: Array<{ id: string; name: string; roleSubtype: string; identity: string; relationHint: string }>
  themes: Array<{ theme: string; weight: number }>
  narrative: Array<{ scene: string; tension: number }>
  evidence: Array<{ id: string; type: string; speaker?: string; text: string }>
}
