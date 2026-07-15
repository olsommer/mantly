import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { ColumnDef, SortingState } from '@tanstack/react-table';
import {
    flexRender,
    getCoreRowModel,
    getFilteredRowModel,
    getPaginationRowModel,
    getSortedRowModel,
    useReactTable,
} from '@tanstack/react-table';
import { Activity, AlertCircle, ArrowUpDown, Clock, Eye, Loader, MessageSquare, MousePointerClick, UserRound } from 'lucide-react';
import { Line, LineChart } from 'recharts';

import { api } from '@/api/endpoints';
import type { MonitorRun, MonitorSummary } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ChartContainer } from '@/components/ui/chart';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { useI18n } from '@/lib/i18n-context';

interface MonitorProps {
    projectId: string;
    isDemoAccount?: boolean;
}

interface TokenUsage {
    input: number | null;
    output: number | null;
    cached: number | null;
}

interface MonitorRow {
    id: string;
    status: string;
    timestamp: string;
    timestampMs: number;
    emailDescription: string;
    emailText: string;
    intent: string;
    tools: string[];
    actions: string[];
    isActionRun: boolean;
    responseText: string;
    durationMs: number;
    tokens: TokenUsage | null;
    feedbackCount: number;
    feedbackRating: string;
    searchText: string;
}

interface MetricCardData {
    label: string;
    value: number | string;
    icon: typeof Activity;
    series: Array<{ index: number; value: number }>;
}

const statusDotClass: Record<string, string> = {
    success: 'bg-emerald-500',
    failed: 'bg-red-500',
    running: 'bg-amber-500',
    preview: 'bg-amber-500',
    needs_human: 'bg-amber-500',
};

function fmtDuration(ms: number) {
    if (!ms) return '-';
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
}

function fmtTime(value: string) {
    if (!value) return '-';
    try {
        return new Intl.DateTimeFormat(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(value));
    } catch {
        return value;
    }
}

function textFrom(value: unknown) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
}

function numberFrom(value: unknown) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function recordFrom(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayFrom(value: unknown): Record<string, unknown>[] {
    return Array.isArray(value) ? value.map(recordFrom) : [];
}

function formatNumber(value: number | null) {
    return value === null ? '-' : value.toLocaleString();
}

function dayKey(timestamp: number) {
    return new Date(timestamp).toISOString().slice(0, 10);
}

function buildTrend(runs: MonitorRun[], valueForRun: (run: MonitorRun) => number) {
    const days = Array.from({ length: 7 }, (_, index) => {
        const date = new Date();
        date.setHours(0, 0, 0, 0);
        date.setDate(date.getDate() - (6 - index));
        return dayKey(date.getTime());
    });
    const totals = new Map(days.map((day) => [day, 0]));
    for (const run of runs) {
        const timestamp = Date.parse(run.startedAt || run.created || '');
        if (!Number.isFinite(timestamp)) continue;
        const key = dayKey(timestamp);
        if (!totals.has(key)) continue;
        totals.set(key, (totals.get(key) ?? 0) + valueForRun(run));
    }
    return days.map((day, index) => ({ index, value: totals.get(day) ?? 0 }));
}

function MetricSparkline({ data }: { data: Array<{ index: number; value: number }> }) {
    return (
        <ChartContainer
            config={{ value: { color: 'var(--chart-2)' } }}
            className="h-12 w-24 shrink-0"
        >
            <LineChart accessibilityLayer data={data} margin={{ left: 2, right: 2, top: 6, bottom: 6 }}>
                <Line
                    dataKey="value"
                    type="monotone"
                    stroke="var(--color-value)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                />
            </LineChart>
        </ChartContainer>
    );
}

function getTokenUsage(output: Record<string, unknown>): TokenUsage | null {
    const summary = recordFrom(output.summary);
    const usage = recordFrom(output.tokenUsage);
    const nestedUsage = recordFrom(summary.tokenUsage);
    const effectiveUsage = Object.keys(usage).length ? usage : nestedUsage;
    if (!Object.keys(effectiveUsage).length) return null;
    return {
        input: numberFrom(effectiveUsage.inputTokens),
        output: numberFrom(effectiveUsage.outputTokens),
        cached: numberFrom(effectiveUsage.cachedInputTokens),
    };
}

function getIntent(output: Record<string, unknown>) {
    const intentResult = recordFrom(output.intentResult);
    return textFrom(output.activatedIntent) || textFrom(intentResult.intentName) || '-';
}

function getTools(output: Record<string, unknown>) {
    const explicit = arrayFrom(output.toolsUsed);
    if (explicit.length > 0) return explicit;

    const identity = recordFrom(output.identityResult);
    const calls = Array.isArray(identity.toolCallsMade) ? identity.toolCallsMade : [];
    return calls.map((name) => ({ name: textFrom(name), status: 'success' }));
}

function labelList(items: Record<string, unknown>[], fallback: string) {
    if (!items.length) return [];
    return items
        .map((item) => {
            const label = textFrom(item.label) || textFrom(item.name) || textFrom(item.type) || fallback;
            const count = numberFrom(item.count);
            return count && count > 1 ? `${label} x${count}` : label;
        })
        .filter(Boolean);
}

function DetailDialog({
    title,
    description,
    triggerLabel,
    children,
}: {
    title: string;
    description?: string;
    triggerLabel: string;
    children: ReactNode;
}) {
    return (
        <Dialog>
            <DialogTrigger asChild>
                <Button variant="outline" size="xs" className="h-6 px-2 text-xs">
                    <Eye className="size-3" /> {triggerLabel}
                </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[82vh] max-w-2xl overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    {description && <DialogDescription>{description}</DialogDescription>}
                </DialogHeader>
                {children}
            </DialogContent>
        </Dialog>
    );
}

function TextBlock({ value }: { value: string }) {
    return (
        <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-sm leading-relaxed">
            {value || '-'}
        </pre>
    );
}

function TagList({ items, variant = 'outline' }: { items: string[]; variant?: 'outline' | 'secondary' }) {
    if (!items.length) return <span className="text-muted-foreground/60">-</span>;
    return (
        <div className="flex max-w-[240px] flex-wrap gap-1">
            {items.slice(0, 3).map((item, idx) => (
                <Badge key={`${item}-${idx}`} variant={variant} className="max-w-full truncate font-normal">
                    {item}
                </Badge>
            ))}
        </div>
    );
}

function SortHeader({ label, column }: { label: string; column: { toggleSorting: (desc?: boolean) => void; getIsSorted: () => false | 'asc' | 'desc' } }) {
    const sorted = column.getIsSorted();
    return (
        <Button
            variant="ghost"
            size="xs"
            className="h-7 w-full justify-start px-1 text-left text-xs font-medium text-muted-foreground"
            onClick={() => column.toggleSorting(sorted === 'asc')}
        >
            {label}
            <ArrowUpDown className="size-3" />
        </Button>
    );
}

function toMonitorRow(run: MonitorRun): MonitorRow {
    const input = run.input || {};
    const output = run.output || {};
    const subject = textFrom(input.subject);
    const sender = textFrom(input.from);
    const body = textFrom(input.body);
    const responseText = textFrom(output.responseText) || textFrom(output.response) || run.error;
    const intent = getIntent(output);
    const tools = labelList(getTools(output), 'Tool');
    const actions = labelList(run.actions, run.source === 'action' ? 'Executed action' : 'Action');
    const feedback = recordFrom(run.feedback);
    const feedbackCount = numberFrom(feedback.count) ?? 0;
    const feedbackRating = textFrom(feedback.latestRating);
    const timestampMs = Date.parse(run.startedAt || run.created || '') || 0;
    const emailText = [
        subject ? `Subject: ${subject}` : '',
        sender ? `From: ${sender}` : '',
        body,
    ].filter(Boolean).join('\n');

    return {
        id: run.id,
        status: run.status,
        timestamp: fmtTime(run.startedAt),
        timestampMs,
        emailDescription: subject || sender || run.id,
        emailText,
        intent,
        tools,
        actions,
        isActionRun: run.source === 'action',
        responseText,
        durationMs: run.durationMs,
        tokens: getTokenUsage(output),
        feedbackCount,
        feedbackRating,
        searchText: [
            run.status,
            subject,
            sender,
            body,
            intent,
            tools.join(' '),
            actions.join(' '),
            responseText,
            feedbackRating,
        ].join(' ').toLowerCase(),
    };
}

function createColumns(t: (key: string) => string): ColumnDef<MonitorRow>[] {
    return [
    {
        accessorKey: 'status',
        header: ({ column }) => <SortHeader label={t('Status')} column={column} />,
        cell: ({ row }) => (
            <span
                role="img"
                aria-label={row.original.status.replace('_', ' ')}
                title={row.original.status.replace('_', ' ')}
                className={`inline-block size-2.5 rounded-full ${statusDotClass[row.original.status] ?? 'bg-muted-foreground/50'}`}
            />
        ),
    },
    {
        accessorKey: 'timestampMs',
        header: ({ column }) => <SortHeader label={t('Timestamp')} column={column} />,
        cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.timestamp}</span>,
    },
    {
        id: 'email',
        header: t('Email'),
        cell: ({ row }) => (
            <DetailDialog title={t('Email input')} description={row.original.emailDescription} triggerLabel={t('Show')}>
                <TextBlock value={row.original.emailText} />
            </DetailDialog>
        ),
    },
    {
        accessorKey: 'intent',
        header: ({ column }) => <SortHeader label={t('Intent')} column={column} />,
        cell: ({ row }) => row.original.intent && row.original.intent !== '-' ? (
            <TagList items={[row.original.intent]} />
        ) : (
            <span className="text-muted-foreground/60">-</span>
        ),
    },
    {
        accessorKey: 'tools',
        header: t('Tools used'),
        cell: ({ row }) => <TagList items={row.original.tools} />,
        filterFn: 'auto',
    },
    {
        accessorKey: 'actions',
        header: t('Actions'),
        cell: ({ row }) => <TagList items={row.original.actions} variant={row.original.isActionRun ? 'secondary' : 'outline'} />,
    },
    {
        id: 'response',
        header: t('Response'),
        cell: ({ row }) => row.original.responseText ? (
            <DetailDialog title={t('Response')} description={row.original.id} triggerLabel={t('Show')}>
                <TextBlock value={row.original.responseText} />
            </DetailDialog>
        ) : (
            <span className="text-muted-foreground/60">-</span>
        ),
    },
    {
        accessorKey: 'durationMs',
        header: ({ column }) => <SortHeader label={t('Time')} column={column} />,
        cell: ({ row }) => fmtDuration(row.original.durationMs),
    },
    {
        accessorFn: row => row.tokens?.input ?? null,
        id: 'tokenInput',
        header: ({ column }) => <SortHeader label={t('Tok. In')} column={column} />,
        cell: ({ row }) => formatNumber(row.original.tokens?.input ?? null),
    },
    {
        accessorFn: row => row.tokens?.output ?? null,
        id: 'tokenOutput',
        header: ({ column }) => <SortHeader label={t('Tok. Out')} column={column} />,
        cell: ({ row }) => formatNumber(row.original.tokens?.output ?? null),
    },
    {
        accessorFn: row => row.tokens?.cached ?? null,
        id: 'tokenCached',
        header: ({ column }) => <SortHeader label={t('Tok. Cached')} column={column} />,
        cell: ({ row }) => formatNumber(row.original.tokens?.cached ?? null),
    },
    {
        accessorKey: 'feedbackCount',
        header: ({ column }) => <SortHeader label={t('Feedback')} column={column} />,
        cell: ({ row }) => row.original.feedbackCount > 0 ? (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <MessageSquare className="size-3" />
                {row.original.feedbackCount} · {row.original.feedbackRating || t('submitted')}
            </div>
        ) : (
            <span className="text-muted-foreground/60">-</span>
        ),
    },
    ];
}

function RunsDataTable({ runs }: { runs: MonitorRun[] }) {
    const [sorting, setSorting] = useState<SortingState>([{ id: 'timestampMs', desc: true }]);
    const [globalFilter, setGlobalFilter] = useState('');
    const { t } = useI18n();
    const data = useMemo(() => runs.map(toMonitorRow), [runs]);
    const columns = useMemo(() => createColumns(t), [t]);
    // eslint-disable-next-line react-hooks/incompatible-library
    const table = useReactTable({
        data,
        columns,
        state: { sorting, globalFilter },
        onSortingChange: setSorting,
        onGlobalFilterChange: setGlobalFilter,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        getFilteredRowModel: getFilteredRowModel(),
        getPaginationRowModel: getPaginationRowModel(),
        globalFilterFn: (row, _columnId, filterValue) => {
            const query = String(filterValue || '').trim().toLowerCase();
            return !query || row.original.searchText.includes(query);
        },
        initialState: { pagination: { pageSize: 10 } },
    });

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden">
            <div className="flex min-w-0 shrink-0 items-center justify-between gap-3">
                <Input
                    value={globalFilter}
                    onChange={(event) => setGlobalFilter(event.target.value)}
                    placeholder={t('Filter runs...')}
                    className="max-w-sm"
                />
                <div className="text-xs text-muted-foreground">
                    {t('{count} {unit}', {
                        count: table.getFilteredRowModel().rows.length,
                        unit: table.getFilteredRowModel().rows.length === 1 ? t('run') : t('runs'),
                    })}
                </div>
            </div>

            <div className="min-h-0 min-w-0 max-w-full flex-1 overflow-auto rounded-md border">
                <Table className="min-w-[1280px]">
                    <TableHeader>
                        {table.getHeaderGroups().map((headerGroup) => (
                            <TableRow key={headerGroup.id} className="bg-muted/40 hover:bg-muted/40">
                                {headerGroup.headers.map((header) => (
                                    <TableHead key={header.id} className="sticky top-0 z-10 bg-muted/40 text-xs font-medium">
                                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                                    </TableHead>
                                ))}
                            </TableRow>
                        ))}
                    </TableHeader>
                    <TableBody>
                        {table.getRowModel().rows.length ? (
                            table.getRowModel().rows.map((row) => (
                                <TableRow key={row.id}>
                                    {row.getVisibleCells().map((cell) => (
                                        <TableCell key={cell.id}>
                                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                        </TableCell>
                                    ))}
                                </TableRow>
                            ))
                        ) : (
                            <TableRow>
                                <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                                    {t('No runs found.')}
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="flex shrink-0 items-center justify-between gap-3">
                <div className="text-xs text-muted-foreground">
                    {t('Page {page} of {total}', {
                        page: table.getState().pagination.pageIndex + 1,
                        total: table.getPageCount() || 1,
                    })}
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => table.previousPage()}
                        disabled={!table.getCanPreviousPage()}
                    >
                        {t('Previous')}
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => table.nextPage()}
                        disabled={!table.getCanNextPage()}
                    >
                        {t('Next')}
                    </Button>
                </div>
            </div>
        </div>
    );
}

export function Monitor({ projectId, isDemoAccount = false }: MonitorProps) {
    const [summary, setSummary] = useState<MonitorSummary | null>(null);
    const [runs, setRuns] = useState<MonitorRun[]>([]);
    const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
    const { t } = useI18n();

    useEffect(() => {
        let cancelled = false;
        void Promise.all([
            api.getMonitorSummary(projectId),
            api.getMonitorRuns(projectId, 50),
        ]).then(([summaryRes, runsRes]) => {
            if (cancelled) return;
            if (summaryRes.data) setSummary(summaryRes.data);
            if (runsRes.data) setRuns(runsRes.data.items);
            setLoadedProjectId(projectId);
        }).finally(() => {
            if (!cancelled) setLoadedProjectId(projectId);
        });
        return () => { cancelled = true; };
    }, [projectId]);

    const loading = loadedProjectId !== projectId;

    if (loading) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center text-muted-foreground">
                <Loader className="mr-2 size-4 animate-spin" />
                {t('Loading monitor')}
            </div>
        );
    }

    const metrics: MetricCardData[] = [
        {
            label: t('Requests today'),
            value: summary?.requestsToday ?? 0,
            icon: Activity,
            series: buildTrend(runs, () => 1),
        },
        {
            label: t('Failures'),
            value: summary?.failures ?? 0,
            icon: AlertCircle,
            series: buildTrend(runs, (run) => run.status === 'failed' ? 1 : 0),
        },
        {
            label: t('Avg processing'),
            value: fmtDuration(summary?.avgDurationMs ?? 0),
            icon: Clock,
            series: buildTrend(runs, (run) => run.durationMs || 0),
        },
        {
            label: t('p95 processing'),
            value: fmtDuration(summary?.p95DurationMs ?? 0),
            icon: Clock,
            series: buildTrend(runs, (run) => run.durationMs || 0),
        },
        {
            label: t('Needs human'),
            value: summary?.needsHuman ?? 0,
            icon: UserRound,
            series: buildTrend(runs, (run) => recordFrom(run.output).requiresHuman ? 1 : 0),
        },
        {
            label: t('Actions executed'),
            value: summary?.actionsTriggered ?? 0,
            icon: MousePointerClick,
            series: buildTrend(runs, (run) => run.source === 'action' ? 1 : 0),
        },
    ];

    return (
        <div className="flex h-full min-h-0 min-w-0 w-full flex-col gap-5 overflow-hidden">
            {isDemoAccount && (
                <Card className="shrink-0 border-primary/20 bg-primary/5">
                    <CardContent className="p-4 text-sm text-muted-foreground">
                        {t('Demo preview runs are tracked here as monitor data so you can inspect the same run history a real workspace would see.')}
                    </CardContent>
                </Card>
            )}

            <div className="grid shrink-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {metrics.map((metric) => (
                    <Card key={metric.label}>
                        <CardContent className="flex items-center justify-between gap-3 p-4">
                            <div>
                                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <metric.icon className="size-3.5" />
                                    {metric.label}
                                </div>
                                <div className="mt-1 text-2xl font-semibold">{metric.value}</div>
                            </div>
                            <MetricSparkline data={metric.series} />
                        </CardContent>
                    </Card>
                ))}
            </div>

            <RunsDataTable runs={runs} />
        </div>
    );
}
