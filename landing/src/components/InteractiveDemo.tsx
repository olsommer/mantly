import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, Play, RotateCcw } from "lucide-react"
import {
  DEFAULT_INTERACTIVE_DEMO_SCENARIO_ID,
  getInteractiveDemoScenario,
  getInteractiveDemoScenarios,
  type DemoScenarioId,
} from "@demo/interactive-scenarios"
import { useTranslation } from "@/i18n/useTranslation"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

type EmbedStatus = "idle" | "processing" | "done" | "error"

const readEnvString = (key: string): string | undefined => {
  const value = (import.meta.env as Record<string, unknown>)[key]
  return typeof value === "string" && value ? value : undefined
}

const addinDemoUrl: string =
  readEnvString("VITE_ADDIN_DEMO_URL")
  ?? (import.meta.env.DEV
    ? "http://localhost:5173/addin/?embed=landing-demo"
    : "https://addin.mantly.io/?embed=landing-demo")

const addinOrigin = new URL(addinDemoUrl).origin

export function InteractiveDemo() {
  const { lang, t } = useTranslation()
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const previousLangRef = useRef(lang)
  const [selectedId, setSelectedId] = useState<DemoScenarioId>(DEFAULT_INTERACTIVE_DEMO_SCENARIO_ID)
  const [loadEmbed, setLoadEmbed] = useState(false)
  const [iframeReady, setIframeReady] = useState(false)
  const [pendingRun, setPendingRun] = useState(false)
  const [status, setStatus] = useState<EmbedStatus>("idle")
  const scenarios = useMemo(() => getInteractiveDemoScenarios(lang), [lang])
  const scenario = useMemo(() => getInteractiveDemoScenario(lang, selectedId), [lang, selectedId])
  const statusText =
    status === "processing"
      ? t("interactiveDemo.status.processing")
      : status === "done"
        ? t("interactiveDemo.status.done")
        : pendingRun
          ? t("interactiveDemo.status.preparing")
          : iframeReady
            ? t("interactiveDemo.status.ready")
            : ""

  const postToEmbed = useCallback((message: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(message, addinOrigin)
  }, [])

  const resetEmbed = useCallback(() => {
    setStatus("idle")
    postToEmbed({ type: "reset" })
  }, [postToEmbed])

  const runDemo = useCallback(() => {
    if (!loadEmbed || !iframeReady) {
      setLoadEmbed(true)
      setPendingRun(true)
      return
    }
    setStatus("processing")
    postToEmbed({ type: "run-cached-demo", scenarioId: selectedId, locale: lang })
  }, [iframeReady, lang, loadEmbed, postToEmbed, selectedId])

  const handleScenarioSelect = useCallback((id: DemoScenarioId) => {
    setSelectedId(id)
    resetEmbed()
  }, [resetEmbed])

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.origin !== addinOrigin) return
      if (event.source !== iframeRef.current?.contentWindow) return
      const data = typeof event.data === "object" && event.data !== null
        ? event.data as Record<string, unknown>
        : {}

      if (data.type === "embed-ready") {
        setIframeReady(true)
        postToEmbed({ type: "embed-ack" })
        postToEmbed({ type: "set-locale", locale: lang })
      }
      if (data.type === "embed-status") {
        const nextStatus = data.status
        if (
          nextStatus === "idle"
          || nextStatus === "processing"
          || nextStatus === "done"
          || nextStatus === "error"
        ) {
          setStatus(nextStatus)
        }
      }
    }

    window.addEventListener("message", handler)
    return () => window.removeEventListener("message", handler)
  }, [lang, postToEmbed])

  useEffect(() => {
    if (!iframeReady || !pendingRun) return
    const timer = window.setTimeout(() => {
      setPendingRun(false)
      setStatus("processing")
      postToEmbed({ type: "run-cached-demo", scenarioId: selectedId, locale: lang })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [iframeReady, lang, pendingRun, postToEmbed, selectedId])

  useEffect(() => {
    if (previousLangRef.current === lang) return
    previousLangRef.current = lang
    if (!loadEmbed || !iframeReady) return
    postToEmbed({ type: "set-locale", locale: lang })
    if (status === "done") {
      postToEmbed({ type: "run-cached-demo", scenarioId: selectedId, locale: lang })
    }
  }, [iframeReady, lang, loadEmbed, postToEmbed, selectedId, status])

  return (
    <div className="rounded-2xl border border-border bg-gradient-to-b from-muted/50 to-muted/20 p-1 shadow-2xl shadow-black/5">
      <div className="overflow-hidden rounded-xl bg-background/95 text-left shadow-sm">
        <div className="border-b px-5 py-4">
          <div className="flex flex-col gap-4">
            <div className="min-w-0">
              <h2 className="text-[2.5rem] font-normal leading-tight sm:text-[3rem] lg:text-[3.5rem]">
                {t("interactiveDemo.title")}
              </h2>
              <p className="mt-1 max-w-2xl text-base text-muted-foreground">
                {t("interactiveDemo.subtitle")}
              </p>
            </div>
          </div>
        </div>

        <div className="grid min-h-0 grid-rows-[auto_680px] overflow-hidden lg:grid-cols-[minmax(0,6fr)_minmax(360px,4fr)] lg:grid-rows-[680px]">
          <section className="flex min-h-0 flex-col overflow-hidden border-b bg-muted/30 p-4 lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-primary">
                  {t("interactiveDemo.scenario")}
                </p>
                <h2 className="mt-1">
                  <Select
                    value={selectedId}
                    onValueChange={(value) => handleScenarioSelect(value as DemoScenarioId)}
                  >
                    <SelectTrigger
                      aria-label={t("interactiveDemo.chooseScenario")}
                      className="h-auto w-full max-w-full bg-background px-3 py-2 text-left text-2xl font-normal shadow-none [&>svg]:ml-2 [&>svg]:size-5"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent align="start">
                      {scenarios.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </h2>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2">
              <Button
                type="button"
                onClick={runDemo}
                disabled={status === "processing" || pendingRun}
                className="justify-center"
              >
                <Play className="size-4" />
                {t("interactiveDemo.start")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={resetEmbed}
                disabled={!iframeReady || status === "processing"}
                className="justify-center"
              >
                <RotateCcw className="size-4" />
                {t("interactiveDemo.reset")}
              </Button>
            </div>

            <div className="mt-4 flex min-h-0 flex-1 flex-col rounded-md border bg-background">
              <div className="space-y-2 border-b p-4">
                <div className="grid grid-cols-[4.5rem_1fr] gap-2 text-sm">
                  <span className="text-muted-foreground">{t("interactiveDemo.from")}</span>
                  <span className="truncate font-medium">{scenario.email.fromAddress}</span>
                  <span className="text-muted-foreground">{t("interactiveDemo.subject")}</span>
                  <span className="font-medium">{scenario.email.subject}</span>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap p-4 text-base leading-relaxed">
                {scenario.email.body}
              </div>
              <div className="border-t p-4 text-sm text-muted-foreground">
                {t("interactiveDemo.attachments")}: {scenario.email.attachments.length || t("interactiveDemo.noAttachments")}
              </div>
            </div>

            {statusText ? (
              <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <span
                  className={cn(
                    "size-2 rounded-full",
                    status === "done"
                      ? "bg-emerald-500"
                      : status === "processing"
                        ? "bg-primary"
                        : status === "error"
                          ? "bg-destructive"
                          : "bg-muted-foreground/40"
                  )}
                />
                {statusText}
              </div>
            ) : null}
          </section>

          <section className="flex min-h-0 min-w-0 flex-col bg-background">
            <div className="border-b px-4 py-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  {t("interactiveDemo.addin")}
                </p>
                <p className="text-sm text-muted-foreground">{t("interactiveDemo.demoMode")}</p>
              </div>
            </div>
            {loadEmbed ? (
              <iframe
                ref={iframeRef}
                src={addinDemoUrl}
                title={t("interactiveDemo.iframeTitle")}
                loading="lazy"
                className="min-h-0 flex-1 border-0"
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-6 text-center">
                <div className="flex max-w-[220px] flex-col items-center gap-3 text-sm text-muted-foreground">
                  <ArrowLeft className="size-6 text-primary" />
                  <p>{t("interactiveDemo.empty")}</p>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
