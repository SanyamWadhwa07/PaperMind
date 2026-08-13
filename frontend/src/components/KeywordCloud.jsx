import { Badge, Card, CardBody, Eyebrow } from './ui/primitives'

/**
 * Weight, not size, carries rank. A true size-scaled cloud fights the type
 * scale, so the leading terms simply sit first and read in ink while the tail
 * fades — the ordering does the work.
 */
export default function KeywordCloud({ overallKeywords, sectionKeywords }) {
  return (
    <div className="space-y-8">
      <div>
        <Eyebrow className="block">Keywords</Eyebrow>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {overallKeywords && overallKeywords.length > 0 ? (
            overallKeywords.map((keyword, idx) => (
              <Badge key={idx} tone={idx < 3 ? 'accent' : 'outline'} mono>
                {keyword}
              </Badge>
            ))
          ) : (
            <p className="text-sm text-ink-faint">No keywords extracted.</p>
          )}
        </div>
      </div>

      {sectionKeywords && Object.keys(sectionKeywords).length > 0 && (
        <div>
          <Eyebrow className="block">By section</Eyebrow>
          <div className="mt-3 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Object.entries(sectionKeywords).map(([section, keywords]) => (
              <Card key={section}>
                <CardBody className="p-4">
                  <h4 className="text-sm font-medium capitalize text-ink">
                    {section.replace(/_/g, ' ')}
                  </h4>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {keywords.slice(0, 5).map((keyword, idx) => (
                      <Badge key={idx} tone="outline" mono>
                        {keyword}
                      </Badge>
                    ))}
                  </div>
                </CardBody>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
