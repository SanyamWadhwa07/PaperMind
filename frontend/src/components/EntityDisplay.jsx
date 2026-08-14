import { Database, Cpu, BarChart3, Wrench, FlaskConical } from 'lucide-react'
import {
  Badge,
  Bento,
  BentoItem,
  Card,
  CardBody,
  EmptyState,
  Eyebrow,
  ScrollArea,
} from './ui/primitives'

/**
 * Domain-agnostic typed entities from the LangGraph engine. Each kind gets one
 * of the system's stage pastels so the four categories stay distinguishable
 * without four different action colours competing with the accent.
 */
const KIND_META = {
  method: { label: 'Methods', icon: FlaskConical, stage: 4 },
  material: { label: 'Materials & data', icon: Database, stage: 3 },
  measurement: { label: 'Measurements', icon: BarChart3, stage: 2 },
  tool: { label: 'Tools', icon: Wrench, stage: 1 },
}

const STAGE_DOT = {
  1: 'bg-stage-1',
  2: 'bg-stage-2',
  3: 'bg-stage-3',
  4: 'bg-stage-4',
}

/**
 * One kind of entity, as a bag of badges.
 *
 * Extraction counts are wildly uneven — a paper can name three tools and eighty
 * measurements — so the badge list scrolls rather than letting the busiest kind
 * stretch its tile and leave the other three sitting in whitespace.
 */
function EntityGroup({ label, icon: Icon, stage, items, emptyText }) {
  return (
    <Card className="flex h-full flex-col">
      <CardBody className="pb-0">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${STAGE_DOT[stage]}`}
            aria-hidden="true"
          />
          <Icon className="h-4 w-4 text-ink-faint" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-ink">{label}</h3>
          {items.length > 0 && (
            <span className="ml-auto font-mono tabular text-code text-ink-faint">
              {items.length}
            </span>
          )}
        </div>
      </CardBody>

      <ScrollArea maxHeight="16rem" aria-label={label} className="min-h-0 flex-1">
        <CardBody className="pt-4">
          <div className="flex flex-wrap gap-1.5">
            {items.length > 0 ? (
              items.map((item, idx) => (
                <Badge
                  key={idx}
                  tone="outline"
                  mono
                  title={item.description || undefined}
                >
                  {item.name ?? item}
                </Badge>
              ))
            ) : (
              <p className="text-sm text-ink-faint">{emptyText}</p>
            )}
          </div>
        </CardBody>
      </ScrollArea>
    </Card>
  )
}

export default function EntityDisplay({ entities, typed }) {
  // Prefer the domain-agnostic typed entities (works for any field, not just ML).
  const typedList = typed?.entities || []

  if (typedList.length > 0) {
    const byKind = { method: [], material: [], measurement: [], tool: [] }
    typedList.forEach((e) => {
      if (!byKind[e.kind]) byKind[e.kind] = []
      byKind[e.kind].push(e)
    })

    return (
      <div>
        <Eyebrow className="block">Extracted from the paper</Eyebrow>
        <Bento className="mt-4">
          {Object.entries(KIND_META).map(([kind, { label, icon, stage }]) => (
            <BentoItem key={kind} span={3}>
              <EntityGroup
                label={label}
                icon={icon}
                stage={stage}
                items={byKind[kind] || []}
                emptyText="None detected"
              />
            </BentoItem>
          ))}
        </Bento>
      </div>
    )
  }

  // Legacy fallback: datasets / models / metrics buckets.
  if (!entities) {
    return (
      <EmptyState
        icon={Database}
        title="No entities extracted"
        description="Either PaperMind processed this paper before it could extract entities, or it found none."
      />
    )
  }

  const legacyTypes = [
    { key: 'datasets', label: 'Datasets', icon: Database, stage: 3 },
    { key: 'models', label: 'Models', icon: Cpu, stage: 4 },
    { key: 'metrics', label: 'Metrics', icon: BarChart3, stage: 2 },
  ]

  return (
    <div>
      <Eyebrow className="block">Extracted from the paper</Eyebrow>
      <Bento className="mt-4">
        {legacyTypes.map(({ key, label, icon, stage }) => (
          <BentoItem key={key} span={2}>
            <EntityGroup
              label={label}
              icon={icon}
              stage={stage}
              items={entities[key] || []}
              emptyText={`No ${label.toLowerCase()} detected`}
            />
          </BentoItem>
        ))}
      </Bento>
    </div>
  )
}
