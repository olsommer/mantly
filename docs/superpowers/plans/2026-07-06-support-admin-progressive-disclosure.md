# Support Admin Progressive Disclosure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Channel setup, Accounts, and Analytics usable as support admin workspaces by moving dense diagnostics and bounded workflows into shadcn Dialog, Sheet, and Tabs surfaces.

**Architecture:** Keep current APIs, data loaders, mutations, and domain objects. Refactor route-local JSX and state only: dialogs handle bounded tasks, sheets handle diagnostics/evidence, tabs separate analytics mental models. Add stable DOM anchors for browser verification and keep existing mutation buttons wired to existing functions.

**Tech Stack:** React 19, TypeScript, Vite, shadcn UI primitives, Radix Dialog/Sheet/Tabs, lucide-react, sonner, backend uv/Ruff/pytest.

---

## Files

- Modify: `admin/src/routes/Channels.tsx`
  - Add route-local Dialog/Sheet state.
  - Move advanced channel checks into a Dialog.
  - Move launch details, provider setup evidence, histories, webhook inboxes, delivery history, web chat sessions, queues detail, and CRM connector detail into Sheets.
  - Keep provider readiness and essential selected-channel fields visible.
- Modify: `admin/src/routes/Accounts.tsx`
  - Add route-local Dialog/Sheet state.
  - Move add-insight form into a Dialog.
  - Move account action queue and CRM/external diagnostics into Sheets.
  - Keep account health, next action, insight cards, contacts, and recent issues visible.
- Modify: `admin/src/routes/Analytics.tsx`
  - Add route-local Sheet state and shadcn Tabs.
  - Make Overview the default decision dashboard.
  - Move launch proof, channel remediation, schema health detail, and raw metric walls behind Sheets or non-default tabs.
- Use existing: `admin/src/components/ui/dialog.tsx`
- Use existing: `admin/src/components/ui/sheet.tsx`
- Use existing: `admin/src/components/ui/tabs.tsx`
- No backend files change in this slice.
- No API contracts change in this slice.

## Task 1: Channel Setup Dialog And Sheets

**Files:**
- Modify: `admin/src/routes/Channels.tsx`
- Test: existing route compile checks and DOM browser checks

- [ ] **Step 1: Add shadcn imports and remove Collapsible when unused**

Add these imports near the existing UI imports:

```tsx
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from '@/components/ui/sheet';
```

Keep `Collapsible` imports only until the two current Collapsible blocks are replaced. After replacement, remove:

```tsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
```

- [ ] **Step 2: Add route-local disclosure state**

Add this type near the other route-local types:

```tsx
type ChannelDetailSheet =
    | 'launchDetails'
    | 'setupDetails'
    | 'currentCursors'
    | 'syncHistory'
    | 'webhookInbox'
    | 'webChatSessions'
    | 'deliveryHistory'
    | 'queues'
    | 'crmConnectors'
    | null;
```

Add these state values after the existing `selectedCrmKey` state:

```tsx
const [advancedChecksOpen, setAdvancedChecksOpen] = useState(false);
const [channelDetailSheet, setChannelDetailSheet] = useState<ChannelDetailSheet>(null);
```

- [ ] **Step 3: Replace the Advanced checks Collapsible with a Dialog**

Replace the current `Advanced checks` Collapsible block near the Channel setup sidebar header with this wrapper. Move the existing all-channel controls and the three run-result summary blocks (`smokeRun`, `outboundSmokeRun`, `lifecycleSmokeRun`) inside `DialogContent` in the order shown below.

```tsx
<Dialog open={advancedChecksOpen} onOpenChange={setAdvancedChecksOpen}>
    <DialogTrigger asChild>
        <Button
            type="button"
            size="sm"
            variant="outline"
            className="m-3 justify-start"
            data-channel-advanced-checks-open
        >
            <CheckCircle2 className="size-4" />
            {t('Advanced checks')}
        </Button>
    </DialogTrigger>
    <DialogContent
        className="max-h-[85vh] max-w-3xl overflow-y-auto"
        data-channel-advanced-checks-dialog
    >
        <DialogHeader>
            <DialogTitle>{t('Advanced checks')}</DialogTitle>
            <DialogDescription>
                {t('Run provider smoke, outbound, lifecycle, and delivery checks across configured channels.')}
            </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
            <Select value={smokeAllTransport} onValueChange={value => setSmokeAllTransport(value as 'direct' | 'http')}>
                <SelectTrigger className="h-8 w-24 text-xs">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="direct">{t('Direct')}</SelectItem>
                    <SelectItem value="http">{t('HTTP')}</SelectItem>
                </SelectContent>
            </Select>
            <Button size="sm" variant="outline" onClick={() => void runSmokeAll()} disabled={smokingAllChannels || !testMessageBody.trim()}>
                {smokingAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                {t('Smoke')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void runOutboundSmokeAll()} disabled={smokingOutboundAllChannels || !outboundSmokeBody.trim()}>
                {smokingOutboundAllChannels ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                {t('Outbound smoke')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void runLifecycleSmokeAll()} disabled={smokingLifecycleAllChannels || !testMessageBody.trim() || !outboundSmokeBody.trim()}>
                {smokingLifecycleAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                {t('Lifecycle smoke')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void runLifecycleSmokeAll({ attachmentOnly: true })} disabled={smokingLifecycleAllChannels || !outboundSmokeBody.trim()}>
                {smokingLifecycleAllChannels ? <Loader className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                {t('Attachment lifecycle')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void runDelivery()} disabled={Boolean(deliveryRunMode)}>
                {deliveryRunMode === 'queued' ? <Loader className="size-4 animate-spin" /> : <Send className="size-4" />}
                {t('Run delivery')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => void runDelivery(true)} disabled={Boolean(deliveryRunMode)}>
                {deliveryRunMode === 'failed' ? <Loader className="size-4 animate-spin" /> : <AlertTriangle className="size-4" />}
                {t('Retry failed')}
            </Button>
        </div>
        <div className="space-y-3 text-xs">
            {smokeRun && (
                <div data-channel-smoke-run-summary className="rounded-md border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="font-medium">{t('Channel smoke')}</div>
                        <Badge variant={smokeRun.failed > 0 ? 'destructive' : 'secondary'} className="font-normal">
                            {smokeRun.status}
                        </Badge>
                    </div>
                    <div className="grid grid-cols-4 gap-2">
                        <div><div className="font-medium">{smokeRun.ready}/{smokeRun.channels}</div><div className="text-muted-foreground">{t('ready')}</div></div>
                        <div><div className="font-medium">{smokeRun.processed}</div><div className="text-muted-foreground">{t('processed')}</div></div>
                        <div><div className="font-medium">{smokeRun.failed}</div><div className="text-muted-foreground">{t('failed')}</div></div>
                        <div><div className="font-medium">{smokeRun.skipped}</div><div className="text-muted-foreground">{t('skipped')}</div></div>
                    </div>
                </div>
            )}
            {outboundSmokeRun && (
                <div data-channel-outbound-smoke-run-summary className="rounded-md border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="font-medium">{t('Outbound smoke')}</div>
                        <Badge variant={outboundSmokeRun.failed > 0 ? 'destructive' : outboundSmokeRun.deferred > 0 ? 'outline' : 'secondary'} className="font-normal">
                            {outboundSmokeRun.status}
                        </Badge>
                    </div>
                    <div className="grid grid-cols-4 gap-2">
                        <div><div className="font-medium">{outboundSmokeRun.ready}/{outboundSmokeRun.channels}</div><div className="text-muted-foreground">{t('ready')}</div></div>
                        <div><div className="font-medium">{outboundSmokeRun.sent}</div><div className="text-muted-foreground">{t('sent')}</div></div>
                        <div><div className="font-medium">{outboundSmokeRun.deferred}</div><div className="text-muted-foreground">{t('deferred')}</div></div>
                        <div><div className="font-medium">{outboundSmokeRun.failed}</div><div className="text-muted-foreground">{t('failed')}</div></div>
                    </div>
                </div>
            )}
            {lifecycleSmokeRun && (
                <div data-channel-lifecycle-smoke-run-summary className="rounded-md border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="font-medium">{t('Lifecycle smoke')}</div>
                        <Badge variant={lifecycleSmokeRun.failed > 0 ? 'destructive' : lifecycleSmokeRun.deferred > 0 ? 'outline' : 'secondary'} className="font-normal">
                            {lifecycleSmokeRun.status}
                        </Badge>
                    </div>
                    <div className="grid grid-cols-4 gap-2">
                        <div><div className="font-medium">{lifecycleSmokeRun.ready}/{lifecycleSmokeRun.channels}</div><div className="text-muted-foreground">{t('ready')}</div></div>
                        <div><div className="font-medium">{lifecycleSmokeRun.sent}</div><div className="text-muted-foreground">{t('sent')}</div></div>
                        <div><div className="font-medium">{lifecycleSmokeRun.deferred}</div><div className="text-muted-foreground">{t('deferred')}</div></div>
                        <div><div className="font-medium">{lifecycleSmokeRun.failed}</div><div className="text-muted-foreground">{t('failed')}</div></div>
                    </div>
                </div>
            )}
        </div>
    </DialogContent>
</Dialog>
```

- [ ] **Step 4: Replace Launch details Collapsible with a Sheet**

Change the current `Launch details` Collapsible trigger to a button:

```tsx
<Button
    type="button"
    size="sm"
    variant="outline"
    className="w-full justify-between px-2"
    data-channel-launch-details-open
    onClick={() => setChannelDetailSheet('launchDetails')}
>
    <span className="flex items-center gap-2">
        <Database className="size-4" />
        {t('Launch details')}
    </span>
    <ExternalLink className="size-4" />
</Button>
```

Move the current Launch details content into this sheet near the end of the route JSX, before the root closing `</div>`:

```tsx
<Sheet open={channelDetailSheet === 'launchDetails'} onOpenChange={open => setChannelDetailSheet(open ? 'launchDetails' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-channel-launch-details-sheet>
        <SheetHeader>
            <SheetTitle>{t('Launch details')}</SheetTitle>
            <SheetDescription>
                {t('Provider launch proof, activation backlog, secret template, and adapter matrix.')}
            </SheetDescription>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6" data-channel-launch-details-body />
    </SheetContent>
</Sheet>
```

Implementation rule for this step: the content moved into the sheet starts at the existing `data-channel-provider-launch-board` wrapper and ends after the existing adapter/secret/activation detail content that currently lives inside `CollapsibleContent`.
After creating the shell, replace the self-closing `data-channel-launch-details-body` element with that moved JSX block.

- [ ] **Step 5: Add selected-channel diagnostic action buttons**

In the selected channel header action area near the selected channel title, add:

```tsx
<Button type="button" size="sm" variant="outline" onClick={() => setChannelDetailSheet('setupDetails')} data-channel-setup-details-open>
    <Database className="size-4" />
    {t('Setup details')}
</Button>
<Button type="button" size="sm" variant="outline" onClick={() => setChannelDetailSheet('syncHistory')} data-channel-sync-history-open>
    <RefreshCw className="size-4" />
    {t('History')}
</Button>
```

Keep `Save`, provider install, and provider validation actions where users already expect them.

- [ ] **Step 6: Move lower diagnostic sections into Sheets**

Replace the current inline sections with compact buttons that open `channelDetailSheet` values:

```tsx
<section className="rounded-md border p-4" data-channel-diagnostics-summary>
    <div className="mb-3 flex items-center justify-between gap-3">
        <div>
            <h2 className="text-sm font-medium">{t('Diagnostics')}</h2>
            <p className="text-xs text-muted-foreground">{t('Provider evidence and operational logs stay available without filling the setup page.')}</p>
        </div>
    </div>
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('currentCursors')}>{t('Current cursors')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('syncHistory')}>{t('Sync history')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('webhookInbox')}>{t('Webhook inbox')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('webChatSessions')}>{t('Web chat sessions')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('deliveryHistory')}>{t('Delivery history')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('queues')}>{t('Queues')}</Button>
        <Button type="button" variant="outline" className="justify-start" onClick={() => setChannelDetailSheet('crmConnectors')}>{t('CRM connectors')}</Button>
    </div>
</section>
```

For each moved section, create a sheet with the same content and current data attributes:

```tsx
<Sheet open={channelDetailSheet === 'currentCursors'} onOpenChange={open => setChannelDetailSheet(open ? 'currentCursors' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-channel-current-cursors-sheet>
        <SheetHeader>
            <SheetTitle>{t('Current cursors')}</SheetTitle>
            <SheetDescription>{t('Latest provider cursor state for connected channels.')}</SheetDescription>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6" data-channel-current-cursors-body />
    </SheetContent>
</Sheet>
```

Repeat this concrete shell for `syncHistory`, `webhookInbox`, `webChatSessions`, `deliveryHistory`, `queues`, and `crmConnectors`. Use data attributes:

```tsx
data-channel-sync-history-sheet
data-channel-webhook-inbox-sheet
data-channel-web-chat-sessions-sheet
data-channel-delivery-history-sheet
data-channel-queues-sheet
data-channel-crm-connectors-sheet
```

For each sheet, replace the self-closing body marker with the current section body from the matching inline section. Preserve row keys, button handlers, and existing `data-*` attributes.

- [ ] **Step 7: Run quality checks after the route edit**

Run:

```bash
cd backend && uv run ruff check automail tests
cd backend && uv run pytest
cd admin && npm run lint
cd admin && npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit Channel setup refactor**

Run:

```bash
git add admin/src/routes/Channels.tsx
git commit -m "refactor: disclose channel setup diagnostics"
```

## Task 2: Accounts Cockpit Dialog And CRM Sheet

**Files:**
- Modify: `admin/src/routes/Accounts.tsx`
- Test: existing route compile checks and DOM browser checks

- [ ] **Step 1: Add shadcn imports**

Add:

```tsx
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from '@/components/ui/sheet';
```

- [ ] **Step 2: Add account disclosure state**

Add near route-local state:

```tsx
type AccountDetailSheet = 'actionQueue' | 'crmDetails' | null;

const [insightDialogOpen, setInsightDialogOpen] = useState(false);
const [accountDetailSheet, setAccountDetailSheet] = useState<AccountDetailSheet>(null);
```

- [ ] **Step 3: Add dialog open helper**

Add after `applyInsightTemplate`:

```tsx
const openInsightDialog = (type: string) => {
    applyInsightTemplate(type);
    setInsightDialogOpen(true);
};
```

If `applyInsightTemplate` currently returns `void`, leave it unchanged.

- [ ] **Step 4: Replace inline Account operations detail with compact cockpit summary**

Keep the top four summary counts visible. Replace the large inline action queue list with an action button:

```tsx
<section data-account-operations className="mb-5 rounded-md border p-4">
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                <Building2 className="size-4 text-muted-foreground" />
                <span className="truncate">{t('Account cockpit')}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
                {t('Customer health, next action, and account signals.')}
            </p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={() => setAccountDetailSheet('actionQueue')} data-account-action-queue-open>
            <CheckCircle2 className="size-3.5" />
            {t('Action queue')}
        </Button>
    </div>
    <div className="grid gap-2 sm:grid-cols-4">
        <div className="rounded-md border bg-muted/20 p-2 text-xs">
            <div className="font-medium">{accountOpsSummary.atRisk}</div>
            <div className="text-muted-foreground">{t('at-risk accounts')}</div>
        </div>
        <div className="rounded-md border bg-muted/20 p-2 text-xs">
            <div className="font-medium">{accountOpsSummary.needsAttention}</div>
            <div className="text-muted-foreground">{t('needs attention')}</div>
        </div>
        <div className="rounded-md border bg-muted/20 p-2 text-xs">
            <div className="font-medium">{accountOpsSummary.crmAttention}</div>
            <div className="text-muted-foreground">{t('CRM attention')}</div>
        </div>
        <div className="rounded-md border bg-muted/20 p-2 text-xs">
            <div className="font-medium">{accountOpsSummary.featureDemand}</div>
            <div className="text-muted-foreground">{t('feature requests')}</div>
        </div>
    </div>
</section>
```

Move the current `data-account-action-queue` block into this sheet:

```tsx
<Sheet open={accountDetailSheet === 'actionQueue'} onOpenChange={open => setAccountDetailSheet(open ? 'actionQueue' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-account-action-queue-sheet>
        <SheetHeader>
            <SheetTitle>{t('Action queue')}</SheetTitle>
            <SheetDescription>{t('Accounts that need risk, CRM, feature, or ticket follow-up.')}</SheetDescription>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6" data-account-action-queue-body />
    </SheetContent>
</Sheet>
```

Replace the self-closing `data-account-action-queue-body` marker with the current `data-account-action-queue` JSX block.

- [ ] **Step 5: Move Add insight form into Dialog**

Replace the template buttons and inline form inside `Account intelligence` with a compact action row:

```tsx
<div className="mb-4 flex flex-wrap gap-1.5 border-b pb-4">
    <Button type="button" size="sm" variant="outline" data-account-insight-template="risk" onClick={() => openInsightDialog('risk')}>
        <AlertTriangle className="size-3.5" />
        {t('Risk')}
    </Button>
    <Button type="button" size="sm" variant="outline" data-account-insight-template="feature_request" onClick={() => openInsightDialog('feature_request')}>
        <Lightbulb className="size-3.5" />
        {t('Feature request')}
    </Button>
    <Button type="button" size="sm" variant="outline" data-account-insight-template="summary" onClick={() => openInsightDialog('summary')}>
        <CheckCircle2 className="size-3.5" />
        {t('Summary')}
    </Button>
    <Button type="button" size="sm" onClick={() => void generateSummary()} disabled={generatingSummary} data-generate-account-summary>
        {generatingSummary ? <Loader className="size-3.5 animate-spin" /> : <Database className="size-3.5" />}
        {t('Generate summary')}
    </Button>
</div>
```

Add the dialog near the end of the selected account JSX:

```tsx
<Dialog open={insightDialogOpen} onOpenChange={setInsightDialogOpen}>
    <DialogContent data-account-add-insight-dialog>
        <DialogHeader>
            <DialogTitle>{t('Add insight')}</DialogTitle>
            <DialogDescription>{t('Capture a customer risk, feature request, or summary signal.')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-[10rem_10rem_1fr]">
            <div className="space-y-1.5">
                <Label>{t('Type')}</Label>
                <Select value={newInsightType} onValueChange={setNewInsightType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="risk">{t('Risk')}</SelectItem>
                        <SelectItem value="feature_request">{t('Feature request')}</SelectItem>
                        <SelectItem value="summary">{t('Summary')}</SelectItem>
                    </SelectContent>
                </Select>
            </div>
            <div className="space-y-1.5">
                <Label>{t('Severity')}</Label>
                <Select value={newInsightSeverity} onValueChange={setNewInsightSeverity}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                        <SelectItem value="info">{t('Info')}</SelectItem>
                        <SelectItem value="normal">{t('Normal')}</SelectItem>
                        <SelectItem value="needs_attention">{t('Needs attention')}</SelectItem>
                        <SelectItem value="high">{t('High')}</SelectItem>
                        <SelectItem value="urgent">{t('Urgent')}</SelectItem>
                        <SelectItem value="at_risk">{t('At risk')}</SelectItem>
                    </SelectContent>
                </Select>
            </div>
            <div className="space-y-1.5">
                <Label htmlFor="account-insight-title">{t('Title')}</Label>
                <Input id="account-insight-title" value={newInsightTitle} onChange={event => setNewInsightTitle(event.target.value)} />
            </div>
        </div>
        <div className="space-y-1.5">
            <Label htmlFor="account-insight-body">{t('Body')}</Label>
            <Textarea id="account-insight-body" value={newInsightBody} onChange={event => setNewInsightBody(event.target.value)} rows={4} />
        </div>
        <div className="flex justify-end">
            <Button
                type="button"
                size="sm"
                data-account-add-insight
                onClick={() => void createInsight().then(() => setInsightDialogOpen(false))}
                disabled={savingNewInsight}
            >
                {savingNewInsight ? <Loader className="size-4 animate-spin" /> : <Lightbulb className="size-4" />}
                {t('Add insight')}
            </Button>
        </div>
    </DialogContent>
</Dialog>
```

- [ ] **Step 6: Compact CRM health and move CRM details into a Sheet**

Keep CRM provider label, status badge, latest sync, and `Sync CRM` visible. Replace the inline external records block with:

```tsx
<Button type="button" size="sm" variant="outline" onClick={() => setAccountDetailSheet('crmDetails')} data-account-crm-details-open>
    <Database className="size-3.5" />
    {t('CRM details')}
</Button>
```

Move current CRM health detail, sync result, external record cards, and sync runs into:

```tsx
<Sheet open={accountDetailSheet === 'crmDetails'} onOpenChange={open => setAccountDetailSheet(open ? 'crmDetails' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-account-crm-details-sheet>
        <SheetHeader>
            <SheetTitle>{t('CRM details')}</SheetTitle>
            <SheetDescription>{t('External records, sync runs, and CRM evidence for this account.')}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6" data-account-crm-details-body />
    </SheetContent>
</Sheet>
```

Replace the self-closing `data-account-crm-details-body` marker with the current CRM sync result, external record cards, failed sync detail, and external records section JSX. Keep the compact CRM status strip outside the sheet.

- [ ] **Step 7: Run quality checks after the route edit**

Run:

```bash
cd backend && uv run ruff check automail tests
cd backend && uv run pytest
cd admin && npm run lint
cd admin && npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit Accounts refactor**

Run:

```bash
git add admin/src/routes/Accounts.tsx
git commit -m "refactor: disclose account cockpit workflows"
```

## Task 3: Analytics Tabs And Evidence Sheets

**Files:**
- Modify: `admin/src/routes/Analytics.tsx`
- Test: existing route compile checks and DOM browser checks

- [ ] **Step 1: Add shadcn imports**

Add:

```tsx
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
```

- [ ] **Step 2: Add analytics disclosure state**

Add near the route-local types:

```tsx
type AnalyticsTab = 'overview' | 'channels' | 'accounts' | 'aiOps' | 'raw';
type AnalyticsDetailSheet = 'launchProof' | 'channelRemediation' | 'schemaHealth' | null;
```

Add route-local state after `launchProofRuns`:

```tsx
const [analyticsTab, setAnalyticsTab] = useState<AnalyticsTab>('overview');
const [analyticsDetailSheet, setAnalyticsDetailSheet] = useState<AnalyticsDetailSheet>(null);
```

- [ ] **Step 3: Convert default return body to Tabs**

Wrap the content after the header in:

```tsx
<Tabs value={analyticsTab} onValueChange={value => setAnalyticsTab(value as AnalyticsTab)} data-analytics-tabs>
    <TabsList className="w-full justify-start overflow-x-auto">
        <TabsTrigger value="overview">{t('Overview')}</TabsTrigger>
        <TabsTrigger value="channels">{t('Channels')}</TabsTrigger>
        <TabsTrigger value="accounts">{t('Accounts')}</TabsTrigger>
        <TabsTrigger value="aiOps">{t('AI/Ops')}</TabsTrigger>
        <TabsTrigger value="raw">{t('Raw')}</TabsTrigger>
    </TabsList>
    <TabsContent value="overview" className="space-y-5" data-analytics-overview-tab />
    <TabsContent value="channels" className="space-y-5" data-analytics-channels-tab />
    <TabsContent value="accounts" className="space-y-5" data-analytics-accounts-tab />
    <TabsContent value="aiOps" className="space-y-5" data-analytics-ai-ops-tab />
    <TabsContent value="raw" className="space-y-5" data-analytics-raw-tab />
</Tabs>
```

Replace each self-closing `TabsContent` marker with the JSX from Steps 4 through 8.

- [ ] **Step 4: Build Overview tab as decision dashboard**

Put these pieces in Overview:

```tsx
{summary.launchReadiness && (
    <section className="rounded-md border bg-background p-4" data-analytics-launch-readiness-band>
        <div data-analytics-launch-readiness-body />
    </section>
)}
{summary.launchProof && (
    <section className="rounded-md border bg-background p-4" data-analytics-launch-proof-summary>
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
                {summary.launchProof.status === 'ready'
                    ? <CheckCircle2 className="size-4 text-emerald-600" />
                    : <Rocket className="size-4 text-muted-foreground" />}
                <div>
                    <h2 className="text-sm font-medium">{t('Launch proof')}</h2>
                    <p className="text-xs text-muted-foreground">{t('Evidence, export, and proof run history.')}</p>
                </div>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => setAnalyticsDetailSheet('launchProof')} data-analytics-launch-proof-open>
                <Rocket className="size-3.5" />
                {t('Open proof')}
            </Button>
        </div>
    </section>
)}
<div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4" data-analytics-support-actions>
    <div data-analytics-support-actions-body />
</div>
<section className="space-y-3" data-analytics-support-workload-band>
    <div data-analytics-support-workload-body />
</section>
<section className="space-y-3" data-analytics-sla-band>
    <div data-analytics-sla-body />
</section>
```

Replace the four body markers with the existing Launch readiness body, selected `QueueAction` cards, Support workload section body, and SLA performance section body.

- [ ] **Step 5: Build Channels tab**

Put channel remediation summary and channel/provider metrics here:

```tsx
<section className="rounded-md border bg-background p-4" data-analytics-channel-remediation-summary>
    <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
            <AlertTriangle className="size-4 text-muted-foreground" />
            <div>
                <h2 className="text-sm font-medium">{t('Channel remediation')}</h2>
                <p className="text-xs text-muted-foreground">{t('Provider setup, smoke, delivery, and webhook issues.')}</p>
            </div>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={() => setAnalyticsDetailSheet('channelRemediation')} data-analytics-channel-remediation-open>
            <ExternalLink className="size-3.5" />
            {t('Open remediation')}
        </Button>
    </div>
</section>
<div className="grid gap-3 sm:grid-cols-2">
    <Metric label={t('Channels')} value={summary.channels} icon={BarChart3} />
    <Metric label={t('Active channels')} value={summary.activeChannels} icon={CheckCircle2} />
    <Metric label={t('Channel backlog')} value={summary.channelBacklogSurfaces} icon={AlertTriangle} />
    <Metric label={t('Every-message ticketing')} value={Math.max(summary.activeChannels - summary.activeChannelsWrongTicketMode, 0)} icon={CheckCircle2} />
    <Metric label={t('Wrong ticket mode')} value={summary.activeChannelsWrongTicketMode} icon={AlertTriangle} />
    <Metric label={t('Smoke passed')} value={summary.activeChannelsWithSmoke} icon={CheckCircle2} />
    <Metric label={t('Smoke missing')} value={summary.activeChannelsMissingSmoke} icon={AlertTriangle} />
    <Metric label={t('Outbound smoke passed')} value={summary.activeChannelsWithOutboundSmoke} icon={CheckCircle2} />
    <Metric label={t('Outbound smoke missing')} value={summary.activeChannelsMissingOutboundSmoke} icon={AlertTriangle} />
</div>
```

Move the email, web chat, delivery, and webhook metric groups currently near the bottom of the route into this tab.

- [ ] **Step 6: Build Accounts tab**

Put account and CRM metrics here:

```tsx
<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-analytics-account-metrics>
    <Metric label={t('Accounts')} value={summary.accounts} icon={Building2} />
    <Metric label={t('Account insights')} value={summary.accountInsights} icon={Building2} />
    <Metric label={t('Account actions')} value={summary.accountsNeedingAction} icon={Building2} />
    <Metric label={t('Open account risks')} value={summary.openAccountRisks} icon={AlertTriangle} />
    <Metric label={t('Feature requests')} value={summary.featureRequests} icon={BookOpen} />
</div>
<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-analytics-crm-metrics>
    <Metric label={t('External objects')} value={summary.externalObjects} icon={Building2} />
    <Metric label={t('External sync runs')} value={summary.externalSyncRuns} icon={BarChart3} />
    <Metric label={t('Failed external sync runs')} value={summary.failedExternalSyncRuns} icon={AlertTriangle} />
    <Metric label={t('CRM connectors')} value={summary.crmConnectors} icon={Building2} />
    <Metric label={t('Active CRM connectors')} value={summary.activeCrmConnectors} icon={Building2} />
    <Metric label={t('CRM sync runs')} value={summary.crmSyncRuns} icon={BarChart3} />
    <Metric label={t('Failed CRM sync runs')} value={summary.failedCrmSyncRuns} icon={AlertTriangle} />
    <Metric label={t('Failed CRM webhook events')} value={summary.failedCrmWebhookEvents} icon={AlertTriangle} />
</div>
```

- [ ] **Step 7: Build AI/Ops tab**

Put schema health access, support health insights, knowledge, AI, action, automation, and workflow metrics here:

```tsx
{schemaHealth && (
    <section className="rounded-md border bg-background p-4" data-analytics-schema-health-summary>
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
                {schemaHealth.ready ? <CheckCircle2 className="size-4 text-emerald-600" /> : <Database className="size-4 text-destructive" />}
                <div>
                    <h2 className="text-sm font-medium">{t('Schema health')}</h2>
                    <p className="text-xs text-muted-foreground">{t('Collections, fields, and migration readiness.')}</p>
                </div>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => setAnalyticsDetailSheet('schemaHealth')} data-analytics-schema-health-open>
                <Database className="size-3.5" />
                {t('Details')}
            </Button>
        </div>
    </section>
)}
<SupportHealthInsights items={summary.supportHealthInsights} onOpen={openRoute} t={t} />
<div className="grid gap-3 sm:grid-cols-2">
    <Metric label={t('Knowledge gaps')} value={summary.knowledgeGaps} icon={BookOpen} />
    <Metric label={t('Open knowledge gaps')} value={summary.openKnowledgeGaps} icon={AlertTriangle} />
    <Metric label={t('AI runs')} value={summary.aiRuns} icon={BarChart3} />
    <Metric label={t('AI needs human')} value={summary.aiRunsNeedingHuman} icon={AlertTriangle} />
    <Metric label={t('Action executions')} value={summary.actionExecutions} icon={BarChart3} />
    <Metric label={t('Successful actions')} value={summary.successfulActionExecutions} icon={BarChart3} />
</div>
```

Move automation and workflow metric groups currently near the bottom of the route into this tab.

- [ ] **Step 8: Build Raw tab**

Put remaining dense counters and CountList blocks here:

```tsx
<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-analytics-raw-ticket-metrics>
    <Metric label={t('Total issues')} value={summary.totalIssues} icon={InboxIcon} />
    <Metric label={t('Open issues')} value={summary.openIssues} icon={BarChart3} />
    <Metric label={t('Ongoing issues')} value={summary.ongoingIssues} icon={BarChart3} />
    <Metric label={t('Done issues')} value={summary.doneIssues} icon={BarChart3} />
</div>
<div className="grid gap-3 lg:grid-cols-2">
    <CountList title={t('Status')} counts={summary.statusCounts} />
    <CountList title={t('Priority')} counts={summary.priorityCounts} />
</div>
<div className="grid gap-3 lg:grid-cols-3">
    <CountList title={t('Channels')} counts={summary.channelCounts} />
    <CountList title={t('Queues')} counts={summary.queueCounts} />
    <CountList title={t('Assignees')} counts={summary.assigneeCounts} />
</div>
```

- [ ] **Step 9: Move evidence panels into Sheets**

Add:

```tsx
<Sheet open={analyticsDetailSheet === 'launchProof'} onOpenChange={open => setAnalyticsDetailSheet(open ? 'launchProof' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-5xl" data-analytics-launch-proof-sheet>
        <SheetHeader>
            <SheetTitle>{t('Launch proof')}</SheetTitle>
            <SheetDescription>{t('Evidence, export, provider state, and proof run history.')}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
            {summary.launchProof && (
                <LaunchProofPanel
                    projectId={projectId}
                    launchProof={summary.launchProof}
                    latestRun={latestLaunchProofRun}
                    runHistory={launchProofRunHistory}
                    onOpen={openRoute}
                    onRunProof={runLaunchProof}
                    proofRunning={runningLaunchProof}
                    t={t}
                />
            )}
        </div>
    </SheetContent>
</Sheet>
<Sheet open={analyticsDetailSheet === 'channelRemediation'} onOpenChange={open => setAnalyticsDetailSheet(open ? 'channelRemediation' : null)}>
    <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-analytics-channel-remediation-sheet>
        <SheetHeader>
            <SheetTitle>{t('Channel remediation')}</SheetTitle>
            <SheetDescription>{t('Actionable provider setup and delivery issues.')}</SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
            <ChannelRemediationPanel items={summary.latestChannelRemediations} onOpen={openRoute} t={t} />
        </div>
    </SheetContent>
</Sheet>
{schemaHealth && (
    <Sheet open={analyticsDetailSheet === 'schemaHealth'} onOpenChange={open => setAnalyticsDetailSheet(open ? 'schemaHealth' : null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-4xl" data-analytics-schema-health-sheet>
            <SheetHeader>
                <SheetTitle>{t('Schema health')}</SheetTitle>
                <SheetDescription>{t('Support collections, fields, and migrations.')}</SheetDescription>
            </SheetHeader>
            <div className="px-4 pb-6">
                <SchemaHealthPanel schemaHealth={schemaHealth} t={t} />
            </div>
        </SheetContent>
    </Sheet>
)}
```

- [ ] **Step 10: Run quality checks after the route edit**

Run:

```bash
cd backend && uv run ruff check automail tests
cd backend && uv run pytest
cd admin && npm run lint
cd admin && npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 11: Commit Analytics refactor**

Run:

```bash
git add admin/src/routes/Analytics.tsx
git commit -m "refactor: organize analytics diagnostics"
```

## Task 4: DOM Browser Verification

**Files:**
- Verify: live or local admin app in browser
- No source modifications unless verification finds a bug

- [ ] **Step 1: Start local admin if no suitable server is running**

Run:

```bash
cd admin && npm run dev
```

Expected: Vite serves the admin on port `5174` unless that port is busy.

- [ ] **Step 2: Verify Channel setup with cmux browser DOM only**

Open the Channel setup route. Do not use screenshots or vision. Query text, headings, buttons, and data attributes from DOM.

Required DOM evidence:

```text
data-channel-advanced-checks-open exists
data-channel-advanced-checks-dialog appears after clicking Advanced checks
data-channel-launch-details-open exists
data-channel-launch-details-sheet appears after clicking Launch details
data-channel-diagnostics-summary exists
Current cursors, Sync history, Webhook inbox, Delivery history, and CRM connectors are not all visible as top-level sections at initial page load
```

- [ ] **Step 3: Verify Accounts with cmux browser DOM only**

Open an account detail route. Do not use screenshots or vision.

Required DOM evidence:

```text
data-account-add-insight-dialog appears after clicking Risk or Feature request
data-account-crm-details-sheet appears after clicking CRM details
data-account-action-queue-sheet appears after clicking Action queue
External records are not a top-level section at initial account detail load
Recent issues remains visible
Prepare action remains visible
```

- [ ] **Step 4: Verify Analytics with cmux browser DOM only**

Open Analytics. Do not use screenshots or vision.

Required DOM evidence:

```text
data-analytics-tabs exists
Overview, Channels, Accounts, AI/Ops, and Raw tabs exist
data-analytics-launch-proof-sheet appears after clicking Open proof
data-analytics-channel-remediation-sheet appears after clicking Open remediation
Raw counters appear only after selecting Raw
Overview includes Launch readiness, Support workload, and SLA/customer outcome metrics
```

- [ ] **Step 5: Run final quality gate**

Run:

```bash
cd backend && uv run ruff check automail tests
cd backend && uv run pytest
cd admin && npm run lint
cd admin && npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 6: Final commit if verification required fixes**

If browser verification produced fixes, commit them:

```bash
git add admin/src/routes/Channels.tsx admin/src/routes/Accounts.tsx admin/src/routes/Analytics.tsx
git commit -m "fix: polish admin disclosure flows"
```

If no fixes were needed, do not create an empty commit.

## Self-Review Notes

- Spec coverage: Channel setup, Accounts, Analytics, Dialog, Sheet, Tabs, DOM verification, and quality gates are covered.
- Scope: UI-only. No backend, channel provider, ticket model, or API migration work.
- Type consistency: disclosure state names are route-local and do not cross file boundaries.
- Verification: backend Ruff, backend pytest, admin ESLint, admin TypeScript/build, and cmux browser DOM checks are required before reporting complete.
