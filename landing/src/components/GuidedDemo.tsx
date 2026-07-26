import { useEffect, useRef, useState } from "react"
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  CheckCircle2,
  CircleDotDashed,
  Clock3,
  GitBranch,
  Inbox,
  Mail,
  MessageSquareText,
  MessagesSquare,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Wrench,
  X,
} from "lucide-react"
import type { Language } from "@/i18n/translations"
import { Button } from "@/components/ui/button"
import { SheetClose, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import {
  GUIDED_DEMO_SCENARIO_IDS,
  guidedDemoCopy,
  type GuidedDemoScenario,
  type GuidedDemoScenarioId,
} from "@/components/guided-demo-data"

type DemoTab = "customer" | "agent"

const LAST_REPLAY_STAGE = 5
const REPLAY_STAGE_DELAY_MS = 1100
const REPLAY_STAGE_TEST_IDS = [
  "demo-stage-inbound",
  "demo-stage-concerns",
  "demo-stage-evidence",
  "demo-stage-composer",
  "demo-stage-response",
] as const

interface GuidedDemoPanelProps {
  lang: Language
}

function ChannelIcon({ scenario }: { scenario: GuidedDemoScenario }) {
  const Icon = scenario.channel === "web_chat" ? MessagesSquare : Mail
  return <Icon className="size-3.5" aria-hidden="true" />
}

function StageProgress({
  labels,
  stage,
  currentLabel,
  completeLabel,
  waitingLabel,
  progressLabel,
}: {
  labels: readonly string[]
  stage: number
  currentLabel: string
  completeLabel: string
  waitingLabel: string
  progressLabel: string
}) {
  const progress = stage === 0 ? 0 : ((stage - 1) / (LAST_REPLAY_STAGE - 1)) * 100

  return (
    <div className="relative" aria-label={progressLabel}>
      <div className="absolute left-[10%] right-[10%] top-3 h-px bg-border" aria-hidden="true">
        <div
          className="h-full bg-primary transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ol className="relative grid grid-cols-5 gap-1">
        {labels.map((label, index) => {
          const stageNumber = index + 1
          const isComplete = stage > stageNumber
          const isCurrent = stage === stageNumber
          const statusLabel = isComplete
            ? completeLabel
            : isCurrent
              ? currentLabel
              : waitingLabel

          return (
            <li
              key={label}
              className="flex min-w-0 flex-col items-center gap-1.5 text-center"
              aria-current={isCurrent ? "step" : undefined}
              aria-label={`${label}: ${statusLabel}`}
            >
              <span
                className={cn(
                  "relative z-10 flex size-6 items-center justify-center rounded-full border bg-background transition-colors",
                  isComplete && "border-primary bg-primary text-primary-foreground",
                  isCurrent && "border-primary text-primary ring-4 ring-primary/10",
                )}
              >
                {isComplete ? (
                  <Check className="size-3" aria-hidden="true" />
                ) : isCurrent ? (
                  <span className="size-2 rounded-full bg-primary" aria-hidden="true" />
                ) : (
                  <span className="size-1.5 rounded-full bg-muted-foreground/30" aria-hidden="true" />
                )}
              </span>
              <span className={cn("truncate text-[10px] text-muted-foreground", isCurrent && "font-medium text-foreground")}>{label}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function StageCard({
  testId,
  icon: Icon,
  eyebrow,
  title,
  children,
}: {
  testId: string
  icon: typeof Inbox
  eyebrow: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section
      data-testid={testId}
      className="animate-in fade-in slide-in-from-bottom-2 rounded-xl border border-border/70 bg-background p-4 duration-300"
    >
      <div className="mb-3 flex items-start gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{eyebrow}</p>
          <h3 className="mt-0.5 text-base font-semibold leading-tight">{title}</h3>
        </div>
      </div>
      {children}
    </section>
  )
}

export function GuidedDemoPanel({ lang }: GuidedDemoPanelProps) {
  const copy = guidedDemoCopy[lang]
  const [selectedId, setSelectedId] = useState<GuidedDemoScenarioId>("logistics")
  const [activeTab, setActiveTab] = useState<DemoTab>("customer")
  const [replayStage, setReplayStage] = useState(0)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const scenario = copy.scenarios[selectedId]

  useEffect(() => {
    if (replayStage === 0 || replayStage >= LAST_REPLAY_STAGE) return

    const timer = window.setTimeout(() => {
      setReplayStage((current) => Math.min(current + 1, LAST_REPLAY_STAGE))
    }, REPLAY_STAGE_DELAY_MS)

    return () => window.clearTimeout(timer)
  }, [replayStage])

  useEffect(() => {
    const scrollArea = scrollAreaRef.current
    if (!scrollArea) return

    if (replayStage === 0) {
      scrollArea.scrollTo({ top: 0 })
      return
    }

    const animationFrame = window.requestAnimationFrame(() => {
      const testId = REPLAY_STAGE_TEST_IDS[replayStage - 1]
      const stage = testId
        ? scrollArea.querySelector<HTMLElement>(`[data-testid="${testId}"]`)
        : null
      if (!stage) return

      const scrollAreaRect = scrollArea.getBoundingClientRect()
      const stageRect = stage.getBoundingClientRect()
      const top = scrollArea.scrollTop + stageRect.top - scrollAreaRect.top
      scrollArea.scrollTo({
        top,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      })
    })

    return () => window.cancelAnimationFrame(animationFrame)
  }, [replayStage])

  const chooseScenario = (id: GuidedDemoScenarioId) => {
    setSelectedId(id)
    setReplayStage(0)
    setActiveTab("customer")
  }

  const startReplay = () => {
    setReplayStage(1)
    setActiveTab("agent")
  }

  const stageAnnouncement = replayStage > 0
    ? `${copy.stages[replayStage - 1]}: ${copy.stageCurrent}`
    : copy.replayReady

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <SheetHeader className="shrink-0 border-b border-border/70 px-4 py-4 pr-16 sm:px-5 sm:py-5 sm:pr-16">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
          <Sparkles className="size-3.5" aria-hidden="true" />
          {copy.simulationLabel}
        </div>
        <SheetTitle className="mt-1 text-xl leading-tight sm:text-2xl">{copy.title}</SheetTitle>
        <SheetDescription className="max-w-md leading-relaxed">{copy.description}</SheetDescription>
      </SheetHeader>

      <SheetClose asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-3 top-3 z-10 size-11 rounded-full sm:right-4 sm:top-4"
          aria-label={copy.close}
        >
          <X className="size-5" aria-hidden="true" />
        </Button>
      </SheetClose>

      <div className="shrink-0 border-b border-border/70 px-4 pt-3 sm:px-5">
        <div role="tablist" aria-label={copy.title} className="grid grid-cols-2 rounded-lg bg-muted p-1">
          <button
            id="mantly-demo-customer-tab"
            type="button"
            role="tab"
            aria-selected={activeTab === "customer"}
            aria-controls="mantly-demo-customer-panel"
            onClick={() => setActiveTab("customer")}
            className={cn(
              "min-h-11 rounded-md px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              activeTab === "customer" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {copy.customerTab}
          </button>
          <button
            id="mantly-demo-agent-tab"
            type="button"
            role="tab"
            aria-selected={activeTab === "agent"}
            aria-controls="mantly-demo-agent-panel"
            onClick={() => setActiveTab("agent")}
            className={cn(
              "min-h-11 rounded-md px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              activeTab === "agent" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {copy.agentTab}
          </button>
        </div>
      </div>

      <div
        ref={scrollAreaRef}
        className="min-h-0 flex-1 scroll-py-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
      >
        <div
          id="mantly-demo-customer-panel"
          role="tabpanel"
          aria-labelledby="mantly-demo-customer-tab"
          hidden={activeTab !== "customer"}
        >
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold">{copy.chooseMessage}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{copy.chooseMessageHint}</p>
            </div>

            <div className="grid grid-cols-3 gap-2" aria-label={copy.chooseMessage}>
              {GUIDED_DEMO_SCENARIO_IDS.map((id) => {
                const option = copy.scenarios[id]
                const selected = id === selectedId
                return (
                  <button
                    key={id}
                    type="button"
                    data-testid={`demo-scenario-${id}`}
                    aria-pressed={selected}
                    onClick={() => chooseScenario(id)}
                    className={cn(
                      "min-h-12 rounded-lg border px-2 py-2 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      selected
                        ? "border-primary bg-primary/5 text-primary"
                        : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                    )}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>

            <article className="overflow-hidden rounded-xl border border-border/70 bg-background shadow-sm">
              <div className="border-b border-border/70 bg-muted/35 px-4 py-3">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">{scenario.eyebrow}</p>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <ChannelIcon scenario={scenario} />
                    {scenario.channelLabel}
                  </div>
                </div>
              </div>
              <dl className="grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-2 border-b border-border/70 px-4 py-3 text-xs">
                <dt className="text-muted-foreground">{copy.from}</dt>
                <dd className="min-w-0 truncate font-medium">{scenario.sender}</dd>
                <dt className="text-muted-foreground">{copy.subject}</dt>
                <dd className="font-medium leading-relaxed">{scenario.subject}</dd>
              </dl>
              <p className="whitespace-pre-wrap px-4 py-4 text-sm leading-6">{scenario.body}</p>
            </article>

            <Button type="button" className="h-11 w-full" onClick={startReplay}>
              <Play className="size-4" aria-hidden="true" />
              {copy.runReplay}
              <ArrowRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        <div
          id="mantly-demo-agent-panel"
          role="tabpanel"
          aria-labelledby="mantly-demo-agent-tab"
          hidden={activeTab !== "agent"}
        >
          <div className="space-y-4">
            <StageProgress
              labels={copy.stages}
              stage={replayStage}
              currentLabel={copy.stageCurrent}
              completeLabel={copy.stageComplete}
              waitingLabel={copy.stageWaiting}
              progressLabel={copy.replayProgress}
            />

            <p className="sr-only" aria-live="polite" aria-atomic="true">{stageAnnouncement}</p>

            {replayStage === 0 ? (
              <div className="rounded-xl border border-dashed bg-muted/25 px-5 py-8 text-center">
                <CircleDotDashed className="mx-auto size-7 text-primary" aria-hidden="true" />
                <h3 className="mt-3 text-base font-semibold">{copy.replayReady}</h3>
                <p className="mx-auto mt-1 max-w-sm text-sm leading-relaxed text-muted-foreground">{copy.replayReadyDetail}</p>
                <Button type="button" className="mt-4 h-11" onClick={startReplay}>
                  <Play className="size-4" aria-hidden="true" />
                  {copy.runReplay}
                </Button>
              </div>
            ) : null}

            {replayStage >= 1 ? (
              <StageCard
                testId="demo-stage-inbound"
                icon={Inbox}
                eyebrow={copy.stages[0]}
                title={scenario.ticketId}
              >
                <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/45 px-3 py-2.5 text-sm">
                  <span className="flex min-w-0 items-center gap-2 font-medium">
                    <ChannelIcon scenario={scenario} />
                    <span className="truncate">{scenario.channelLabel}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5 text-xs text-emerald-700">
                    <CheckCircle2 className="size-3.5" aria-hidden="true" />
                    {copy.stageComplete}
                  </span>
                </div>
              </StageCard>
            ) : null}

            {replayStage >= 2 ? (
              <StageCard
                testId="demo-stage-concerns"
                icon={GitBranch}
                eyebrow={copy.stages[1]}
                title={`${copy.detectedConcerns} · ${scenario.concerns.length}`}
              >
                <div className="space-y-2">
                  {scenario.concerns.map((concern) => (
                    <div
                      key={concern.id}
                      data-testid={`demo-concern-${concern.id}`}
                      className="rounded-lg border border-border/70 bg-muted/20 p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium leading-snug">{concern.title}</p>
                          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                            <span className="font-medium text-foreground">{copy.customerQuestion}:</span> {concern.question}
                          </p>
                        </div>
                        <span className="shrink-0 rounded-full bg-primary/10 px-2 py-1 font-mono text-[10px] text-primary">{concern.id}</span>
                      </div>
                      <div
                        data-testid={`demo-runbook-${concern.id}`}
                        className="mt-2 flex items-center gap-1.5 text-xs text-primary"
                      >
                        <GitBranch className="size-3.5" aria-hidden="true" />
                        <span className="text-muted-foreground">{copy.runbook}:</span>
                        <span className="font-medium">{concern.runbook}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </StageCard>
            ) : null}

            {replayStage >= 3 ? (
              <StageCard
                testId="demo-stage-evidence"
                icon={Wrench}
                eyebrow={copy.stages[2]}
                title={copy.evidenceAndActions}
              >
                <div className="space-y-4">
                  {scenario.concerns.map((concern) => (
                    <div key={concern.id} className="space-y-2">
                      <div className="flex items-center gap-2 text-xs font-semibold">
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{concern.id}</span>
                        <span>{concern.runbook}</span>
                      </div>
                      {concern.evidence.map((evidence) => {
                        const EvidenceIcon = evidence.kind === "knowledge" ? BookOpenCheck : CheckCircle2
                        return (
                          <div key={`${concern.id}-${evidence.title}`} className="rounded-lg border border-emerald-200/80 bg-emerald-50/60 p-3">
                            <div className="flex items-start gap-2.5">
                              <EvidenceIcon className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-hidden="true" />
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center justify-between gap-1.5">
                                  <p className="text-xs font-semibold">{evidence.title}</p>
                                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">{evidence.status}</span>
                                </div>
                                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{evidence.detail}</p>
                                <p className="mt-1 text-[10px] font-medium uppercase tracking-wide text-emerald-800">
                                  {evidence.kind === "knowledge" ? copy.knowledge : copy.tool}
                                </p>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                      <div
                        className={cn(
                          "rounded-lg border p-3",
                          concern.action.state === "pending"
                            ? "border-amber-200/80 bg-amber-50/70"
                            : "border-border/70 bg-muted/30",
                        )}
                      >
                        <div className="flex items-start gap-2.5">
                          {concern.action.state === "pending" ? (
                            <Clock3 className="mt-0.5 size-4 shrink-0 text-amber-700" aria-hidden="true" />
                          ) : (
                            <Check className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center justify-between gap-1.5">
                              <p className="text-xs font-semibold">{concern.action.label}</p>
                              <span
                                className={cn(
                                  "rounded-full px-2 py-0.5 text-[10px] font-medium",
                                  concern.action.state === "pending"
                                    ? "bg-amber-100 text-amber-900"
                                    : "bg-muted text-muted-foreground",
                                )}
                              >
                                {concern.action.status}
                              </span>
                            </div>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{concern.action.detail}</p>
                            <p className="mt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{copy.action}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </StageCard>
            ) : null}

            {replayStage >= 4 ? (
              <StageCard
                testId="demo-stage-composer"
                icon={MessageSquareText}
                eyebrow={copy.stages[3]}
                title={copy.oneComposer}
              >
                <p data-testid="demo-composer" className="text-sm leading-relaxed text-muted-foreground">
                  {copy.composerDetail}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-lg border bg-muted/25 p-3 text-center">
                    <p className="text-lg font-semibold text-primary">{scenario.concerns.length}/{scenario.concerns.length}</p>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{copy.concernsCovered}</p>
                  </div>
                  <div className="rounded-lg border bg-muted/25 p-3 text-center">
                    <p className="text-lg font-semibold text-primary">{scenario.obligationCount}/{scenario.obligationCount}</p>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{copy.questionsCovered}</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-800">
                    <ShieldCheck className="size-3.5" aria-hidden="true" />
                    {copy.groundingPassed}
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900">
                    <Clock3 className="size-3.5" aria-hidden="true" />
                    {scenario.composerStatus}
                  </span>
                </div>
              </StageCard>
            ) : null}

            {replayStage >= 5 ? (
              <StageCard
                testId="demo-stage-response"
                icon={Sparkles}
                eyebrow={copy.stages[4]}
                title={copy.oneResponse}
              >
                <div
                  data-testid="demo-final-reply"
                  className="whitespace-pre-wrap rounded-lg border border-primary/20 bg-primary/[0.035] p-3 text-sm leading-6"
                >
                  {scenario.response}
                </div>
                <Button type="button" variant="outline" className="mt-3 h-11 w-full" onClick={startReplay}>
                  <RotateCcw className="size-4" aria-hidden="true" />
                  {copy.replay}
                </Button>
              </StageCard>
            ) : null}
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-border/70 bg-muted/30 px-4 py-2.5 text-center text-[10px] text-muted-foreground sm:px-5">
        {copy.simulationDisclosure}
      </div>
    </div>
  )
}
