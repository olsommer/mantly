import { useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { useTranslation } from "@/i18n/useTranslation"

type InteractiveDemoComponent = () => ReactNode

export function DemoLauncher() {
  const { t } = useTranslation()
  const rootRef = useRef<HTMLDivElement>(null)
  const [Demo, setDemo] = useState<InteractiveDemoComponent | null>(null)

  useEffect(() => {
    const node = rootRef.current
    if (!node) return

    let cancelled = false
    const loadDemo = async () => {
      const mod = await import("@/components/InteractiveDemo")
      if (!cancelled) setDemo(() => mod.InteractiveDemo)
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return
        observer.disconnect()
        void loadDemo()
      },
      { rootMargin: "320px 0px" }
    )

    observer.observe(node)
    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [])

  return (
    <div ref={rootRef}>
      {Demo ? (
        <Demo />
      ) : (
        <div className="rounded-2xl border border-border bg-gradient-to-b from-muted/50 to-muted/20 p-1 shadow-2xl shadow-black/5">
          <div className="flex min-h-[520px] items-center justify-center rounded-xl bg-background/95 text-sm text-muted-foreground">
            {t("interactiveDemo.loading")}
          </div>
        </div>
      )}
    </div>
  )
}
