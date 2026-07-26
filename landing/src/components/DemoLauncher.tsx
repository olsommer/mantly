import { useEffect, useRef, useState } from "react"
import { ArrowUpRight, Sparkles } from "lucide-react"
import { GuidedDemoPanel } from "@/components/GuidedDemo"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { useTranslation } from "@/i18n/useTranslation"
import { guidedDemoCopy } from "@/components/guided-demo-data"

const OPEN_DEMO_EVENT = "mantly:open-demo"

export function DemoLauncher() {
  const { lang } = useTranslation()
  const [open, setOpen] = useState(false)
  const [showLauncher, setShowLauncher] = useState(false)
  const openerRef = useRef<HTMLElement | null>(null)
  const copy = guidedDemoCopy[lang]

  useEffect(() => {
    const openDemo = () => {
      if (document.activeElement instanceof HTMLElement) {
        openerRef.current = document.activeElement
      }
      setOpen(true)
    }
    window.addEventListener(OPEN_DEMO_EVENT, openDemo)
    return () => window.removeEventListener(OPEN_DEMO_EVENT, openDemo)
  }, [])

  useEffect(() => {
    const heroTrigger = document.querySelector('[data-testid="hero-demo-trigger"]')
    if (!heroTrigger) return

    const observer = new IntersectionObserver(
      ([entry]) => setShowLauncher(!entry?.isIntersecting),
      { threshold: 0.2 },
    )
    observer.observe(heroTrigger)
    return () => observer.disconnect()
  }, [])

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      {showLauncher ? (
        <SheetTrigger asChild>
          <Button
            type="button"
            data-testid="demo-launcher"
            size="lg"
            className="fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-40 h-12 w-12 rounded-full px-0 shadow-xl shadow-primary/20 sm:bottom-6 sm:right-6 sm:w-auto sm:px-5"
            aria-label={copy.launcher}
            onPointerDown={(event) => {
              openerRef.current = event.currentTarget
            }}
            onClick={(event) => {
              openerRef.current = event.currentTarget
            }}
          >
            <Sparkles className="size-4" aria-hidden="true" />
            <span className="hidden sm:inline">{copy.launcher}</span>
            <ArrowUpRight className="hidden size-4 sm:block" aria-hidden="true" />
          </Button>
        </SheetTrigger>
      ) : null}
      <SheetContent
        data-testid="demo-sheet"
        side="right"
        showCloseButton={false}
        className="inset-0 h-[100dvh] w-full max-w-none gap-0 overflow-hidden border-0 p-0 sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[460px] sm:max-w-[460px] sm:border-l"
        onCloseAutoFocus={(event) => {
          if (!openerRef.current?.isConnected) return
          event.preventDefault()
          window.requestAnimationFrame(() => openerRef.current?.focus())
        }}
      >
        <GuidedDemoPanel lang={lang} />
      </SheetContent>
    </Sheet>
  )
}
