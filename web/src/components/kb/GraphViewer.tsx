'use client'

import * as React from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { useUserStore } from '@/stores'
import { apiFetch } from '@/lib/api'
import { toast } from 'sonner'
import dynamic from 'next/dynamic'

const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

interface GraphNode {
  id: string
  title: string
  description?: string | null
  path: string
  file_type: string
  source_kind: 'wiki' | 'source' | 'asset'
  tags?: string[]
  x?: number
  y?: number
}

interface GraphEdge {
  source: string
  target: string
  type: 'cites' | 'links_to'
  page?: number
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

interface Props {
  kbId: string
  focusNodeId?: string | null
  onNavigateToDoc?: (docId: string, sourceKind: string) => void
}

const NODE_COLOR_CONCEPT = 'rgba(130, 130, 210, 0.85)'   // concepts — blue-violet
const NODE_COLOR_ENTITY = 'rgba(200, 130, 100, 0.85)'    // entities — warm terracotta
const NODE_COLOR_WIKI = 'rgba(140, 140, 170, 0.7)'       // other wiki pages (overview, log)
const NODE_COLOR_SOURCE = 'rgba(100, 170, 120, 0.7)'     // source documents
const NODE_COLOR_HOVER = 'rgba(230, 180, 60, 1)'
const EDGE_COLOR_LINKS = 'rgba(130, 130, 190, 0.25)'
const EDGE_COLOR_CITES = 'rgba(100, 170, 120, 0.18)'

function getNodeColor(node: { source_kind: string; path: string }) {
  if (node.source_kind !== 'wiki') return NODE_COLOR_SOURCE
  const p = node.path.toLowerCase()
  if (p.includes('/concepts/') || p.includes('concepts/')) return NODE_COLOR_CONCEPT
  if (p.includes('/entities/') || p.includes('entities/')) return NODE_COLOR_ENTITY
  return NODE_COLOR_WIKI
}

export function GraphViewer({ kbId, focusNodeId, onNavigateToDoc }: Props) {
  const token = useUserStore((s) => s.accessToken)
  const containerRef = React.useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = React.useRef<any>(null)
  const [graphData, setGraphData] = React.useState<GraphData | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [rebuilding, setRebuilding] = React.useState(false)
  const [error, setError] = React.useState(false)
  const hoverNodeRef = React.useRef<GraphNode | null>(null)
  const hoverNeighborsRef = React.useRef<Set<string> | null>(null)
  const [hoverNodeState, setHoverNodeState] = React.useState<GraphNode | null>(null)
  const [mousePos, setMousePos] = React.useState({ x: 0, y: 0 })
  const [dimensions, setDimensions] = React.useState({ width: 0, height: 0 })
  const [showSources, setShowSources] = React.useState(false)

  const fetchGraph = React.useCallback(() => {
    if (!token) return
    setLoading(true)
    setError(false)
    apiFetch<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
      `/v1/knowledge-bases/${kbId}/graph`,
      token,
    )
      .then(setGraphData)
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [kbId, token])

  React.useEffect(() => { fetchGraph() }, [fetchGraph])

  // Always track container size — ref is always mounted
  React.useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          setDimensions({ width, height })
        }
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const handleRebuild = React.useCallback(async () => {
    if (!token || rebuilding) return
    setRebuilding(true)
    try {
      const res = await apiFetch<{ citations: number; links: number }>(
        `/v1/knowledge-bases/${kbId}/graph/rebuild`,
        token,
        { method: 'POST' },
      )
      const total = res.citations + res.links
      if (total === 0) {
        toast.info('No citations or cross-references found')
      } else {
        toast.success(`${res.citations} citation${res.citations !== 1 ? 's' : ''}, ${res.links} cross-reference${res.links !== 1 ? 's' : ''}`)
      }
      fetchGraph()
    } catch {
      toast.error('Failed to rebuild references')
    } finally {
      setRebuilding(false)
    }
  }, [kbId, token, rebuilding, fetchGraph])

  // Connection counts for tooltip
  const connectionCounts = React.useMemo(() => {
    if (!graphData) return new Map<string, { outbound: number; inbound: number }>()
    const counts = new Map<string, { outbound: number; inbound: number }>()
    for (const n of graphData.nodes) counts.set(n.id, { outbound: 0, inbound: 0 })
    for (const e of graphData.edges) {
      const s = counts.get(e.source)
      const t = counts.get(e.target)
      if (s) s.outbound++
      if (t) t.inbound++
    }
    return counts
  }, [graphData])

  const forceGraphData = React.useMemo(() => {
    if (!graphData) return { nodes: [], links: [] }

    let relevantNodes = graphData.nodes
    let relevantEdges = graphData.edges

    // Local graph mode: show only the focus node's neighborhood
    if (focusNodeId) {
      const neighborIds = new Set<string>([focusNodeId])
      for (const e of graphData.edges) {
        if (e.source === focusNodeId) neighborIds.add(e.target)
        if (e.target === focusNodeId) neighborIds.add(e.source)
      }
      relevantNodes = graphData.nodes.filter((n) => neighborIds.has(n.id))
      relevantEdges = graphData.edges.filter(
        (e) => neighborIds.has(e.source) && neighborIds.has(e.target),
      )
    } else {
      // Global mode: optionally hide sources
      if (!showSources) {
        relevantNodes = relevantNodes.filter((n) => n.source_kind === 'wiki')
        relevantEdges = relevantEdges.filter((e) => e.type === 'links_to')
      }
    }

    const nodeIds = new Set(relevantNodes.map((n) => n.id))

    return {
      nodes: relevantNodes.map((n) => ({ ...n })),
      links: relevantEdges
        .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e) => ({ source: e.source, target: e.target, type: e.type })),
    }
  }, [graphData, showSources, focusNodeId])

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleNodeClick = React.useCallback(
    (node: any) => { onNavigateToDoc?.(node.id, node.source_kind) },
    [onNavigateToDoc],
  )

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodeCanvasObject = React.useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const hovering = hoverNodeRef.current
      const isHover = hovering?.id === node.id
      const neighbors = hoverNeighborsRef.current
      const isFaded = hovering && neighbors && !neighbors.has(node.id)

      const isWiki = node.source_kind === 'wiki'
      const radius = isWiki ? 5 : 3.5
      const color = isHover ? NODE_COLOR_HOVER : getNodeColor(node)

      ctx.globalAlpha = isFaded ? 0.12 : 1
      ctx.beginPath()
      ctx.arc(node.x!, node.y!, radius, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()

      if (globalScale > 1.2 || isHover) {
        const label = node.title
        const fontSize = Math.max(10 / globalScale, 2)
        ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = isHover ? '#fff' : 'rgba(180,180,190,0.85)'
        ctx.fillText(label, node.x!, node.y! + radius + 2)
      }
      ctx.globalAlpha = 1
    },
    // hoverNodeState triggers a new function ref so ForceGraph repaints on hover change
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hoverNodeState],
  )

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleNodeHover = React.useCallback((node: any) => {
    hoverNodeRef.current = node
    if (node && forceGraphData.links.length > 0) {
      const neighbors = new Set<string>([node.id])
      for (const link of forceGraphData.links) {
        // D3 mutates link.source/target from string IDs to node objects at runtime
        const src = link.source as string | { id: string }
        const tgt = link.target as string | { id: string }
        const srcId = typeof src === 'object' ? src.id : src
        const tgtId = typeof tgt === 'object' ? tgt.id : tgt
        if (srcId === node.id) neighbors.add(tgtId)
        if (tgtId === node.id) neighbors.add(srcId)
      }
      hoverNeighborsRef.current = neighbors
    } else {
      hoverNeighborsRef.current = null
    }
    setHoverNodeState(node)
  }, [forceGraphData.links])

  const handleMouseMove = React.useCallback((e: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (rect) setMousePos({ x: e.clientX - rect.left, y: e.clientY - rect.top })
  }, [])

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const linkColor = React.useCallback(
    (link: any) => {
      const hovering = hoverNodeRef.current
      if (hovering) {
        const src = link.source as string | { id: string }
        const tgt = link.target as string | { id: string }
        const srcId = typeof src === 'object' ? src.id : src
        const tgtId = typeof tgt === 'object' ? tgt.id : tgt
        const connected = srcId === hovering.id || tgtId === hovering.id
        if (!connected) return 'rgba(200,200,200,0.04)'
        return link.type === 'links_to' ? 'rgba(130,130,190,0.6)' : 'rgba(100,170,120,0.5)'
      }
      return link.type === 'links_to' ? EDGE_COLOR_LINKS : EDGE_COLOR_CITES
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hoverNodeState],
  )

  // Configure forces for better spacing
  React.useEffect(() => {
    const fg = graphRef.current
    if (!fg) return
    fg.d3Force('charge')?.strength(-200)
    fg.d3Force('link')?.distance(60)
    fg.d3ReheatSimulation()
  }, [forceGraphData])

  const hasEdges = forceGraphData.links.length > 0
  const hasNodes = forceGraphData.nodes.length > 0
  const ready = !loading && !error && graphData && hasNodes && hasEdges && dimensions.width > 0

  // Determine overlay content for non-graph states
  let overlay: React.ReactNode = null
  if (loading) {
    overlay = <Loader2 className="size-5 animate-spin text-muted-foreground" />
  } else if (error || !graphData) {
    overlay = <p className="text-sm text-muted-foreground">Failed to load graph data</p>
  } else if (!hasNodes) {
    overlay = <p className="text-sm text-muted-foreground">No documents to visualize yet</p>
  } else if (!hasEdges) {
    overlay = (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm text-muted-foreground text-center max-w-xs">
          {graphData.nodes.length} document{graphData.nodes.length !== 1 ? 's' : ''} found, but no
          references have been indexed yet.
        </p>
        <button
          onClick={handleRebuild}
          disabled={rebuilding}
          className="inline-flex items-center gap-2 rounded-full border border-border px-4 py-1.5 text-xs font-medium hover:bg-accent transition-colors cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`size-3 ${rebuilding ? 'animate-spin' : ''}`} />
          {rebuilding ? 'Building...' : 'Build references'}
        </button>
        <p className="text-[11px] text-muted-foreground/50 text-center max-w-xs">
          Parses wiki pages for citations and cross-references
        </p>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="h-full w-full bg-background relative" onMouseMove={handleMouseMove}>
      {overlay ? (
        <div className="absolute inset-0 flex items-center justify-center">{overlay}</div>
      ) : ready ? (
        <>
          <ForceGraph2D
            ref={graphRef}
            width={dimensions.width}
            height={dimensions.height}
            graphData={forceGraphData}
            nodeId="id"
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
              ctx.beginPath()
              ctx.arc(node.x!, node.y!, 8, 0, 2 * Math.PI)
              ctx.fillStyle = color
              ctx.fill()
            }}
            onNodeHover={handleNodeHover}
            onNodeClick={handleNodeClick}
            linkColor={linkColor}
            linkWidth={0.5}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            backgroundColor="transparent"
            cooldownTicks={100}
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
          />

          {/* Controls */}
          <div className="absolute top-3 right-3 flex items-center gap-3 text-[10px] text-muted-foreground bg-background/80 backdrop-blur-sm px-3 py-1.5 rounded-md border border-border">
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-full" style={{ backgroundColor: NODE_COLOR_CONCEPT }} />
              Concept
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-full" style={{ backgroundColor: NODE_COLOR_ENTITY }} />
              Entity
            </span>
            <button
              onClick={() => setShowSources((s) => !s)}
              className={`flex items-center gap-1.5 cursor-pointer transition-colors ${showSources ? 'text-foreground' : 'text-muted-foreground/40 hover:text-muted-foreground'}`}
              title={showSources ? 'Hide sources' : 'Show sources'}
            >
              <span className="inline-block size-2 rounded-full" style={{ backgroundColor: NODE_COLOR_SOURCE, opacity: showSources ? 1 : 0.3 }} />
              Sources
            </button>
            <span className="text-muted-foreground/30">|</span>
            <button
              onClick={handleRebuild}
              disabled={rebuilding}
              className="flex items-center gap-1 hover:text-foreground transition-colors cursor-pointer disabled:opacity-50"
              title="Rebuild references"
            >
              <RefreshCw className={`size-2.5 ${rebuilding ? 'animate-spin' : ''}`} />
              {rebuilding ? 'Building...' : 'Rebuild'}
            </button>
          </div>

          {/* Hover tooltip — follows cursor */}
          {hoverNodeState && (() => {
            const p = hoverNodeState.path.toLowerCase()
            const category = hoverNodeState.source_kind !== 'wiki'
              ? 'Source'
              : p.includes('concepts/') ? 'Concept'
              : p.includes('entities/') ? 'Entity'
              : 'Page'
            return (
              <div
                className="absolute text-xs bg-background/95 backdrop-blur-sm border border-border rounded-md px-3 py-2 pointer-events-none max-w-72 z-10"
                style={{ left: mousePos.x + 14, top: mousePos.y - 10 }}
              >
                <p className="font-medium">{hoverNodeState.title}</p>
                {hoverNodeState.description && (
                  <p className="text-muted-foreground mt-0.5 line-clamp-2">{hoverNodeState.description}</p>
                )}
                <p className="text-muted-foreground/50 mt-0.5">{category}</p>
                {hoverNodeState.tags && hoverNodeState.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {hoverNodeState.tags.slice(0, 4).map((tag) => (
                      <span key={tag} className="text-[9px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground/50">{tag}</span>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}
        </>
      ) : null}
    </div>
  )
}
