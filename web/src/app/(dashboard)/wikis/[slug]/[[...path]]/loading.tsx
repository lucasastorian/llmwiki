function SkeletonLine({ className = '' }: { className?: string }) {
  return <div className={`rounded-md bg-muted/50 animate-pulse ${className}`} />
}

export default function Loading() {
  return (
    <div className="flex h-full overflow-hidden bg-background">
      <aside className="w-[272px] shrink-0 border-r border-border">
        <div className="px-2 pt-2 pb-1">
          <SkeletonLine className="h-9 w-full" />
        </div>
        <div className="px-2 pb-1 flex items-center gap-1.5">
          <SkeletonLine className="h-8 flex-1" />
          <SkeletonLine className="size-8 shrink-0" />
          <SkeletonLine className="size-8 shrink-0" />
        </div>
        <div className="px-4 pt-3 space-y-2">
          <SkeletonLine className="h-4 w-24" />
          <SkeletonLine className="h-5 w-44" />
          <SkeletonLine className="h-5 w-36" />
          <SkeletonLine className="h-5 w-48" />
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-3xl px-8 py-10">
          <SkeletonLine className="h-4 w-32" />
          <SkeletonLine className="mt-4 h-8 w-2/3" />
          <div className="mt-8 space-y-3">
            <SkeletonLine className="h-4 w-full" />
            <SkeletonLine className="h-4 w-11/12" />
            <SkeletonLine className="h-4 w-10/12" />
          </div>
        </div>
      </main>
    </div>
  )
}
