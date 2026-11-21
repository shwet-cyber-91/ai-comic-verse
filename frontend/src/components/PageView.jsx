import PanelCard from './PanelCard.jsx'

/**
 * One comic page.
 *
 * The backend gives every panel a 1-based cell on a 12-column grid
 * (`col_start`, `col_span`, `row_start`, `row_span`), which maps straight onto
 * CSS grid - so what you see here is geometrically what the PDF compositor
 * produces.
 */
export default function PageView({
  page,
  panels,
  selectedPanelId,
  onSelectPanel,
  showMeta = true,
  className = '',
}) {
  if (!page) return null

  const byId = panels || {}
  const get = (panelId) => (Array.isArray(byId) ? byId.find((p) => p.panel_id === panelId) : byId[panelId])
  const cells = page.cells?.length
    ? page.cells
    : (page.panel_ids || []).map((panelId, index) => ({
        panel_id: panelId,
        col_start: 1 + (index % 2) * 6,
        col_span: 6,
        row_start: Math.floor(index / 2) + 1,
        row_span: 1,
      }))

  return (
    <div className={`mx-auto w-full max-w-3xl ${className}`}>
      <div className="overflow-hidden rounded-lg border-2 border-ink-950 bg-panel p-2 shadow-comic">
        <div
          className="grid gap-2"
          style={{
            gridTemplateColumns: `repeat(${page.cols || 12}, minmax(0, 1fr))`,
            gridTemplateRows: `repeat(${page.rows || 2}, minmax(0, 1fr))`,
            aspectRatio: `${page.width || 1200} / ${page.height || 1800}`,
          }}
        >
          {cells.map((cell) => {
            const panel = get(cell.panel_id)
            return (
              <div
                key={cell.panel_id}
                style={{
                  gridColumn: `${cell.col_start} / span ${cell.col_span}`,
                  gridRow: `${cell.row_start} / span ${cell.row_span}`,
                }}
                className="min-h-0"
              >
                <PanelCard
                  panel={panel}
                  selected={selectedPanelId === cell.panel_id}
                  onSelect={onSelectPanel}
                  showMeta={showMeta}
                  className="h-full w-full"
                />
              </div>
            )
          })}
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>
          {page.page_id} · {page.template} · {cells.length} panel{cells.length === 1 ? '' : 's'}
        </span>
        <span>
          {page.cols}×{page.rows} grid
        </span>
      </div>
    </div>
  )
}
