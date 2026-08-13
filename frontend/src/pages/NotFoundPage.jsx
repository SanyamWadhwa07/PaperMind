import { FileQuestion } from 'lucide-react'
import { Button, EmptyState } from '../components/ui/primitives'

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-lg py-16">
      <EmptyState
        icon={FileQuestion}
        title="No page at this address"
        description="The link may be out of date, or the paper it pointed to was deleted."
        action={
          <div className="flex gap-2">
            <Button to="/dashboard">Go to library</Button>
            <Button to="/" variant="secondary">
              Add a paper
            </Button>
          </div>
        }
      />
    </div>
  )
}
