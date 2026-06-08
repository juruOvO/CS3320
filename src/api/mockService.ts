import { characters, narrativeSegments, plays, relations, themeGroups, themes } from './mockData'
import type {
  AssociationResponse,
  CharacterRecord,
  CharacterRoleResponse,
  FilterOptionsResponse,
  GlobalFilters,
  NarrativeResponse,
  OverviewResponse,
  PlayRecord,
  RelationNetworkResponse,
  ThemeResponse,
} from './types'

const stageOrder = ['开端', '铺垫', '冲突升级', '转折', '高潮', '收束']

const wait = (ms = 180) => new Promise((resolve) => setTimeout(resolve, ms))

function includesIfSelected(filterValue: string | undefined, target: string) {
  return !filterValue || filterValue === target
}

function getVisiblePlays(filters: GlobalFilters): PlayRecord[] {
  let visiblePlays = plays.filter(
    (play) =>
      includesIfSelected(filters.period, play.period) &&
      includesIfSelected(filters.genre, play.genre) &&
      includesIfSelected(filters.playId, play.id) &&
      includesIfSelected(filters.narrativePattern, play.narrativePattern),
  )

  if (filters.theme) {
    const themePlayIds = new Set(themes.filter((theme) => theme.theme === filters.theme).map((theme) => theme.playId))
    visiblePlays = visiblePlays.filter((play) => themePlayIds.has(play.id))
  }

  if (filters.roleType || filters.characterId) {
    const characterPlayIds = new Set(
      characters
        .filter(
          (character) =>
            includesIfSelected(filters.roleType, character.roleMain) &&
            includesIfSelected(filters.characterId, character.id),
        )
        .map((character) => character.playId),
    )
    visiblePlays = visiblePlays.filter((play) => characterPlayIds.has(play.id))
  }

  return visiblePlays
}

function getVisibleCharacters(filters: GlobalFilters): CharacterRecord[] {
  const playIds = new Set(getVisiblePlays(filters).map((play) => play.id))
  return characters.filter(
    (character) =>
      playIds.has(character.playId) &&
      includesIfSelected(filters.roleType, character.roleMain) &&
      includesIfSelected(filters.characterId, character.id),
  )
}

function getVisibleThemes(filters: GlobalFilters) {
  const playIds = new Set(getVisiblePlays(filters).map((play) => play.id))
  return themes.filter(
    (theme) => playIds.has(theme.playId) && includesIfSelected(filters.theme, theme.theme),
  )
}

function countBy<T>(items: T[], getKey: (item: T) => string) {
  const map = new Map<string, number>()
  items.forEach((item) => {
    const key = getKey(item)
    map.set(key, (map.get(key) ?? 0) + 1)
  })
  return map
}

function getPerformanceCue(character: CharacterRecord) {
  const evidenceText = character.evidence.join(' ')
  const hasSingingCue = /西皮|二黄|慢板|原板|流水|摇板|散板|唱|板/.test(evidenceText)
  const hasSpeechCue = /【[^】]*·白】|念|白/.test(evidenceText)

  if (character.actionScore >= 0.35) return '做打线索强'
  if (hasSingingCue || hasSpeechCue) return '唱念线索强'
  if (character.emotionScore >= 0.22) return '情感推动强'
  if (character.appearanceCount >= 8) return '出场高频'
  return '辅助角色'
}

function unique<T>(items: T[]) {
  return Array.from(new Set(items))
}

export async function getFilterOptions(filters: GlobalFilters = {}): Promise<FilterOptionsResponse> {
  await wait()
  const periodPlays = getVisiblePlays({ ...filters, period: undefined })
  const genrePlays = getVisiblePlays({ ...filters, genre: undefined })
  const playOptions = getVisiblePlays({ ...filters, playId: undefined })
  const rolePlayIds = new Set(getVisiblePlays({ ...filters, roleType: undefined, characterId: undefined }).map((play) => play.id))
  const themePlayIds = new Set(getVisiblePlays({ ...filters, theme: undefined }).map((play) => play.id))
  const patternPlays = getVisiblePlays({ ...filters, narrativePattern: undefined })

  return {
    periods: unique(periodPlays.map((play) => play.period)),
    genres: unique(genrePlays.map((play) => play.genre)),
    plays: playOptions.map((play) => ({ id: play.id, title: play.title })),
    roleTypes: unique(characters.filter((character) => rolePlayIds.has(character.playId)).map((character) => character.roleMain)),
    themes: unique(themes.filter((theme) => themePlayIds.has(theme.playId)).map((theme) => theme.theme)),
    narrativePatterns: unique(patternPlays.map((play) => play.narrativePattern)),
  }
}

export async function getOverview(filters: GlobalFilters): Promise<OverviewResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const visibleCharacters = getVisibleCharacters(filters)
  const visibleThemes = getVisibleThemes(filters)
  const playIds = new Set(visiblePlays.map((play) => play.id))
  const visibleRelations = relations.filter((relation) => playIds.has(relation.playId))

  const periodGenreDistribution = visiblePlays.map((play) => ({
    period: play.period,
    genre: play.genre,
    value: 1,
  }))

  const roleDistribution = Array.from(
    countBy(visibleCharacters, (character) => character.roleSubtype).entries(),
  ).map(([roleType, value]) => ({ roleType, value }))

  const topThemes = Array.from(
    visibleThemes.reduce((map, item) => {
      map.set(item.theme, (map.get(item.theme) ?? 0) + item.weight)
      return map
    }, new Map<string, number>()),
  )
    .map(([theme, value]) => ({ theme, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8)

  const narrativePatterns = Array.from(
    countBy(visiblePlays, (play) => play.narrativePattern).entries(),
  ).map(([pattern, value]) => ({ pattern, value }))

  return {
    summary: {
      playCount: visiblePlays.length,
      characterCount: visibleCharacters.length,
      inferredRoleCount: visibleCharacters.filter((character) => character.confidence < 0.9).length,
      themeCount: unique(visibleThemes.map((theme) => theme.theme)).length,
      relationCount: visibleRelations.length,
      avgSceneCount:
        visiblePlays.length > 0
          ? Number(
              (
                visiblePlays.reduce((sum, play) => sum + play.sceneCount, 0) / visiblePlays.length
              ).toFixed(1),
            )
          : 0,
    },
    periodGenreDistribution,
    roleDistribution,
    topThemes,
    narrativePatterns,
    apiGuide: [
      { endpoint: 'GET /api/overview', description: '总览统计与全局分布' },
      { endpoint: 'GET /api/character-roles', description: '角色特征与行当推断结果' },
      { endpoint: 'GET /api/relations', description: '关系网络结构与关系演化' },
      { endpoint: 'GET /api/themes', description: '主题构成、共现与组合模式' },
      { endpoint: 'GET /api/narratives', description: '叙事阶段与张力变化' },
      { endpoint: 'GET /api/associations', description: '关系-主题-叙事综合关联' },
    ],
    playList: visiblePlays.map((play) => ({
      id: play.id,
      title: play.title,
      period: play.period,
      genre: play.genre,
      sceneCount: play.sceneCount,
    })),
  }
}

export async function getCharacterRoles(filters: GlobalFilters): Promise<CharacterRoleResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const visibleCharacters = getVisibleCharacters(filters)
  const playMap = new Map(visiblePlays.map((play) => [play.id, play]))

  const nodes = new Map<string, { name: string; category: string }>()
  const links = new Map<string, { source: string; target: string; value: number }>()

  visibleCharacters.forEach((character) => {
    const play = playMap.get(character.playId)
    const period = play?.period ?? '未知时期'
    const cue = getPerformanceCue(character)
    const role = character.roleMain || character.roleSubtype || '未识别行当'

    nodes.set(period, { name: period, category: '时期' })
    nodes.set(cue, { name: cue, category: '表演线索' })
    nodes.set(role, { name: role, category: '行当' })

    const periodCueKey = `${period}-${cue}`
    const cueRoleKey = `${cue}-${role}`
    links.set(periodCueKey, {
      source: period,
      target: cue,
      value: (links.get(periodCueKey)?.value ?? 0) + 1,
    })
    links.set(cueRoleKey, {
      source: cue,
      target: role,
      value: (links.get(cueRoleKey)?.value ?? 0) + 1,
    })
  })

  const heatmap = visibleCharacters.flatMap((character) => {
    const play = playMap.get(character.playId)
    const feature = `${character.gender}/${character.ageGroup}`
    return [
      {
        period: play?.period ?? '未知',
        roleType: character.roleSubtype,
        feature,
        value: 1,
      },
    ]
  })

  const timeline = Array.from(
    visibleCharacters.reduce((map, character) => {
      const play = playMap.get(character.playId)
      const key = `${play?.period ?? '未知'}-${character.roleMain}`
      map.set(key, (map.get(key) ?? 0) + 1)
      return map
    }, new Map<string, number>()),
  ).map(([key, value]) => {
    const [period, roleType] = key.split('-')
    return { period, roleType, value }
  })

  return {
    sankeyNodes: Array.from(nodes.values()),
    sankeyLinks: Array.from(links.values()),
    heatmap,
    timeline,
    characters: visibleCharacters,
  }
}

export async function getRelations(filters: GlobalFilters): Promise<RelationNetworkResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const playIds = new Set(visiblePlays.map((play) => play.id))
  const baseCharacters = characters.filter(
    (character) => playIds.has(character.playId) && includesIfSelected(filters.roleType, character.roleMain),
  )
  const baseCharacterMap = new Map(baseCharacters.map((character) => [character.id, character]))
  let visibleRelations = relations.filter(
    (relation) => playIds.has(relation.playId) && baseCharacterMap.has(relation.source) && baseCharacterMap.has(relation.target),
  )

  if (filters.characterId) {
    visibleRelations = visibleRelations.filter(
      (relation) => relation.source === filters.characterId || relation.target === filters.characterId,
    )
  }

  const relatedCharacterIds = filters.characterId
    ? new Set([filters.characterId, ...visibleRelations.flatMap((relation) => [relation.source, relation.target])])
    : null
  const visibleCharacters = baseCharacters.filter(
    (character) => !relatedCharacterIds || relatedCharacterIds.has(character.id),
  )
  const characterMap = new Map(visibleCharacters.map((character) => [character.id, character]))

  const degreeMap = new Map<string, number>()
  visibleRelations.forEach((relation) => {
    degreeMap.set(relation.source, (degreeMap.get(relation.source) ?? 0) + relation.weight)
    degreeMap.set(relation.target, (degreeMap.get(relation.target) ?? 0) + relation.weight)
  })

  const nodes = visibleCharacters.map((character) => ({
    id: character.id,
    name: character.name,
    playId: character.playId,
    roleType: character.roleMain,
    size: 24 + character.appearanceCount * 2,
    centrality: degreeMap.get(character.id) ?? 1,
  }))

  const adjacency = visibleRelations.map((relation) => ({
    source: characterMap.get(relation.source)?.name ?? relation.source,
    target: characterMap.get(relation.target)?.name ?? relation.target,
    value: relation.weight,
  }))

  const genreGroups = unique(visiblePlays.map((play) => play.genre))
  const metrics = genreGroups.map((genre) => {
    const genrePlayIds = new Set(visiblePlays.filter((play) => play.genre === genre).map((play) => play.id))
    const genreNodes = visibleCharacters.filter((character) => genrePlayIds.has(character.playId))
    const genreLinks = visibleRelations.filter((relation) => genrePlayIds.has(relation.playId))
    const nodeCount = Math.max(genreNodes.length, 1)
    const possibleEdges = Math.max((nodeCount * (nodeCount - 1)) / 2, 1)
    const density = Number((genreLinks.length / possibleEdges).toFixed(2))
    const avgDegree = Number(((genreLinks.length * 2) / nodeCount).toFixed(2))
    const centralization = Number(
      (
        Math.max(...genreNodes.map((node) => degreeMap.get(node.id) ?? 0), 1) /
        Math.max(genreLinks.length * 2, 1)
      ).toFixed(2),
    )
    const clustering = Number((Math.min(density * 0.8 + 0.12, 0.92)).toFixed(2))
    const modularity = Number((Math.min(0.25 + density / 2, 0.76)).toFixed(2))
    return { genre, density, avgDegree, clustering, centralization, modularity }
  })

  const relationTrend = visibleRelations.flatMap((relation) =>
    relation.scenes.map((scene) => ({
      scene,
      relationType: relation.relationType,
      value: relation.weight,
    })),
  )

  return {
    nodes,
    links: visibleRelations,
    adjacency,
    metrics,
    relationTrend,
  }
}

export async function getThemes(filters: GlobalFilters): Promise<ThemeResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const visibleThemes = getVisibleThemes(filters)
  const playIds = new Set(visiblePlays.map((play) => play.id))

  const grouped = visibleThemes.reduce((map, item) => {
    const group = themeGroups[item.theme] ?? '其他'
    const groupMap = map.get(group) ?? new Map<string, number>()
    groupMap.set(item.theme, (groupMap.get(item.theme) ?? 0) + item.weight)
    map.set(group, groupMap)
    return map
  }, new Map<string, Map<string, number>>())

  const sunburst = {
    name: '主题结构',
    children: Array.from(grouped.entries()).map(([group, values]) => ({
      name: group,
      children: Array.from(values.entries()).map(([name, value]) => ({ name, value })),
    })),
  }

  const themeCounts = Array.from(
    visibleThemes.reduce((map, item) => {
      map.set(item.theme, (map.get(item.theme) ?? 0) + item.weight)
      return map
    }, new Map<string, number>()),
  )
  const cooccurrenceNodes = themeCounts.map(([id, value]) => ({ id, value }))
  const cooccurrenceLinks = visiblePlays.flatMap((play) => {
    const playThemes = visibleThemes.filter((theme) => theme.playId === play.id).map((theme) => theme.theme)
    return playThemes.flatMap((source, sourceIndex) =>
      playThemes.slice(sourceIndex + 1).map((target) => ({
        source,
        target,
        value: 1,
      })),
    )
  })

  const genreDistribution = visibleThemes.map((theme) => ({
    genre: visiblePlays.find((play) => play.id === theme.playId)?.genre ?? '未知',
    theme: theme.theme,
    value: theme.weight,
  }))

  const combinations = visiblePlays.map((play) => ({
    combination: visibleThemes
      .filter((theme) => theme.playId === play.id)
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 3)
      .map((theme) => theme.theme),
    value: 1,
  }))

  const playProfiles = visiblePlays
    .filter((play) => playIds.has(play.id))
    .map((play) => ({
      playId: play.id,
      title: play.title,
      topThemes: visibleThemes
        .filter((theme) => theme.playId === play.id)
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 3)
        .map((theme) => theme.theme),
    }))

  return {
    sunburst,
    cooccurrenceNodes,
    cooccurrenceLinks,
    genreDistribution,
    combinations,
    playProfiles,
  }
}

export async function getNarratives(filters: GlobalFilters): Promise<NarrativeResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const playIds = new Set(visiblePlays.map((play) => play.id))
  const visibleSegments = narrativeSegments.filter((segment) => playIds.has(segment.playId))

  const stages = stageOrder.map((stage, order) => ({
    stage,
    order,
    description:
      stage === '高潮'
        ? '冲突与情绪最为集中的阶段。'
        : stage === '收束'
          ? '交代后果并重组秩序。'
          : '承接剧情推进与节奏变化。',
  }))

  const performanceDistribution = visibleSegments.map((segment) => ({
    stage: segment.stage,
    form: segment.performanceForm,
    value: 1,
  }))

  const patternClusters = visiblePlays.map((play, index) => ({
    playId: play.id,
    title: play.title,
    genre: play.genre,
    x: 24 + index * 9,
    y:
      play.genre === '历史戏'
        ? 70
        : play.genre === '家庭戏'
          ? 48
          : play.genre === '公案戏'
            ? 62
            : 34,
    pattern: play.narrativePattern,
  }))

  const turningPoints = visibleSegments
    .filter((segment) => segment.stage === '转折' || segment.stage === '高潮')
    .map((segment) => ({
      playId: segment.playId,
      scene: segment.scene,
      label: segment.label,
      description: segment.description,
    }))

  return {
    stages,
    tensionSeries: visibleSegments.map((segment) => ({
      playId: segment.playId,
      scene: segment.scene,
      tension: segment.tension,
      action: segment.action,
      emotion: segment.emotion,
    })),
    performanceDistribution,
    patternClusters,
    turningPoints,
  }
}

export async function getAssociations(filters: GlobalFilters): Promise<AssociationResponse> {
  await wait()
  const visiblePlays = getVisiblePlays(filters)
  const playIds = new Set(visiblePlays.map((play) => play.id))
  const visibleThemes = themes.filter((theme) => playIds.has(theme.playId))

  const relationFeatureMap = new Map<string, string>()
  visiblePlays.forEach((play) => {
    if (play.genre === '历史戏') relationFeatureMap.set(play.id, '中心辐射型关系')
    else if (play.genre === '家庭戏') relationFeatureMap.set(play.id, '家庭团簇型关系')
    else if (play.genre === '公案戏') relationFeatureMap.set(play.id, '审判链型关系')
    else relationFeatureMap.set(play.id, '媒合互动型关系')
  })

  const themeFeatureMap = new Map<string, string>()
  visiblePlays.forEach((play) => {
    const topTheme =
      visibleThemes
        .filter((theme) => theme.playId === play.id)
        .sort((a, b) => b.weight - a.weight)[0]?.theme ?? '其他'
    themeFeatureMap.set(play.id, topTheme)
  })

  const sankeyNodeMap = new Map<string, { name: string; category: string }>()
  const sankeyLinkMap = new Map<string, { source: string; target: string; value: number }>()
  visiblePlays.forEach((play) => {
    const relationFeature = relationFeatureMap.get(play.id) ?? '其他'
    const themeFeature = themeFeatureMap.get(play.id) ?? '其他'
    const narrativeFeature = play.narrativePattern

    const pairs = [
      [relationFeature, themeFeature],
      [themeFeature, narrativeFeature],
    ] as const

    pairs.forEach(([source, target]) => {
      sankeyNodeMap.set(source, { name: source, category: source === relationFeature ? '关系' : '主题' })
      sankeyNodeMap.set(target, { name: target, category: target === narrativeFeature ? '叙事' : '主题' })
      const key = `${source}-${target}`
      sankeyLinkMap.set(key, {
        source,
        target,
        value: (sankeyLinkMap.get(key)?.value ?? 0) + 1,
      })
    })
  })

  const targetFeatures = unique([
    ...visibleThemes.map((theme) => theme.theme),
    ...visiblePlays.map((play) => play.narrativePattern),
  ])
  const matrix = Array.from(relationFeatureMap.entries()).flatMap(([playId, relationFeature]) => {
    const play = visiblePlays.find((item) => item.id === playId)
    const localTargets = [themeFeatureMap.get(playId) ?? '其他', play?.narrativePattern ?? '其他']
    return localTargets.map((targetFeature) => ({
      relationFeature,
      targetFeature,
      value: 1,
    }))
  })

  const clusters = visiblePlays.map((play, index) => ({
    playId: play.id,
    title: play.title,
    genre: play.genre,
    x: 18 + index * 10,
    y: targetFeatures.indexOf(themeFeatureMap.get(play.id) ?? '其他') * 7 + 18,
    pattern: `${relationFeatureMap.get(play.id)} / ${play.narrativePattern}`,
  }))

  const rules = [
    {
      id: 'rule-1',
      title: '中心化关系推动忠义主题',
      support: 0.72,
      confidence: 0.84,
      description: '历史戏中，中心化关系网络常与忠义、牺牲等政治伦理主题共现，并对应单主角推进型叙事。',
      samples: ['赵氏孤儿'],
    },
    {
      id: 'rule-2',
      title: '家庭团簇关系强化伦理回环',
      support: 0.68,
      confidence: 0.81,
      description: '家庭戏中，亲缘密集网络更容易承载家庭伦理、孝义与和解主题，叙事常呈回环或双高潮结构。',
      samples: ['秦香莲', '琵琶记', '打金枝'],
    },
    {
      id: 'rule-3',
      title: '审判链关系对应线性审案结构',
      support: 0.63,
      confidence: 0.78,
      description: '公案戏中，受害者、施害者与裁断者形成链式关系，叙事更倾向线性推进并在公堂或裁决场景达到高潮。',
      samples: ['窦娥冤', '坐楼杀惜'],
    },
  ]

  return {
    sankeyNodes: Array.from(sankeyNodeMap.values()),
    sankeyLinks: Array.from(sankeyLinkMap.values()),
    matrix,
    clusters,
    rules,
  }
}
