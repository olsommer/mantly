import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { parse as parseYaml } from 'yaml';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemHeader, ItemMedia, ItemTitle } from '@/components/ui/item';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import {
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { AlertCircle, ArrowRight, Loader, Plus, Trash2, Save, X, Upload, Paperclip, ChevronRight, GripVertical, Pencil, Lightbulb, MessageSquare, Check } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/api/endpoints';
import type { EvalSet, IntentFileInfo, IntentLearningProposal } from '@/api/endpoints';
import type { UserRole } from '@/components/app-sidebar';
import { IntentLearningProposals } from '@/components/intent-learning-proposals';
import { useTopBar } from '@/TopBarContext';
import { HintBanner } from '@/components/hint-banner';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/i18n-context';
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
    type DragEndEvent,
} from '@dnd-kit/core';
import {
    arrayMove,
    SortableContext,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

// ── Types ─────────────────────────────────────────────────────────────────────

interface IntentSummary {
    name: string;
    description: string;
    actions: unknown[];
    response: unknown;
    active: boolean;
    requireReview: boolean;
}

interface ResponseAttachmentMeta {
    filename: string;
    description: string;
    mode: 'always' | 'dynamic';
}

interface ResponseConfig {
    enabled: boolean;              // legacy file field; reply generation now belongs to Inbox
    responseRules: string;
    requiredGuidance: string;
    responseTrigger: 'auto' | 'button'; // legacy file field kept for lossless editing
    attachments: ResponseAttachmentMeta[];
    useFeedbackLearnings: boolean;
}

interface ActionRow {
    type: 'dropdown' | 'calendar' | 'input' | 'button';
    id: string;                    // stable id for dnd-kit (auto-generated)
    name: string;
    label: string;
    description: string;           // tool schema description
    options: string;               // comma-separated; only for dropdown
    separateCall: boolean;         // only meaningful for non-button types
    webhook: string;               // required for button; required when separateCall=true
    method: 'GET' | 'POST';
    headers: KVPair[];             // key-value pairs for HTTP headers
    query: KVPair[];               // mapped query params for webhook calls
    body: KVPair[];                // mapped JSON body for webhook calls
}

interface KVPair { key: string; value: string; }

interface IntentToolInputField {
    key: string;
    description: string;
    type: 'string' | 'number' | 'integer' | 'boolean';
    default?: string;
    required: boolean;
}

interface IntentToolRow {
    name: string;
    description: string;
    method: 'GET' | 'POST';
    urlTemplate: string;
    headers: KVPair[];
    body: KVPair[];
    inputSchema: IntentToolInputField[];
    expectsFile: boolean;
    attachToResponse: boolean;
    fileNamePath: string;
    fileContentTypePath: string;
    fileContentBase64Path: string;
}

interface IntentForm {
    name: string;
    description: string;
    active: boolean;
    requireReview: boolean;
    instructions: string;          // INTENT.md body (markdown)
    actions: ActionRow[];
    response: ResponseConfig;
    tools: IntentToolRow[];        // HTTP tools for intent processing stage
}

type View = 'list' | 'edit' | 'new';

interface IntentLearning {
    id: string;
    learning: string;
    source_feedback_id: string;
    affected_stages: string[];
    created: string;
}

interface IntentFeedback {
    id: string;
    rating: string;
    affected_stages: string[];
    feedback_text: string;
    user_email: string;
    created: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

let _nextId = 1;
function nextId(): string { return `action-${_nextId++}`; }

// ── Parse / Serialize ─────────────────────────────────────────────────────────

const FRONTMATTER_RE = /^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string {
    if (value == null) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return String(value);
    try {
        return JSON.stringify(value) ?? '';
    } catch {
        return '';
    }
}

function asBool(value: unknown, fallback: boolean): boolean {
    if (typeof value === 'boolean') return value;
    if (value == null || value === '') return fallback;
    return asString(value).trim().toLowerCase() !== 'false';
}

function asRecords(value: unknown): Record<string, unknown>[] {
    return Array.isArray(value) ? value.filter(isRecord) : [];
}

function stringList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map(item => asString(item).trim()).filter(Boolean);
    }
    const text = asString(value).trim();
    return text ? [text] : [];
}

function rowsFromMap(value: unknown): KVPair[] {
    if (Array.isArray(value)) {
        return value.filter(isRecord).map(row => ({
            key: asString(row.key).trim(),
            value: asString(row.value),
        })).filter(row => row.key);
    }
    if (!isRecord(value)) return [];
    return Object.entries(value).map(([key, val]) => ({
        key,
        value: typeof val === 'string' ? val : JSON.stringify(val),
    }));
}

function parseAttachments(value: unknown): ResponseAttachmentMeta[] {
    return asRecords(value).map<ResponseAttachmentMeta>(item => {
        const mode = asString(item.mode);
        return {
            filename: asString(item.filename),
            description: asString(item.description),
            mode: mode === 'dynamic' ? 'dynamic' : 'always',
        };
    }).filter(item => item.filename);
}

function parseResponseConfig(value: unknown): ResponseConfig {
    const response = isRecord(value) ? value : {};
    const auto = asBool(response.auto, true);
    return {
        enabled: asBool(response.enabled, false),
        responseRules: stringList(response.response_rules ?? response.responseRules).join('\n'),
        requiredGuidance: stringList(response.required_guidance ?? response.requiredGuidance).join('\n'),
        responseTrigger: auto ? 'auto' : 'button',
        attachments: parseAttachments(response.attachments),
        useFeedbackLearnings: asBool(response.use_feedback_learnings ?? response.useFeedbackLearnings, true),
    };
}

function parseYamlIntentMd(frontmatter: string, body: string): IntentForm | null {
    let fm: unknown;
    try {
        fm = parseYaml(frontmatter);
    } catch {
        return null;
    }
    if (!isRecord(fm)) return null;

    const actions: ActionRow[] = [];

    for (const raw of asRecords(fm.actions)) {
        const rawType = asString(raw.type);
        const name = asString(raw.name);
        if (!name) continue;
        const type = (['dropdown', 'calendar', 'input', 'button'].includes(rawType) ? rawType : 'button') as ActionRow['type'];
        const separateRaw = raw.separate_call ?? raw.separateCall;
        actions.push({
            type,
            id: nextId(),
            name,
            label: asString(raw.label),
            description: asString(raw.description),
            options: stringList(raw.options).join(', '),
            separateCall: separateRaw == null ? type !== 'button' : asBool(separateRaw, type !== 'button'),
            webhook: asString(raw.webhook),
            method: asString(raw.method).toUpperCase() === 'GET' ? 'GET' : 'POST',
            headers: rowsFromMap(raw.headers),
            query: rowsFromMap(raw.query),
            body: rowsFromMap(raw.body),
        });
    }

    const tools: IntentToolRow[] = asRecords(fm.tools).map(raw => {
        const file = isRecord(raw.file) ? raw.file : {};
        const method: IntentToolRow['method'] = asString(raw.method).toUpperCase() === 'POST' ? 'POST' : 'GET';
        return {
            name: asString(raw.name),
            description: asString(raw.description),
            method,
            urlTemplate: asString(raw.urlTemplate ?? raw.url_template),
            headers: rowsFromMap(raw.headers),
            body: rowsFromMap(raw.body),
            inputSchema: asRecords(raw.inputSchema ?? raw.input_schema).map(field => ({
                key: asString(field.key),
                description: asString(field.description),
                type: (['string', 'number', 'integer', 'boolean'].includes(asString(field.type)) ? asString(field.type) : 'string') as IntentToolInputField['type'],
                default: asString(field.default),
                required: asBool(field.required, true),
            })).filter(field => field.key),
            expectsFile: asBool(file.expectsFile ?? file.expects_file ?? raw.expectsFile ?? raw.expects_file, false),
            attachToResponse: asBool(file.attachToResponse ?? file.attach_to_response ?? raw.attachToResponse ?? raw.attach_to_response, true),
            fileNamePath: asString(file.filenamePath ?? file.filename_path ?? raw.filenamePath ?? raw.filename_path),
            fileContentTypePath: asString(file.contentTypePath ?? file.content_type_path ?? raw.contentTypePath ?? raw.content_type_path),
            fileContentBase64Path: asString(file.contentBase64Path ?? file.content_base64_path ?? raw.contentBase64Path ?? raw.content_base64_path),
        };
    }).filter(tool => tool.name);

    return {
        name: asString(fm.name),
        description: asString(fm.description),
        active: asBool(fm.active, true),
        requireReview: asBool(fm.require_review ?? fm.requireReview, false),
        instructions: body,
        actions,
        response: parseResponseConfig(fm.response),
        tools,
    };
}

function parseIntentMd(raw: string): IntentForm {
    const match = raw.match(FRONTMATTER_RE);
    if (!match) {
        return {
            name: '',
            description: '',
            active: true,
            requireReview: false,
            instructions: raw.trim(),
            actions: [],
            response: { ...DEFAULT_RESPONSE_CONFIG },
            tools: [],
        };
    }

    const fm = match[1];
    const body = match[2].trim();
    const parsed = parseYamlIntentMd(fm, body);
    if (parsed) return parsed;

    const getScalar = (key: string): string => {
        const m = fm.match(new RegExp(`^${key}:\\s*(.+)$`, 'm'));
        return m ? m[1].trim().replace(/^["']|["']$/g, '') : '';
    };

    const activeRaw = getScalar('active');
    const active = activeRaw === '' ? true : activeRaw.toLowerCase() !== 'false';

    const requireReviewRaw = getScalar('require_review');
    const requireReview = requireReviewRaw.toLowerCase() === 'true';

    // ── Parse actions ───────────────────────────────────────────────────────
    const actionsBlockMatch = fm.match(/^actions:\s*\n((?:[ \t][^\n]*\n?)*)/m);
    const actions: ActionRow[] = [];

    if (actionsBlockMatch) {
        const blocks = actionsBlockMatch[1].split(/(?=^[ \t]{2}-[ \t]+)/m);
        for (const block of blocks) {
            if (!block.trim()) continue;
            const getField = (key: string) => {
                const m = block.match(new RegExp(`${key}:\\s*["']?([^"'\\n]+)["']?`));
                return m ? m[1].trim() : '';
            };
            const getListField = (): string => {
                const inlineM = block.match(/options:\s*\[([^\]]*)\]/);
                if (inlineM) return inlineM[1].split(',').map(s => s.trim()).filter(Boolean).join(', ');
                const blockM = block.match(/options:\s*\n((?:[ \t]+-[ \t]+[^\n]+\n?)+)/);
                if (blockM) return blockM[1].split('\n').map(l => l.replace(/^[ \t]+-[ \t]+/, '').trim()).filter(Boolean).join(', ');
                return '';
            };
            const getMapField = (key: string): string => {
                const m = block.match(new RegExp(`${key}:\\s*\\n((?:[ \\t]+\\S[^\\n]*\\n?)+)`));
                if (!m) return '';
                return m[1].split('\n').map(l => l.trim()).filter(Boolean).join('\n');
            };
            const mapToRows = (raw: string): KVPair[] => {
                if (!raw) return [];
                return raw.split('\n').map(line => {
                    const colonIdx = line.indexOf(':');
                    if (colonIdx <= 0) return null;
                    return {
                        key: line.slice(0, colonIdx).trim(),
                        value: line.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, ''),
                    };
                }).filter((row): row is KVPair => !!row && !!row.key);
            };

            const rawType = getField('type');

            const name = getField('name');
            if (!name) continue;
            const type = (['dropdown', 'calendar', 'input', 'button'].includes(rawType) ? rawType : 'button') as 'dropdown' | 'calendar' | 'input' | 'button';
            const rawSep = getField('separate_call');
            const separateCall = rawSep === '' ? type !== 'button' : rawSep.toLowerCase() !== 'false';

            // Parse headers map into KVPair[]
            const headersKV: KVPair[] = [];
            const rawHeaders = getMapField('headers');
            if (rawHeaders) {
                for (const line of rawHeaders.split('\n')) {
                    const colonIdx = line.indexOf(':');
                    if (colonIdx > 0) {
                        headersKV.push({
                            key: line.slice(0, colonIdx).trim(),
                            value: line.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, ''),
                        });
                    }
                }
            }

            const actionMethod = getField('method').toUpperCase() === 'GET' ? 'GET' : 'POST';
            actions.push({
                type,
                id: nextId(),
                name,
                label: getField('label'),
                description: getField('description'),
                options: getListField(),
                separateCall,
                webhook: getField('webhook'),
                method: actionMethod,
                headers: headersKV,
                query: mapToRows(getMapField('query')),
                body: mapToRows(getMapField('body')),
            });
        }
    }

    // ── Parse tools block ──────────────────────────────────────────────
    const tools: IntentToolRow[] = [];
    const toolsBlockMatch = fm.match(/^tools:\s*\n((?:[ \t][^\n]*\n?)*)/m);
    if (toolsBlockMatch) {
        const toolBlocks = toolsBlockMatch[1].split(/(?=[ \t]+-[ \t]+name:)/);
        for (const block of toolBlocks) {
            if (!block.trim()) continue;
            const getTF = (key: string) => {
                const m = block.match(new RegExp(`${key}:\\s*["']?([^"'\\n]+)["']?`));
                return m ? m[1].trim() : '';
            };
            const toolName = getTF('name');
            if (!toolName) continue;

            // Parse headers map — indent-aware to avoid capturing sibling keys
            const headersKV: KVPair[] = [];
            const hdrMatch = block.match(/([ \t]*)headers:\s*\n/);
            if (hdrMatch) {
                const parentIndent = hdrMatch[1].length;
                const afterHdr = block.slice(block.indexOf(hdrMatch[0]) + hdrMatch[0].length);
                for (const line of afterHdr.split('\n')) {
                    const lineIndent = (line.match(/^([ \t]*)/)?.[1] ?? '').length;
                    if (line.trim() && lineIndent <= parentIndent) break;
                    const trimmed = line.trim();
                    if (!trimmed) continue;
                    const colonIdx = trimmed.indexOf(':');
                    if (colonIdx > 0) {
                        headersKV.push({
                            key: trimmed.slice(0, colonIdx).trim(),
                            value: trimmed.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, ''),
                        });
                    }
                }
            }

            // Parse body map — indent-aware to avoid capturing sibling keys
            const bodyKV: KVPair[] = [];
            const bodyMatch = block.match(/([ \t]*)body:\s*\n/);
            if (bodyMatch) {
                const parentIndent = bodyMatch[1].length;
                const afterBody = block.slice(block.indexOf(bodyMatch[0]) + bodyMatch[0].length);
                for (const line of afterBody.split('\n')) {
                    const lineIndent = (line.match(/^([ \t]*)/)?.[1] ?? '').length;
                    if (line.trim() && lineIndent <= parentIndent) break;
                    const trimmed = line.trim();
                    if (!trimmed) continue;
                    const colonIdx = trimmed.indexOf(':');
                    if (colonIdx > 0) {
                        bodyKV.push({
                            key: trimmed.slice(0, colonIdx).trim(),
                            value: trimmed.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, ''),
                        });
                    }
                }
            }

            // Parse inputSchema list
            const schema: IntentToolInputField[] = [];
            const schemaMatch = block.match(/inputSchema:\s*\n((?:[ \t]+-[ \t]+[\s\S]*?)(?=\n[ \t]*-[ \t]+name:|\n[ \t]*$|$))/);
            if (schemaMatch) {
                const schemaParts = schemaMatch[1].split(/(?=[ \t]+-[ \t]+key:)/);
                for (const sp of schemaParts) {
                    if (!sp.trim()) continue;
                    const getSF = (key: string) => {
                        const m = sp.match(new RegExp(`${key}:\\s*["']?([^"'\\n]+)["']?`));
                        return m ? m[1].trim() : '';
                    };
                    const sKey = getSF('key');
                    if (!sKey) continue;
                    const rawType = getSF('type');
                    schema.push({
                        key: sKey,
                        description: getSF('description'),
                        type: (['string', 'number', 'integer', 'boolean'].includes(rawType) ? rawType : 'string') as IntentToolInputField['type'],
                        default: getSF('default'),
                        required: getSF('required') !== 'false',
                    });
                }
            }

            const rawMethod = getTF('method').toUpperCase();
            const fileExpectsRaw = getTF('expectsFile') || getTF('expects_file');
            const attachToResponseRaw = getTF('attachToResponse') || getTF('attach_to_response');
            tools.push({
                name: toolName,
                description: getTF('description'),
                method: rawMethod === 'POST' ? 'POST' : 'GET',
                urlTemplate: getTF('urlTemplate'),
                headers: headersKV,
                body: bodyKV,
                inputSchema: schema,
                expectsFile: fileExpectsRaw.toLowerCase() === 'true',
                attachToResponse: attachToResponseRaw === '' ? true : attachToResponseRaw.toLowerCase() !== 'false',
                fileNamePath: getTF('filenamePath') || getTF('filename_path'),
                fileContentTypePath: getTF('contentTypePath') || getTF('content_type_path'),
                fileContentBase64Path: getTF('contentBase64Path') || getTF('content_base64_path'),
            });
        }
    }

    return {
        name: getScalar('name'),
        description: getScalar('description'),
        active,
        requireReview,
        instructions: body,
        actions,
        response: { ...DEFAULT_RESPONSE_CONFIG },
        tools,
    };
}

function yamlString(value: string): string {
    return JSON.stringify(value ?? '');
}

function serializeIntentMd(form: IntentForm): string {
    const allActionBlocks: string[] = [];

    for (const a of form.actions) {
        if (!a.name) continue;
        const lines = [`  - type: ${a.type || 'button'}`, `    name: ${yamlString(a.name)}`, `    label: ${yamlString(a.label)}`];
        if (a.description.trim()) {
            lines.push(`    description: ${yamlString(a.description.trim())}`);
        }
        if (a.type === 'dropdown' && a.options.trim()) {
            const opts = a.options.split(',').map(o => o.trim()).filter(Boolean);
            lines.push(`    options:`);
            opts.forEach(o => lines.push(`      - ${yamlString(o)}`));
        }
        if (a.type !== 'button') {
            lines.push(`    separate_call: ${a.separateCall}`);
        }
        if (a.type === 'button' || a.separateCall) {
            const actionMethod = a.method === 'GET' ? 'GET' : 'POST';
            lines.push(`    webhook: "${a.webhook}"`, `    method: ${actionMethod}`);
            const validHeaders = a.headers.filter(h => h.key.trim());
            if (validHeaders.length > 0) {
                lines.push(`    headers:`);
                validHeaders.forEach(h => lines.push(`      ${yamlString(h.key)}: ${yamlString(h.value)}`));
            }
            const validQuery = a.query.filter(row => row.key.trim());
            if (validQuery.length > 0) {
                lines.push(`    query:`);
                validQuery.forEach(row => lines.push(`      ${yamlString(row.key)}: ${yamlString(row.value)}`));
            }
            const validBody = a.body.filter(row => row.key.trim());
            if (actionMethod === 'POST' && validBody.length > 0) {
                lines.push(`    body:`);
                validBody.forEach(row => lines.push(`      ${yamlString(row.key)}: ${yamlString(row.value)}`));
            }
        }
        allActionBlocks.push(lines.join('\n'));
    }

    const actionsStr = allActionBlocks.length > 0
        ? `actions:\n${allActionBlocks.join('\n')}`
        : 'actions: []';

    const responseLines = [
        'response:',
        `  enabled: ${form.response.enabled}`,
        `  auto: ${form.response.responseTrigger === 'auto'}`,
    ];
    if (!form.response.useFeedbackLearnings) {
        responseLines.push('  use_feedback_learnings: false');
    }
    const responseRules = form.response.responseRules.trim();
    if (responseRules) {
        responseLines.push('  response_rules:');
        responseLines.push(`    - ${yamlString(responseRules)}`);
    }
    const requiredGuidance = form.response.requiredGuidance
        .split('\n')
        .map(item => item.trim())
        .filter(Boolean);
    if (requiredGuidance.length > 0) {
        responseLines.push('  required_guidance:');
        requiredGuidance.forEach(item => responseLines.push(`    - ${yamlString(item)}`));
    }
    if (form.response.attachments.length > 0) {
        responseLines.push('  attachments:');
        for (const att of form.response.attachments) {
            responseLines.push(`    - filename: ${yamlString(att.filename)}`);
            if (att.description) responseLines.push(`      description: ${yamlString(att.description)}`);
            responseLines.push(`      mode: ${att.mode}`);
        }
    }

    // ── Serialize tools ──────────────────────────────────────────────
    let toolsStr = '';
    const validTools = form.tools.filter(t => t.name.trim());
    if (validTools.length > 0) {
        const toolBlocks: string[] = [];
        for (const t of validTools) {
            const method = t.method === 'POST' ? 'POST' : 'GET';
            const tLines = [
                `  - name: ${yamlString(t.name)}`,
                `    description: ${yamlString(t.description)}`,
                `    method: ${method}`,
                `    urlTemplate: ${yamlString(t.urlTemplate)}`,
            ];
            const validHeaders = t.headers.filter(h => h.key.trim());
            if (validHeaders.length > 0) {
                tLines.push(`    headers:`);
                validHeaders.forEach(h => tLines.push(`      ${yamlString(h.key)}: ${yamlString(h.value)}`));
            }
            const validBody = t.body.filter(b => b.key.trim());
            if (method === 'POST' && validBody.length > 0) {
                tLines.push(`    body:`);
                validBody.forEach(b => tLines.push(`      ${yamlString(b.key)}: ${yamlString(b.value)}`));
            }
            if (t.inputSchema.length > 0) {
                tLines.push(`    inputSchema:`);
                for (const s of t.inputSchema) {
                    if (!s.key.trim()) continue;
                    tLines.push(`      - key: ${yamlString(s.key)}`);
                    tLines.push(`        type: ${s.type}`);
                    if (s.description) tLines.push(`        description: ${yamlString(s.description)}`);
                    if (s.default) tLines.push(`        default: ${yamlString(s.default)}`);
                    tLines.push(`        required: ${s.required}`);
                }
            }
            if (t.expectsFile) {
                tLines.push(`    file:`);
                tLines.push(`      expectsFile: true`);
                tLines.push(`      attachToResponse: ${t.attachToResponse}`);
                tLines.push(`      filenamePath: ${yamlString(t.fileNamePath)}`);
                tLines.push(`      contentTypePath: ${yamlString(t.fileContentTypePath)}`);
                tLines.push(`      contentBase64Path: ${yamlString(t.fileContentBase64Path)}`);
            }
            toolBlocks.push(tLines.join('\n'));
        }
        toolsStr = `tools:\n${toolBlocks.join('\n')}`;
    }

    const lines = [
        '---',
        `name: ${yamlString(form.name)}`,
        `description: ${yamlString(form.description)}`,
        `active: ${form.active}`,
        `require_review: ${form.requireReview}`,
        ...responseLines,
        actionsStr,
        ...(toolsStr ? [toolsStr] : []),
        '---',
        '',
        form.instructions.trim(),
    ];

    return lines.join('\n');
}

const EMPTY_ACTION: Omit<ActionRow, 'id'> = {
    type: 'button', name: '', label: '', description: '', options: '',
    separateCall: false, webhook: '', method: 'POST', headers: [],
    query: [], body: [],
};

const DEFAULT_RESPONSE_CONFIG: ResponseConfig = {
    enabled: true,
    responseRules: '',
    requiredGuidance: '',
    responseTrigger: 'auto',
    attachments: [],
    useFeedbackLearnings: true,
};

const EMPTY_TOOL: IntentToolRow = {
    name: '', description: '', method: 'GET', urlTemplate: '',
    headers: [], body: [], inputSchema: [],
    expectsFile: false, attachToResponse: true,
    fileNamePath: 'document.filename',
    fileContentTypePath: 'document.contentType',
    fileContentBase64Path: 'document.contentBase64',
};

const DEFAULT_FORM: IntentForm = {
    name: '',
    description: '',
    active: true,
    requireReview: false,
    instructions: '# Instructions\n\nWrite the instructions the agent must follow when this intent is matched.',
    actions: [],
    response: { ...DEFAULT_RESPONSE_CONFIG },
    tools: [],
};

const ELSE_DEFAULT_FORM: IntentForm = {
    ...DEFAULT_FORM,
    name: '_else',
    instructions: '# Instructions\n\nWrite the instructions the agent must follow when no intent matches.',
};

// ── Intent tool sub-editors ───────────────────────────────────────────────────

function IntentToolKVEditor({
    rows,
    onChange,
    addLabel = 'Add row',
}: {
    rows: KVPair[];
    onChange: (rows: KVPair[]) => void;
    addLabel?: string;
}) {
    const { t } = useI18n();
    const update = (i: number, field: keyof KVPair, val: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', value: '' }]);

    return (
        <div className="space-y-1.5">
            {rows.map((row, i) => (
                <div key={i} className="flex gap-1.5 items-center">
                    <Input
                        value={row.key}
                        onChange={e => update(i, 'key', e.target.value)}
                        placeholder={t('Key')}
                        className="flex-1 h-7 text-xs font-mono"
                    />
                    <Input
                        value={row.value}
                        onChange={e => update(i, 'value', e.target.value)}
                        placeholder={t('Value')}
                        className="flex-[2] h-7 text-xs"
                    />
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => remove(i)}
                        className="shrink-0 text-muted-foreground hover:text-destructive"
                    >
                        <X className="size-3.5" />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={add} type="button" className="h-6 text-xs px-2">
                <Plus className="size-3" /> {t(addLabel)}
            </Button>
        </div>
    );
}

function getIntentToolPlaceholderParam(value: string): string {
    const match = value.match(/^\{([^}]+)\}$/);
    return match?.[1] ?? '';
}

function IntentToolBodyParameterEditor({
    rows,
    onChange,
    parameters,
}: {
    rows: KVPair[];
    onChange: (rows: KVPair[]) => void;
    parameters: string[];
}) {
    const { t } = useI18n();
    const options = Array.from(new Set(['sender_email', ...parameters.filter(Boolean)]));
    const updateKey = (i: number, key: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, key } : r));
    const updateParam = (i: number, param: string) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, value: `{${param}}` } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', value: `{${options[0]}}` }]);

    return (
        <div className="space-y-1.5">
            {rows.length > 0 && (
                <div className="grid grid-cols-[1fr_1fr_1.75rem] gap-1.5 px-0.5 text-[11px] text-muted-foreground">
                    <span>{t('Body key')}</span>
                    <span>{t('Input parameter')}</span>
                    <span />
                </div>
            )}
            {rows.map((row, i) => {
                const selected = getIntentToolPlaceholderParam(row.value);
                const available = selected && !options.includes(selected)
                    ? [...options, selected]
                    : options;

                return (
                    <div key={i} className="grid grid-cols-[1fr_1fr_1.75rem] gap-1.5 items-center">
                        <Input
                            aria-label={t('Body key')}
                            value={row.key}
                            onChange={e => updateKey(i, e.target.value)}
                            placeholder="request_field"
                            className="h-7 text-xs font-mono"
                        />
                        <Select value={selected || options[0]} onValueChange={value => updateParam(i, value)}>
                            <SelectTrigger data-size="sm" className="h-7 px-2 text-xs" aria-label={t('Input parameter')}>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {available.map(param => (
                                    <SelectItem key={param} value={param}>
                                        {param}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => remove(i)}
                            className="shrink-0 text-muted-foreground hover:text-destructive"
                        >
                            <X className="size-3.5" />
                        </Button>
                    </div>
                );
            })}
            <Button variant="outline" size="sm" onClick={add} type="button" className="h-6 text-xs px-2">
                <Plus className="size-3" /> {t('Add body parameter')}
            </Button>
        </div>
    );
}

const TOOL_FIELD_TYPES: IntentToolInputField['type'][] = ['string', 'number', 'integer', 'boolean'];

function IntentToolSchemaEditor({
    rows,
    onChange,
}: {
    rows: IntentToolInputField[];
    onChange: (rows: IntentToolInputField[]) => void;
}) {
    const { t } = useI18n();
    const update = <K extends keyof IntentToolInputField>(i: number, field: K, val: IntentToolInputField[K]) =>
        onChange(rows.map((r, idx) => idx === i ? { ...r, [field]: val } : r));
    const remove = (i: number) => onChange(rows.filter((_, idx) => idx !== i));
    const add = () => onChange([...rows, { key: '', description: '', type: 'string', default: '', required: true }]);

    return (
        <div className="space-y-1.5">
            {rows.map((row, i) => (
                <div key={i} className="grid grid-cols-[7rem_1fr_5rem_5rem_2rem_1.75rem] gap-1.5 items-center">
                    <Input
                        value={row.key}
                        onChange={e => update(i, 'key', e.target.value)}
                        placeholder="param"
                        className="h-7 text-xs font-mono"
                    />
                    <Input
                        value={row.description}
                        onChange={e => update(i, 'description', e.target.value)}
                        placeholder={t('Description')}
                        className="h-7 text-xs"
                    />
                    <Select
                        value={row.type}
                        onValueChange={value => update(i, 'type', value as IntentToolInputField['type'])}
                    >
                        <SelectTrigger data-size="sm" className="h-7 px-2 text-xs">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {TOOL_FIELD_TYPES.map(t => (
                                <SelectItem key={t} value={t}>
                                    {t}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Input
                        value={row.default ?? ''}
                        onChange={e => update(i, 'default', e.target.value)}
                        placeholder={t('Default')}
                        className="h-7 text-xs"
                    />
                    <div className="flex justify-center" title={t(row.required ? 'Required' : 'Optional')}>
                        <Switch
                            checked={row.required}
                            onCheckedChange={val => update(i, 'required', val)}
                            className="scale-75"
                        />
                    </div>
                    <Button type="button" variant="ghost" size="icon-xs" onClick={() => remove(i)}
                        className="text-muted-foreground hover:text-destructive shrink-0">
                        <X className="size-3.5" />
                    </Button>
                </div>
            ))}
            <Button variant="outline" size="sm" onClick={add} type="button" className="h-6 text-xs px-2">
                <Plus className="size-3" /> {t('Add parameter')}
            </Button>
        </div>
    );
}

// ── Badge color helpers ───────────────────────────────────────────────────────

const ACTION_TYPE_COLORS: Record<string, string> = {
    button: 'bg-blue-100 text-blue-700 border-blue-200',
    input: 'bg-green-100 text-green-700 border-green-200',
    dropdown: 'bg-purple-100 text-purple-700 border-purple-200',
    calendar: 'bg-amber-100 text-amber-700 border-amber-200',
};

const METHOD_COLORS: Record<string, string> = {
    GET: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    POST: 'bg-blue-100 text-blue-700 border-blue-200',
};

// ── Sortable action summary row (dnd-kit) ─────────────────────────────────────

function SortableActionRow({
    action,
    onClick,
}: {
    action: ActionRow;
    onClick: () => void;
}) {
    const { t } = useI18n();
    const {
        attributes,
        listeners,
        setNodeRef,
        transform,
        transition,
        isDragging,
    } = useSortable({ id: action.id });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        zIndex: isDragging ? 10 : undefined,
        opacity: isDragging ? 0.5 : 1,
    };

    return (
        <div ref={setNodeRef} style={style}>
            <div className={`rounded-lg border bg-white shadow-sm transition-shadow ${isDragging ? 'shadow-lg' : ''}`}>
                <Button
                    type="button"
                    variant="ghost"
                    className="h-auto w-full justify-start gap-2 rounded-lg px-3 py-2.5 text-left"
                    onClick={onClick}
                >
                    <span
                        {...attributes}
                        {...listeners}
                        className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground shrink-0"
                        onClick={e => e.stopPropagation()}
                        onPointerDown={e => { e.stopPropagation(); listeners?.onPointerDown?.(e); }}
                    >
                        <GripVertical className="size-4" />
                    </span>
                    <span className="text-sm font-medium truncate flex-1">
                        {action.label || action.name || t('Untitled action')}
                    </span>
                    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${ACTION_TYPE_COLORS[action.type] ?? 'bg-gray-100 text-gray-700 border-gray-200'}`}>
                        {action.type}
                    </span>
                    {(action.type === 'button' || action.separateCall) && action.method && (
                        <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${METHOD_COLORS[action.method] ?? ''}`}>
                            {action.method}
                        </span>
                    )}
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </Button>
            </div>
        </div>
    );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface IntentsProps {
    projectId: string;
    userRole: UserRole;
}

export const Intents = ({ projectId, userRole }: IntentsProps) => {
    const { t } = useI18n();
    const navigate = useNavigate();
    const { tenantId, '*': splatPath } = useParams();
    const urlIntentName = splatPath || null;
    const basePath = `/${tenantId}/${projectId}/runbooks`;

    const [view, setView] = useState<View>('list');
    const [intents, setIntents] = useState<IntentSummary[]>([]);
    const [loadingList, setLoadingList] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const [editName, setEditName] = useState('');
    const [form, setForm] = useState<IntentForm>(DEFAULT_FORM);
    const [loadingContent, setLoadingContent] = useState(false);
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);

    // Files supplied by this runbook to the final ticket composer
    const [intentFiles, setIntentFiles] = useState<IntentFileInfo[]>([]);
    const [uploadingFile, setUploadingFile] = useState(false);
    const [attachmentsDialogOpen, setAttachmentsDialogOpen] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Learnings & feedback
    const [learnings, setLearnings] = useState<IntentLearning[]>([]);
    const [feedbackEntries, setFeedbackEntries] = useState<IntentFeedback[]>([]);
    const [learningProposals, setLearningProposals] = useState<IntentLearningProposal[]>([]);
    const [evalSets, setEvalSets] = useState<EvalSet[]>([]);
    const [loadingLearnings, setLoadingLearnings] = useState(false);
    const [editingLearningId, setEditingLearningId] = useState<string | null>(null);
    const [editingLearningText, setEditingLearningText] = useState('');
    const [learningsDialogOpen, setLearningsDialogOpen] = useState(false);
    const [busyProposalId, setBusyProposalId] = useState<string | null>(null);
    const [derivingFeedbackId, setDerivingFeedbackId] = useState<string | null>(null);
    const learningIntentRef = useRef('');

    // Dialog state for editing actions/tools
    const [editingActionIdx, setEditingActionIdx] = useState<number | null>(null);
    const [editingToolIdx, setEditingToolIdx] = useState<number | null>(null);

    // Drag-and-drop sensors for action reordering
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
    );

    const loadIntents = async () => {
        setLoadingList(true);
        setLoadError(null);
        const res = await api.getIntents(projectId);
        if (res.data) {
            setIntents(res.data.map((i: Record<string, unknown>) => ({
                name: i.name as string,
                description: i.description as string,
                actions: i.actions as unknown[],
                response: i.response,
                active: i.active as boolean,
                requireReview: (i.require_review as boolean) ?? false,
            })));
        } else {
            setLoadError(t('Could not reach the backend. Is it running?'));
        }
        setLoadingList(false);
    };

    const loadIntentFiles = useCallback(async (intentName: string) => {
        const res = await api.listIntentFiles(projectId, intentName);
        if (res.data) setIntentFiles(res.data);
    }, [projectId]);

    const loadLearningProposals = useCallback(async (intentName: string) => {
        const res = await api.getIntentLearningProposals(projectId, intentName);
        if (learningIntentRef.current !== intentName) return;
        if (res.data) setLearningProposals(res.data);
    }, [projectId]);

    const loadLearningsAndFeedback = useCallback(async (intentName: string) => {
        setLoadingLearnings(true);
        const [lRes, fRes, pRes, eRes] = await Promise.all([
            api.getIntentLearnings(projectId, intentName),
            api.getIntentFeedback(projectId, intentName),
            api.getIntentLearningProposals(projectId, intentName),
            api.getEvalSets(projectId),
        ]);
        if (learningIntentRef.current !== intentName) return;
        if (lRes.data) setLearnings(lRes.data);
        if (fRes.data) setFeedbackEntries(fRes.data);
        if (pRes.data) setLearningProposals(pRes.data);
        if (eRes.data) setEvalSets(eRes.data);
        setLoadingLearnings(false);
    }, [projectId]);

    const handleFileUpload = async (files: FileList | null) => {
        if (!files?.length) return;
        const intentName = view === 'new'
            ? form.name.trim().toLowerCase().replace(/\s+/g, '-')
            : editName;
        if (!intentName) { toast.error(t('Save the runbook first before uploading files')); return; }

        setUploadingFile(true);
        for (const file of Array.from(files)) {
            const res = await api.uploadIntentFile(projectId, intentName, file);
            if (res.error) {
                toast.error(t('Upload failed: {error}', { error: res.error }));
            } else {
                toast.success(t('Uploaded {filename}', { filename: file.name }));
            }
        }
        await loadIntentFiles(intentName);
        setUploadingFile(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handleDeleteFile = async (filename: string) => {
        const intentName = view === 'new' ? form.name.trim().toLowerCase().replace(/\s+/g, '-') : editName;
        if (!intentName) return;
        const res = await api.deleteIntentFile(projectId, intentName, filename);
        if (res.error) {
            toast.error(t('Delete failed: {error}', { error: res.error }));
        } else {
            // Also remove from attachment metadata
            setForm(f => ({
                ...f,
                response: {
                    ...f.response,
                    attachments: f.response.attachments.filter(a => a.filename !== filename),
                },
            }));
            toast.success(t('Deleted {filename}', { filename }));
        }
        await loadIntentFiles(intentName);
    };

    useEffect(() => {
        void api.getIntents(projectId).then((res) => {
            if (res.data) {
                setIntents(res.data.map((i: Record<string, unknown>) => ({
                    name: i.name as string,
                    description: i.description as string,
                    actions: i.actions as unknown[],
                    response: i.response,
                    active: i.active as boolean,
                    requireReview: (i.require_review as boolean) ?? false,
                })));
            } else {
                setLoadError(t('Could not reach the backend. Is it running?'));
            }
            setLoadingList(false);
        });
    }, [projectId, t]);

    const openEdit = async (name: string) => {
        learningIntentRef.current = name;
        setEditName(name);
        setView('edit');
        setLoadingContent(true);
        setLearnings([]);
        setFeedbackEntries([]);
        setLearningProposals([]);
        const res = await api.getIntent(projectId, name);
        if (res.data) {
            setForm(parseIntentMd(res.data.content));
        } else {
            toast.error(t('Failed to load runbook'));
            setView('list');
        }
        setLoadingContent(false);
        void loadIntentFiles(name);
        void loadLearningsAndFeedback(name);
    };

    // Sync view with URL intent name
    useEffect(() => {
        if (urlIntentName) {
            void openEdit(urlIntentName);
        } else if (view === 'edit') {
            setView('list');
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [urlIntentName]);

    useEffect(() => {
        if (view !== 'edit' || !editName || !learningProposals.some(proposal => proposal.status === 'evaluating')) {
            return;
        }
        const timer = window.setInterval(() => {
            void loadLearningProposals(editName);
        }, 2500);
        return () => window.clearInterval(timer);
    }, [editName, learningProposals, loadLearningProposals, view]);

    const openNew = (isElse = false) => {
        learningIntentRef.current = '';
        setEditName('');
        const source = isElse ? ELSE_DEFAULT_FORM : DEFAULT_FORM;
        setForm({
            ...source,
            actions: [...source.actions],
            tools: [...source.tools],
            response: {
                ...source.response,
                attachments: [...source.response.attachments],
            },
        });
        setIntentFiles([]);
        setLearnings([]);
        setFeedbackEntries([]);
        setLearningProposals([]);
        setEvalSets([]);
        setView('new');
    };

    const updateForm = <K extends keyof IntentForm>(key: K, value: IntentForm[K]) =>
        setForm(f => ({ ...f, [key]: value }));

    const updateAction = (idx: number, patch: Partial<ActionRow>) =>
        setForm(f => {
            const actions = [...f.actions];
            actions[idx] = { ...actions[idx], ...patch };
            return { ...f, actions };
        });

    const addAction = () => setForm(f => ({ ...f, actions: [...f.actions, { ...EMPTY_ACTION, id: nextId() }] }));

    const removeAction = (idx: number) =>
        setForm(f => ({ ...f, actions: f.actions.filter((_, i) => i !== idx) }));

    const handleDragEnd = (event: DragEndEvent) => {
        const { active, over } = event;
        if (!over || active.id === over.id) return;
        setForm(f => {
            const oldIndex = f.actions.findIndex(a => a.id === active.id);
            const newIndex = f.actions.findIndex(a => a.id === over.id);
            if (oldIndex === -1 || newIndex === -1) return f;
            return { ...f, actions: arrayMove(f.actions, oldIndex, newIndex) };
        });
    };

    const updateTool = (idx: number, patch: Partial<IntentToolRow>) =>
        setForm(f => {
            const tools = [...f.tools];
            tools[idx] = { ...tools[idx], ...patch };
            return { ...f, tools };
        });

    const addTool = () => setForm(f => ({ ...f, tools: [...f.tools, { ...EMPTY_TOOL }] }));

    const removeTool = (idx: number) =>
        setForm(f => ({ ...f, tools: f.tools.filter((_, i) => i !== idx) }));

    const handleUpdateLearning = async (learningId: string, text: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        const learning = learnings.find(item => item.id === learningId);
        const proposedLearning = text.trim();
        if (!learning || !proposedLearning || proposedLearning === learning.learning) {
            setEditingLearningId(null);
            return;
        }
        const res = await api.createIntentLearningProposal(projectId, intentName, {
            operation: 'update',
            proposedLearning,
            targetLearningId: learningId,
            affectedStages: learning.affected_stages,
        });
        if (res.error) {
            toast.error(t('Proposal failed: {error}', { error: res.error }));
        } else {
            if (res.data) setLearningProposals(prev => [res.data!, ...prev.filter(item => item.id !== res.data!.id)]);
            setEditingLearningId(null);
            setLearningsDialogOpen(true);
            toast.success(t('Learning change proposed. Evaluation required before publication.'));
        }
    };

    const handleDeleteLearning = async (learningId: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        const learning = learnings.find(item => item.id === learningId);
        if (!learning) return;
        const res = await api.createIntentLearningProposal(projectId, intentName, {
            operation: 'delete',
            targetLearningId: learningId,
            affectedStages: learning.affected_stages,
        });
        if (res.error) {
            toast.error(t('Proposal failed: {error}', { error: res.error }));
        } else {
            if (res.data) setLearningProposals(prev => [res.data!, ...prev.filter(item => item.id !== res.data!.id)]);
            setLearningsDialogOpen(true);
            toast.success(t('Learning deletion proposed. Evaluation required before publication.'));
        }
    };

    const handleLearnFeedback = async (feedbackId: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!intentName || derivingFeedbackId) return;
        setDerivingFeedbackId(feedbackId);
        const res = await api.createIntentLearningProposalsFromFeedback(projectId, intentName, feedbackId);
        setDerivingFeedbackId(null);
        if (res.error) {
            toast.error(t('Could not create learning proposal: {error}', { error: res.error }));
            return;
        }
        const proposals = res.data?.proposals ?? [];
        if (proposals.length === 0) {
            toast.info(t('No actionable learning found in this feedback.'));
            return;
        }
        setLearningProposals(prev => [
            ...proposals,
            ...prev.filter(existing => !proposals.some(proposal => proposal.id === existing.id)),
        ]);
        toast.success(t('{count} learning proposal(s) created.', { count: proposals.length }));
    };

    const handleEvaluateProposal = async (proposalId: string, evalSetId: string, minimumScore: number) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!intentName || busyProposalId) return;
        setBusyProposalId(proposalId);
        const res = await api.evaluateIntentLearningProposal(projectId, intentName, proposalId, evalSetId, minimumScore);
        setBusyProposalId(null);
        if (res.error) {
            toast.error(t('Evaluation failed to start: {error}', { error: res.error }));
            return;
        }
        if (res.data) {
            setLearningProposals(prev => prev.map(proposal => proposal.id === res.data!.id ? res.data! : proposal));
        }
        toast.success(t('Evaluation started. Publication stays locked until it passes.'));
    };

    const handlePublishProposal = async (proposalId: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!intentName || busyProposalId) return;
        setBusyProposalId(proposalId);
        const res = await api.publishIntentLearningProposal(projectId, intentName, proposalId);
        setBusyProposalId(null);
        if (res.error) {
            toast.error(t('Publication failed: {error}', { error: res.error }));
            return;
        }
        await loadLearningsAndFeedback(intentName);
        toast.success(t('Learning published to the live runbook.'));
    };

    const handleRejectProposal = async (proposalId: string, reason: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!intentName || busyProposalId) return;
        setBusyProposalId(proposalId);
        const res = await api.rejectIntentLearningProposal(projectId, intentName, proposalId, reason);
        setBusyProposalId(null);
        if (res.error) {
            toast.error(t('Rejection failed: {error}', { error: res.error }));
            return;
        }
        if (res.data) {
            setLearningProposals(prev => prev.map(proposal => proposal.id === res.data!.id ? res.data! : proposal));
        }
        toast.success(t('Learning proposal rejected. Live behavior unchanged.'));
    };

    const handleDeleteFeedback = async (feedbackId: string) => {
        const intentName = view === 'edit' ? editName : form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!intentName) return;
        if (!confirm(t('Delete this feedback? Any legacy learning directly derived from it will also be removed.'))) return;
        setLoadingLearnings(true);
        const res = await api.deleteIntentFeedback(projectId, intentName, feedbackId);
        if (res.error) {
            toast.error(t('Delete failed: {error}', { error: res.error }));
            setLoadingLearnings(false);
            return;
        }
        const removedLearningCount = res.data?.removedLearningCount ?? 0;
        toast.success(removedLearningCount > 0
            ? t('Feedback deleted. Removed {count} linked legacy learning(s).', { count: removedLearningCount })
            : t('Feedback deleted.'));
        await loadLearningsAndFeedback(intentName);
    };

    const handleSave = async () => {
        const slug = form.name.trim().toLowerCase().replace(/\s+/g, '-');
        if (!slug) { toast.error(t('Intent name is required')); return; }
        if (slug !== '_else' && !form.description.trim()) { toast.error(t('Short description is required')); return; }
        const invalidAction = form.actions.find(action =>
            action.name.trim()
            && (action.type === 'button' || action.separateCall)
            && !action.webhook.trim()
        );
        if (invalidAction) {
            toast.error(t('Webhook URL is required for action {action}', {
                action: invalidAction.label.trim() || invalidAction.name.trim(),
            }));
            return;
        }
        const invalidTool = form.tools.find(t => t.name.trim() && !t.urlTemplate.trim());
        if (invalidTool) {
            toast.error(t('Endpoint is required for tool {tool}', { tool: invalidTool.name.trim() }));
            return;
        }

        setSaving(true);

        // If editing and the name changed, rename first
        const renamed = view === 'edit' && slug !== editName;
        if (renamed) {
            const renameRes = await api.renameIntent(projectId, editName, slug);
            if (renameRes.error) {
                toast.error(t('Rename failed: {error}', { error: renameRes.error }));
                setSaving(false);
                return;
            }
        }

        const finalForm = { ...form, name: slug };
        const content = serializeIntentMd(finalForm);
        const res = await api.upsertIntent(projectId, slug, content);
        if (res.error) {
            toast.error(t('Save failed: {error}', { error: res.error }));
        } else {
            toast.success(t('Intent saved'));
            await loadIntents();
            window.dispatchEvent(new Event('admin:intents-changed'));
            if (view === 'new' || renamed) {
                void navigate(`${basePath}/${slug}`, { replace: true });
            }
        }
        setSaving(false);
    };

    const handleDelete = async () => {
        if (!confirm(t('Delete runbook "{name}"?', { name: editName }))) return;
        setDeleting(true);
        const res = await api.deleteIntent(projectId, editName);
        if (res.error) {
            toast.error(t('Delete failed: {error}', { error: res.error }));
        } else {
            toast.success(t('Runbook deleted'));
            await loadIntents();
            window.dispatchEvent(new Event('admin:intents-changed'));
            void navigate(basePath);
        }
        setDeleting(false);
    };

    // ── Top bar: inject breadcrumb + actions for edit/new view ────────────────

    const { setBreadcrumb, setActions } = useTopBar();
    const isElse = form.name === '_else' || editName === '_else';
    const displayName = isElse
        ? t('Default (no match)')
        : view === 'new' ? t('New runbook') : editName;

    useEffect(() => {
        if (view !== 'edit' && view !== 'new') {
            setBreadcrumb(null);
            setActions(null);
            return;
        }

        setBreadcrumb(
            <Breadcrumb>
                <BreadcrumbList>
                    <BreadcrumbItem className="hidden md:block">
                        <BreadcrumbLink asChild>
                            <Link to={basePath}>{t('AI runbooks')}</Link>
                        </BreadcrumbLink>
                    </BreadcrumbItem>
                    <BreadcrumbSeparator className="hidden md:block" />
                    <BreadcrumbItem>
                        <BreadcrumbPage>{displayName}</BreadcrumbPage>
                    </BreadcrumbItem>
                </BreadcrumbList>
            </Breadcrumb>
        );

        setActions(
            <>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => updateForm('active', !form.active)}
                    className="w-[7.5rem] justify-start gap-2 text-muted-foreground"
                >
                    <span>{t(form.active ? 'Active' : 'Disabled')}</span>
                    <Switch
                        checked={form.active}
                        onCheckedChange={v => updateForm('active', v)}
                        className="ml-auto pointer-events-none scale-75"
                    />
                </Button>
                <Button size="sm" onClick={handleSave} disabled={saving}>
                    {saving ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                    {t('Save runbook')}
                </Button>
                {view === 'edit' && (
                    <Button size="sm" variant="destructive" onClick={handleDelete} disabled={deleting}>
                        {deleting ? <Loader className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        {t('Delete')}
                    </Button>
                )}
            </>
        );

        return () => {
            setBreadcrumb(null);
            setActions(null);
        };
    });

    // ── List view ─────────────────────────────────────────────────────────────

    if (view === 'list') {
        const regularIntents = intents.filter(i => i.name !== '_else');
        const elseIntent = intents.find(i => i.name === '_else');

        return (
            <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
                <HintBanner storageKey="intent-identification" title={t('What are AI runbooks?')}>
                    {t('AI runbooks teach the agent how to recognize concerns, gather evidence, follow policies, and prepare actions. The Inbox Reply Composer combines every matched runbook into one customer draft.')}
                </HintBanner>

                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-lg font-semibold">{t('AI runbooks')}</h2>
                        <p className="text-sm text-muted-foreground">
                            {t('Each runbook defines when a concern matches and what facts, constraints, and actions the final reply must respect.')}
                        </p>
                    </div>
                    <Button size="sm" onClick={() => openNew()}>
                        <Plus className="size-4" /> {t('New runbook')}
                    </Button>
                </div>

                {loadError && (
                    <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-2 text-sm text-destructive flex items-center gap-2">
                        <AlertCircle className="size-4 shrink-0" />
                        {loadError}
                    </div>
                )}

                {loadingList ? (
                    <div className="flex items-center gap-2 text-muted-foreground">
                        <Loader className="size-4 animate-spin" /> {t('Loading...')}
                    </div>
                ) : regularIntents.length === 0 && !loadError ? (
                    <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                        {t('No runbooks yet. Create one to get started.')}
                    </div>
                ) : (
                    <div className="divide-y overflow-hidden rounded-lg border bg-white">
                        {regularIntents.map(intent => (
                            <Button
                                type="button"
                                variant="ghost"
                                key={intent.name}
                                className="grid h-auto w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 overflow-hidden whitespace-normal rounded-none px-4 py-3 text-left hover:bg-gray-50"
                                onClick={() => navigate(`${basePath}/${intent.name}`)}
                            >
                                <div className="min-w-0 overflow-hidden">
                                    <div className={`truncate text-sm font-medium ${!intent.active ? 'text-muted-foreground' : ''}`}>{intent.name}</div>
                                    <div className="truncate text-xs text-muted-foreground">{intent.description}</div>
                                </div>
                                <div className="flex min-w-0 shrink-0 items-center gap-2">
                                    {!intent.active && (
                                        <Badge variant="outline" className="text-xs text-muted-foreground">{t('Disabled')}</Badge>
                                    )}
                                    {intent.requireReview && (
                                        <Badge variant="outline" className="text-xs">{t('Human review')}</Badge>
                                    )}
                                    {intent.actions.length > 0 && (
                                        <Badge variant="secondary" className="text-xs">
                                            {t('{count} {unit}', {
                                                count: intent.actions.length,
                                                unit: intent.actions.length === 1 ? t('action') : t('actions'),
                                            })}
                                        </Badge>
                                    )}
                                    <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                </div>
                            </Button>
                        ))}
                    </div>
                )}

                {/* ── Else / Default response ── */}
                <div className="space-y-1.5">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Default (no match)')}</p>
                    <div className="rounded-lg border bg-white">
                        {elseIntent ? (
                            <Button
                                type="button"
                                variant="ghost"
                                className="h-auto w-full justify-between gap-4 whitespace-normal rounded-none px-4 py-3 text-left hover:bg-gray-50"
                                onClick={() => navigate(`${basePath}/_else`)}
                            >
                                <div className="min-w-0">
                                    <div className={`font-medium text-sm ${!elseIntent.active ? 'text-muted-foreground' : ''}`}>
                                        {t('Default')}
                                    </div>
                                    <div className="text-xs text-muted-foreground">{t('Used when no runbook matches')}</div>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    {!elseIntent.active && (
                                        <Badge variant="outline" className="text-xs text-muted-foreground">{t('Disabled')}</Badge>
                                    )}
                                    <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                </div>
                            </Button>
                        ) : (
                            <Button
                                type="button"
                                variant="ghost"
                                className="h-auto w-full justify-between gap-4 whitespace-normal rounded-none px-4 py-3 text-left hover:bg-gray-50"
                                onClick={() => openNew(true)}
                            >
                                <div className="text-sm text-muted-foreground italic">{t('Not configured - click to set up')}</div>
                                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                            </Button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // ── Loading content ───────────────────────────────────────────────────────

    if (loadingContent) {
        return (
            <div className="flex items-center gap-2 text-muted-foreground py-8">
                <Loader className="size-4 animate-spin" /> {t('Loading runbook...')}
            </div>
        );
    }

    const feedbackLearningsEnabled = form.response.useFeedbackLearnings;
    const canEditLearnings = userRole === 'root' || userRole === 'admin' || userRole === 'editor';
    const canPublishLearnings = userRole === 'root' || userRole === 'admin';
    const pendingLearningProposals = learningProposals.filter(proposal => (
        proposal.status !== 'published' && proposal.status !== 'rejected'
    )).length;
    const regularActions = form.actions.map((action, idx) => ({ action, originalIdx: idx }));
    const instructionsDisabled = regularActions.length === 0 && form.tools.length === 0;
    const updateResponseAttachment = (filename: string, patch: Partial<ResponseAttachmentMeta>) => {
        const current = form.response.attachments;
        const exists = current.findIndex(a => a.filename === filename);
        const updated = exists >= 0
            ? current.map((a, i) => i === exists ? { ...a, ...patch } : a)
            : [...current, { filename, description: '', mode: 'always' as const, ...patch }];
        setForm(f => ({ ...f, response: { ...f.response, attachments: updated } }));
    };

    // ── Edit / New view ───────────────────────────────────────────────────────

    return (
        <div className="flex-1 min-h-0 flex flex-col gap-4">
            {/* ── 3-column grid ── */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-3 gap-4">

                {/* ── Column 1: Overview + Feedback ── */}
                <div className="flex flex-col overflow-hidden gap-4">
                    <Card className="flex flex-col overflow-hidden p-3 flex-[5]">
                        <section className="space-y-4">
                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Overview')}</h3>

                            {isElse ? (
                                <p className="text-sm text-muted-foreground">
                                    {t('Default runbook - matched when no other runbook applies.')}
                                </p>
                            ) : (
                                <>
                                    <div className="space-y-1.5">
                                        <Label htmlFor="intentName">
                                            {t('Name')} <span className="font-normal text-muted-foreground">{t('(slug)')}</span>
                                        </Label>
                                        <Input
                                            id="intentName"
                                            value={form.name}
                                            onChange={e => updateForm('name', e.target.value.toLowerCase().replace(/\s+/g, '-'))}
                                            placeholder="e.g. claim-submission"
                                        />
                                    </div>

                                    <div className="space-y-1.5">
                                        <Label htmlFor="intentDesc">{t('Short description')}</Label>
                                        <Textarea
                                            id="intentDesc"
                                            value={form.description}
                                            onChange={e => updateForm('description', e.target.value)}
                                            placeholder={t('Short description of when this runbook matches')}
                                            rows={3}
                                            className="resize-none [field-sizing:fixed]"
                                        />
                                        <p className="text-xs text-muted-foreground">{t('Shown to the agent during runbook matching.')}</p>
                                    </div>
                                </>
                            )}

                            {/* ── Require human review toggle ── */}
                            <div className="flex items-center justify-between pt-1">
                                <Label className="text-sm font-medium">{t('Require human review')}</Label>
                                <Switch
                                    checked={form.requireReview}
                                    onCheckedChange={v => setForm(f => ({ ...f, requireReview: v }))}
                                />
                            </div>
                            {form.requireReview && (
                                <p className="text-xs text-muted-foreground -mt-2">
                                    {t('Actions are disabled when human review is required.')}
                                </p>
                            )}
                        </section>
                    </Card>

                    <Card className="flex flex-col overflow-hidden p-3 flex-[5]">
                        <section className="flex-1 flex flex-col min-h-0 gap-3">
                            <div className="shrink-0 flex items-center justify-between gap-2">
                                <div>
                                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Feedback')}</h3>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        {t('Active learning rules for this runbook. Feedback remains inert until an explicit reviewed publication flow.')}
                                    </p>
                                </div>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="h-7 text-xs px-2"
                                    onClick={() => setLearningsDialogOpen(true)}
                                >
                                    {t('Learning review')}
                                    {pendingLearningProposals > 0 && (
                                        <Badge variant="secondary" className="ml-1 h-4 min-w-4 px-1 text-[9px]">
                                            {pendingLearningProposals}
                                        </Badge>
                                    )}
                                </Button>
                            </div>

                            <div className="flex-1 min-h-0 space-y-2 overflow-y-auto">
                                <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <Lightbulb className="size-3.5 shrink-0 text-muted-foreground" />
                                        <span className="truncate text-xs text-muted-foreground">
                                            {t('{count} active {unit}', {
                                                count: learnings.length,
                                                unit: learnings.length === 1 ? t('rule') : t('rules'),
                                            })}
                                        </span>
                                    </div>
                                    <Switch
                                        checked={feedbackLearningsEnabled}
                                        onCheckedChange={v => setForm(f => ({
                                            ...f,
                                            response: { ...f.response, useFeedbackLearnings: v },
                                        }))}
                                    />
                                </div>

                                {loadingLearnings ? (
                                    <div className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs text-muted-foreground">
                                        <Loader className="size-3 animate-spin" /> {t('Loading learnings...')}
                                    </div>
                                ) : !feedbackLearningsEnabled ? (
                                    <Item variant="outline" size="sm">
                                        <ItemMedia variant="icon" className="size-7">
                                            <Lightbulb className="size-3" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle className="text-xs">{t('Learnings disabled')}</ItemTitle>
                                            <ItemDescription className="text-xs">{t('Enable existing learning rules with the switch above.')}</ItemDescription>
                                        </ItemContent>
                                    </Item>
                                ) : learnings.length === 0 ? (
                                    <Item variant="outline" size="sm">
                                        <ItemMedia variant="icon" className="size-7">
                                            <Lightbulb className="size-3" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle className="text-xs">{t('No active learning rules')}</ItemTitle>
                                            <ItemDescription className="text-xs">{t('Feedback remains evidence until a user explicitly reviews and publishes a learning.')}</ItemDescription>
                                        </ItemContent>
                                    </Item>
                                ) : (
                                    <ItemGroup className="gap-1.5">
                                        {learnings.map(l => (
                                            <Item key={l.id} size="sm" variant="outline" className="block p-2 text-xs group">
                                                {editingLearningId === l.id ? (
                                                    <div className="space-y-1.5">
                                                        <Textarea
                                                            value={editingLearningText}
                                                            onChange={e => setEditingLearningText(e.target.value)}
                                                            className="resize-none text-xs min-h-[3rem] [field-sizing:content]"
                                                            rows={2}
                                                        />
                                                        <div className="flex gap-1 justify-end">
                                                            <Button type="button" variant="ghost" size="sm" className="h-6 text-xs px-1.5"
                                                                onClick={() => setEditingLearningId(null)}>
                                                                {t('Cancel')}
                                                            </Button>
                                                            <Button type="button" size="sm" className="h-6 text-xs px-1.5"
                                                                onClick={() => handleUpdateLearning(l.id, editingLearningText)}>
                                                                <Check className="size-3" /> {t('Propose')}
                                                            </Button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className="flex items-start gap-1.5">
                                                        <ItemDescription className="flex-1 text-xs leading-relaxed line-clamp-none text-foreground">{l.learning}</ItemDescription>
                                                        {canEditLearnings && (
                                                            <ItemActions className="gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                                                <Button type="button"
                                                                    variant="ghost"
                                                                    size="icon-xs"
                                                                    className="text-muted-foreground hover:text-foreground"
                                                                    aria-label={t('Propose learning edit')}
                                                                    onClick={() => { setEditingLearningId(l.id); setEditingLearningText(l.learning); }}>
                                                                    <Pencil className="size-3" />
                                                                </Button>
                                                                <Button type="button"
                                                                    variant="ghost"
                                                                    size="icon-xs"
                                                                    className="text-muted-foreground hover:text-destructive"
                                                                    aria-label={t('Propose learning deletion')}
                                                                    onClick={() => handleDeleteLearning(l.id)}>
                                                                    <Trash2 className="size-3" />
                                                                </Button>
                                                            </ItemActions>
                                                        )}
                                                    </div>
                                                )}
                                            </Item>
                                        ))}
                                    </ItemGroup>
                                )}
                            </div>
                        </section>
                    </Card>
                </div>

                {/* ── Column 2: Instructions + Tools ── */}
                <div className="flex flex-col overflow-hidden gap-4">
                    {/* Instructions (top ~70%) */}
                    <Card className="flex flex-col overflow-hidden p-3 flex-[7]">
                        <section className="flex-1 flex flex-col min-h-0 gap-3">
                            <div className="shrink-0">
                                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Instructions')}</h3>
                                <p className="text-xs text-muted-foreground mt-1">
                                    {t('Markdown instructions the agent follows when processing this runbook.')}
                                </p>
                            </div>
                            {instructionsDisabled ? (
                                <Item variant="outline" className="flex-1 flex-col items-center justify-center gap-2 bg-muted/30 p-4 text-center text-muted-foreground">
                                    <ItemMedia variant="icon" className="size-8 !self-center border-muted-foreground/20 text-muted-foreground">
                                        <AlertCircle className="size-4" />
                                    </ItemMedia>
                                    <ItemContent className="max-w-sm flex-none items-center text-center">
                                        <ItemTitle className="justify-center text-sm text-muted-foreground">{t('No tools or actions configured')}</ItemTitle>
                                        <ItemDescription className="text-center text-xs leading-relaxed text-muted-foreground">
                                            {t('Instructions guide tool calls and action execution. Add a tool or action to enable this section. Put customer-facing constraints in Customer communication requirements.')}
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                            ) : (
                                <Textarea
                                    value={form.instructions}
                                    onChange={e => updateForm('instructions', e.target.value)}
                                    className="flex-1 min-h-0 resize-none [field-sizing:fixed] font-mono text-xs leading-relaxed md:text-xs"
                                />
                            )}
                        </section>
                    </Card>

                    {/* Tools panel (bottom ~30%) */}
                    <Card className="flex flex-col overflow-hidden p-3 flex-[3]">
                        <section className="flex-1 flex flex-col min-h-0 gap-3">
                            <div className="shrink-0 flex items-center justify-between gap-2">
                                <div>
                                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Tools')}</h3>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        {t('HTTP APIs the agent can call while processing this runbook.')}
                                    </p>
                                </div>
                                <Button
                                    type="button" size="sm" variant="outline"
                                    onClick={addTool}
                                    className="h-7 text-xs px-2"
                                >
                                    <Plus className="size-3" /> {t('Add tool')}
                                </Button>
                            </div>
                            <div className="flex-1 min-h-0 overflow-y-auto">
                                {form.tools.length === 0 ? (
                                    <p className="text-sm text-muted-foreground italic">{t('No tools configured.')}</p>
                                ) : (
                                    <div className="space-y-2">
                                        {form.tools.map((tool, idx) => (
                                            <div key={idx} className="rounded-lg border bg-white shadow-sm">
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    className="h-auto w-full justify-start gap-2 rounded-lg px-3 py-2.5 text-left"
                                                    onClick={() => setEditingToolIdx(idx)}
                                                >
                                                    <span className="text-sm font-medium truncate flex-1">
                                                        {tool.name || t('Tool {number}', { number: idx + 1 })}
                                                    </span>
                                                    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${METHOD_COLORS[tool.method] ?? 'bg-gray-100 text-gray-700 border-gray-200'}`}>
                                                        {tool.method}
                                                    </span>
                                                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                                                </Button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </section>
                    </Card>
                </div>

                {/* ── Column 3: Actions + communication requirements ── */}
                <div className="flex flex-col overflow-hidden gap-4">
                    {/* Regular actions (top ~30%) */}
                    <Card className={cn('flex flex-col overflow-hidden p-3', regularActions.length === 0 ? 'shrink-0' : 'flex-[3]')}>
                        <section className={cn('flex flex-col gap-3', regularActions.length > 0 && 'min-h-0 flex-1')}>
                            <div className="shrink-0 flex items-center justify-between gap-2">
                                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Actions')}</h3>
                                <Button
                                    type="button" size="sm" variant="outline"
                                    onClick={addAction}
                                    disabled={form.requireReview}
                                    className="h-7 text-xs px-2"
                                >
                                    <Plus className="size-3" /> {t('Add action')}
                                </Button>
                            </div>

                            {regularActions.length > 0 && (
                                <div className={`flex-1 min-h-0 flex flex-col gap-3 ${form.requireReview ? 'pointer-events-none opacity-40' : ''}`}>
                                    <div className="flex-1 min-h-0 overflow-y-auto">
                                        <DndContext
                                            sensors={sensors}
                                            collisionDetection={closestCenter}
                                            onDragEnd={handleDragEnd}
                                        >
                                            <SortableContext
                                                items={regularActions.map(({ action }) => action.id)}
                                                strategy={verticalListSortingStrategy}
                                            >
                                                <div className="space-y-2">
                                                    {regularActions.map(({ action }, visualIdx) => (
                                                        <SortableActionRow
                                                            key={action.id}
                                                            action={action}
                                                            onClick={() => setEditingActionIdx(visualIdx)}
                                                        />
                                                    ))}
                                                </div>
                                            </SortableContext>
                                        </DndContext>
                                    </div>
                                </div>
                            )}
                        </section>
                    </Card>

                    {/* Inputs supplied to the ticket-level reply composer (bottom ~70%) */}
                    <Card className="flex min-h-0 flex-col overflow-hidden p-3 flex-[7]">
                        <section className="flex min-h-0 flex-1 flex-col gap-3">
                            <div className="shrink-0">
                                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t('Customer communication requirements')}</h3>
                                <p className="text-xs text-muted-foreground mt-1">
                                    {t('Supply evidence, constraints, and attachments to the Inbox Reply Composer. Runbooks do not create separate customer drafts.')}
                                </p>
                            </div>

                            <div className="flex min-h-0 flex-1 flex-col gap-3">
                                <div className="flex min-h-0 flex-1 flex-col gap-1">
                                    <Label className="shrink-0 text-xs">{t('Required points and constraints')}</Label>
                                    <Textarea
                                        value={form.response.responseRules}
                                        onChange={e => setForm(f => ({
                                            ...f,
                                            response: { ...f.response, responseRules: e.target.value },
                                        }))}
                                        placeholder={t('State the verified cancellation date\nDescribe pending actions as pending\nNever promise availability without a tool result')}
                                        className="min-h-28 flex-1 resize-none overflow-y-auto field-sizing-fixed text-sm"
                                        rows={3}
                                    />
                                </div>

                                <div className="flex min-h-0 flex-1 flex-col gap-1">
                                    <Label className="shrink-0 text-xs">{t('Required guidance (opt-in)')}</Label>
                                    <p className="shrink-0 text-xs text-muted-foreground">
                                        {t('Add one guidance requirement per line. Leave empty when no specific guidance is required.')}
                                    </p>
                                    <Textarea
                                        value={form.response.requiredGuidance}
                                        onChange={e => setForm(f => ({
                                            ...f,
                                            response: { ...f.response, requiredGuidance: e.target.value },
                                        }))}
                                        placeholder={t('Explain how to reset the account password\nDescribe where to find the billing invoice')}
                                        className="min-h-24 flex-1 resize-none overflow-y-auto field-sizing-fixed text-sm"
                                        rows={2}
                                    />
                                </div>

                                <div className="shrink-0 space-y-2">
                                    <Item size="sm" variant="outline" className="px-3 py-2 shadow-sm">
                                        <ItemMedia variant="icon" className="size-7 !self-center !translate-y-0">
                                            <Paperclip className="size-3" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle className="text-xs">{t('Reply composer attachments')}</ItemTitle>
                                            <ItemDescription className="text-xs">{t('Files this runbook makes available to the final ticket composer')}</ItemDescription>
                                        </ItemContent>
                                        <ItemActions>
                                            <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                className="h-7 text-xs px-2"
                                                onClick={() => setAttachmentsDialogOpen(true)}
                                            >
                                                {t('Files')} ({intentFiles.length})
                                            </Button>
                                            <input
                                                ref={fileInputRef}
                                                type="file"
                                                className="hidden"
                                                multiple
                                                onChange={e => handleFileUpload(e.target.files)}
                                            />
                                            <Button
                                                type="button" size="sm" variant="outline"
                                                className="h-7 text-xs px-2"
                                                disabled={uploadingFile || (view === 'new' && !editName)}
                                                onClick={() => fileInputRef.current?.click()}
                                            >
                                                {uploadingFile
                                                    ? <Loader className="size-3 animate-spin" />
                                                    : <Upload className="size-3" />
                                                }
                                                {t('Upload')}
                                            </Button>
                                        </ItemActions>
                                    </Item>
                                </div>
                            </div>
                        </section>
                    </Card>
                </div>

            </div>

            <Dialog open={attachmentsDialogOpen} onOpenChange={setAttachmentsDialogOpen}>
                <DialogContent className="max-h-[85vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>{t('Reply composer attachments')}</DialogTitle>
                        <DialogDescription>{t('Files this runbook supplies to the final ticket composer. Include them always or let the composer decide.')}</DialogDescription>
                    </DialogHeader>
                    {intentFiles.length === 0 ? (
                        <Item variant="outline" size="sm">
                            <ItemMedia variant="icon" className="size-7">
                                <Paperclip className="size-3" />
                            </ItemMedia>
                            <ItemContent>
                                <ItemTitle className="text-xs">{t('No uploaded files')}</ItemTitle>
                                <ItemDescription className="text-xs">{t('Upload files from Customer communication requirements.')}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : (
                        <ItemGroup className="gap-2">
                            {intentFiles.map(file => {
                                const meta = form.response.attachments.find(
                                    a => a.filename === file.filename,
                                );
                                const mode = meta?.mode ?? 'always';
                                const description = meta?.description ?? '';

                                return (
                                    <Item key={file.filename} size="sm" variant="outline" className="gap-1.5 p-2.5">
                                        <ItemHeader>
                                            <ItemContent className="min-w-0 flex-row items-center gap-1.5">
                                                <Paperclip className="size-3 shrink-0 text-muted-foreground" />
                                                <ItemTitle className="min-w-0 flex-1 text-xs">
                                                    <span className="block truncate">{file.filename}</span>
                                                </ItemTitle>
                                                <span className="text-[10px] text-muted-foreground shrink-0">
                                                    {(file.size / 1024).toFixed(0)} KB
                                                </span>
                                            </ItemContent>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon-xs"
                                                onClick={() => handleDeleteFile(file.filename)}
                                                className="shrink-0 text-muted-foreground hover:text-destructive"
                                            >
                                                <X className="size-3.5" />
                                            </Button>
                                        </ItemHeader>
                                        <Input
                                            value={description}
                                            onChange={e => updateResponseAttachment(file.filename, { description: e.target.value })}
                                            placeholder={t('Description (helps the composer decide in dynamic mode)')}
                                            className="h-7 text-xs"
                                        />
                                        <ItemHeader>
                                            <span className="text-[11px] text-muted-foreground">
                                                {t(mode === 'always' ? 'Always include' : 'Composer decides')}
                                            </span>
                                            <ItemActions className="gap-0.5">
                                                {(['always', 'dynamic'] as const).map(m => (
                                                    <Button key={m} type="button" size="sm"
                                                        variant={mode === m ? 'default' : 'outline'}
                                                        className="h-6 text-[10px] px-1.5"
                                                        onClick={() => updateResponseAttachment(file.filename, { mode: m })}>
                                                        {t(m === 'always' ? 'Always' : 'Dynamic')}
                                                    </Button>
                                                ))}
                                            </ItemActions>
                                        </ItemHeader>
                                    </Item>
                                );
                            })}
                        </ItemGroup>
                    )}
                </DialogContent>
            </Dialog>

            <Dialog open={learningsDialogOpen} onOpenChange={setLearningsDialogOpen}>
                <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
                    <DialogHeader>
                        <DialogTitle>{t('Learning review')}</DialogTitle>
                        <DialogDescription>{t('Feedback stays inert. Only an evaluated proposal approved by a project admin changes live behavior.')}</DialogDescription>
                    </DialogHeader>
                    {loadingLearnings ? (
                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <Loader className="size-3 animate-spin" /> {t('Loading...')}
                        </div>
                    ) : (
                        <div className="space-y-5">
                            <section className="space-y-2">
                                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                                    <Lightbulb className="size-3" />
                                    {t('Learning proposals')} ({learningProposals.length})
                                </div>
                                <IntentLearningProposals
                                    proposals={learningProposals}
                                    evalSets={evalSets}
                                    evaluationPath={`/${tenantId}/${projectId}/eval`}
                                    canEdit={canEditLearnings}
                                    canPublish={canPublishLearnings}
                                    busyProposalId={busyProposalId}
                                    onEvaluate={handleEvaluateProposal}
                                    onPublish={handlePublishProposal}
                                    onReject={handleRejectProposal}
                                />
                            </section>

                            <section className="space-y-2 border-t pt-4">
                                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                                    <MessageSquare className="size-3" />
                                    {t('Raw feedbacks')} ({feedbackEntries.length})
                                </div>
                                {feedbackEntries.length === 0 ? (
                                    <Item variant="outline" size="sm">
                                        <ItemMedia variant="icon" className="size-7">
                                            <MessageSquare className="size-3" />
                                        </ItemMedia>
                                        <ItemContent>
                                            <ItemTitle className="text-xs">{t('No raw feedbacks')}</ItemTitle>
                                            <ItemDescription className="text-xs">{t('Feedback appears after users rate add-in results.')}</ItemDescription>
                                        </ItemContent>
                                    </Item>
                                ) : (
                                    <ItemGroup className="gap-1.5">
                                        {feedbackEntries.map(fb => (
                                            <Item key={fb.id} size="sm" variant="outline" className="block p-2 text-xs group">
                                                <ItemHeader>
                                                    <ItemTitle className="text-xs">{fb.user_email}</ItemTitle>
                                                    <ItemActions className="gap-1">
                                                        <span className="text-muted-foreground text-[10px]">
                                                            {new Date(fb.created).toLocaleDateString()}
                                                        </span>
                                                        {canEditLearnings && (
                                                            <Button
                                                                type="button"
                                                                variant="outline"
                                                                size="sm"
                                                                className="h-6 px-2 text-[10px]"
                                                                disabled={derivingFeedbackId !== null}
                                                                onClick={() => void handleLearnFeedback(fb.id)}
                                                            >
                                                                {derivingFeedbackId === fb.id
                                                                    ? <Loader className="size-3 animate-spin" />
                                                                    : <Lightbulb className="size-3" />}
                                                                {t('Learn this')}
                                                            </Button>
                                                        )}
                                                        {canEditLearnings && (
                                                            <Button
                                                                type="button"
                                                                variant="ghost"
                                                                size="icon-xs"
                                                                aria-label={t('Delete feedback')}
                                                                className="opacity-0 transition-opacity text-muted-foreground hover:text-destructive group-hover:opacity-100"
                                                                disabled={derivingFeedbackId !== null || learningProposals.some(proposal => (
                                                                    proposal.source_feedback_id === fb.id
                                                                    && proposal.status !== 'published'
                                                                    && proposal.status !== 'rejected'
                                                                ))}
                                                                title={learningProposals.some(proposal => (
                                                                    proposal.source_feedback_id === fb.id
                                                                    && proposal.status !== 'published'
                                                                    && proposal.status !== 'rejected'
                                                                )) ? t('Reject or publish linked proposals before deleting this evidence.') : undefined}
                                                                onClick={() => handleDeleteFeedback(fb.id)}
                                                            >
                                                                <Trash2 className="size-3" />
                                                            </Button>
                                                        )}
                                                    </ItemActions>
                                                </ItemHeader>
                                                <div className="mt-1 flex flex-wrap gap-1">
                                                    {fb.rating && <Badge variant="outline" className="text-[10px]">{fb.rating}</Badge>}
                                                    {fb.affected_stages.map(stage => (
                                                        <Badge key={stage} variant="secondary" className="text-[10px]">{stage}</Badge>
                                                    ))}
                                                </div>
                                                <ItemDescription className="mt-1.5 text-xs leading-relaxed line-clamp-none">{fb.feedback_text}</ItemDescription>
                                            </Item>
                                        ))}
                                    </ItemGroup>
                                )}
                            </section>
                        </div>
                    )}
                </DialogContent>
            </Dialog>

            {/* ── Action edit dialog ── */}
            {(() => {
                const editAction = editingActionIdx !== null ? regularActions[editingActionIdx] : null;
                if (!editAction) return null;
                const { action, originalIdx } = editAction;
                const onUpdate = (patch: Partial<ActionRow>) => updateAction(originalIdx, patch);
                return (
                    <Dialog open onOpenChange={() => setEditingActionIdx(null)}>
                        <DialogContent className="max-h-[85vh] overflow-y-auto">
                            <DialogHeader>
                                <DialogTitle>{action.label || action.name || t('Edit Action')}</DialogTitle>
                                <DialogDescription>{t('Configure action behavior and webhook settings.')}</DialogDescription>
                            </DialogHeader>

                            <div className="space-y-4 py-2">
                                {/* Type selector */}
                                <div className="space-y-1.5">
                                    <Label className="text-xs">{t('Type')}</Label>
                                    <div className="flex gap-1 flex-wrap">
                                        {(['dropdown', 'calendar', 'input', 'button'] as const).map(t => (
                                            <Button key={t} type="button" size="sm"
                                                variant={action.type === t ? 'default' : 'outline'}
                                                className="h-7 text-xs px-2"
                                                onClick={() => onUpdate({ type: t })}>
                                                {t}
                                            </Button>
                                        ))}
                                    </div>
                                </div>

                                {/* Name + Label */}
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">{t('Label')}</Label>
                                        <Input value={action.label}
                                            onChange={e => onUpdate({ label: e.target.value })}
                                            placeholder="Urgency" className="h-8 text-sm" />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">{t('Name (key)')}</Label>
                                        <Input value={action.name}
                                            onChange={e => onUpdate({ name: e.target.value.toLowerCase().replace(/\s+/g, '-') })}
                                            placeholder="urgency" className="h-8 text-sm font-mono" />
                                    </div>
                                </div>

                                {/* Description */}
                                <div className="space-y-1.5">
                                    <Label className="text-xs">{t('Description')}</Label>
                                    <Textarea
                                        placeholder={t('Describe what this action does (used in tool schema)...')}
                                        className="resize-none text-sm"
                                        rows={2}
                                        value={action.description}
                                        onChange={e => onUpdate({ description: e.target.value })}
                                    />
                                </div>

                                {/* Options — dropdown only */}
                                {action.type === 'dropdown' && (
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">{t('Options')} <span className="font-normal text-muted-foreground">{t('(comma-separated)')}</span></Label>
                                        <Input value={action.options}
                                            onChange={e => onUpdate({ options: e.target.value })}
                                            placeholder="Low, Medium, High" className="h-8 text-sm" />
                                    </div>
                                )}

                                {/* Submit directly toggle — non-button only */}
                                {action.type !== 'button' && (
                                    <div className="flex items-center justify-between gap-3">
                                        <div>
                                            <Label className="text-xs">{t('Submit directly')}</Label>
                                            <p className="text-xs text-muted-foreground">{t('Fire webhook on change instead of collecting with a button')}</p>
                                        </div>
                                        <Switch
                                            checked={action.separateCall}
                                            onCheckedChange={v => onUpdate({ separateCall: v })}
                                        />
                                    </div>
                                )}

                                {/* Webhook + method + headers */}
                                {(action.type === 'button' || action.separateCall) && (
                                    <>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs">{t('Webhook URL')}</Label>
                                            <Input value={action.webhook}
                                                onChange={e => onUpdate({ webhook: e.target.value })}
                                                placeholder="https://internal.example.com/api/endpoint"
                                                className="h-8 text-sm font-mono" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs">{t('Method')}</Label>
                                            <div className="flex gap-1">
                                                {(['POST', 'GET'] as const).map(m => (
                                                    <Button key={m} type="button" size="sm"
                                                        variant={action.method === m ? 'default' : 'outline'}
                                                        className="h-7 text-xs px-2"
                                                        onClick={() => onUpdate({ method: m })}>
                                                        {m}
                                                    </Button>
                                                ))}
                                            </div>
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs">{t('Headers')}</Label>
                                            <IntentToolKVEditor
                                                rows={action.headers}
                                                onChange={rows => onUpdate({ headers: rows })}
                                                addLabel="Add header"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-xs">{t('Query Parameters')}</Label>
                                            <IntentToolKVEditor
                                                rows={action.query}
                                                onChange={rows => onUpdate({ query: rows })}
                                                addLabel="Add query parameter"
                                            />
                                        </div>
                                        {action.method !== 'GET' && (
                                            <div className="space-y-1.5">
                                                <Label className="text-xs">{t('Body')}</Label>
                                                <IntentToolKVEditor
                                                    rows={action.body}
                                                    onChange={rows => onUpdate({ body: rows })}
                                                    addLabel="Add body field"
                                                />
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>

                            <DialogFooter>
                                <Button
                                    type="button" variant="ghost" size="sm"
                                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                                    onClick={() => { removeAction(originalIdx); setEditingActionIdx(null); }}
                                >
                                    <Trash2 className="size-3.5" /> {t('Remove action')}
                                </Button>
                                <Button type="button" onClick={() => setEditingActionIdx(null)}>
                                    {t('Done')}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                );
            })()}

            {/* ── Tool edit dialog ── */}
            {editingToolIdx !== null && form.tools[editingToolIdx] && (() => {
                const tool = form.tools[editingToolIdx];
                const idx = editingToolIdx;
                const inputParameterKeys = tool.inputSchema.map(field => field.key.trim()).filter(Boolean);
                return (
                    <Dialog open onOpenChange={() => setEditingToolIdx(null)}>
                        <DialogContent className="max-h-[85vh] overflow-y-auto">
                            <DialogHeader>
                                <DialogTitle>{tool.name || t('Edit Tool')}</DialogTitle>
                                <DialogDescription>{t('Define the tool description, input parameters, and HTTP endpoint.')}</DialogDescription>
                            </DialogHeader>

                            <div className="space-y-4 py-2">
                                {/* Description */}
                                <div className="space-y-1.5">
                                    <Label className="text-xs">{t('Description')}</Label>
                                    <Textarea
                                        value={tool.description}
                                        onChange={e => updateTool(idx, { description: e.target.value })}
                                        placeholder={t('Describe when the agent should use this tool and what result it returns.')}
                                        className="resize-none text-sm"
                                        rows={2}
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <Label className="text-xs">{t('Tool name')}</Label>
                                    <Input
                                        value={tool.name}
                                        onChange={e => updateTool(idx, { name: e.target.value.toLowerCase().replace(/\s+/g, '-') })}
                                        placeholder="get-claim-status"
                                        className="h-8 text-sm font-mono"
                                    />
                                    <p className="text-xs text-muted-foreground">
                                        {t('Internal key used by the agent. Use lowercase words separated by hyphens.')}
                                    </p>
                                </div>

                                {/* Input schema */}
                                <div className="space-y-1.5">
                                    <Label className="text-xs">{t('Input parameters')}</Label>
                                    <IntentToolSchemaEditor
                                        rows={tool.inputSchema}
                                        onChange={rows => updateTool(idx, { inputSchema: rows })}
                                    />
                                </div>

                                {/* Endpoint */}
                                <div className="space-y-3 rounded-md border p-3">
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">{t('Endpoint')}</Label>
                                        <div className="grid grid-cols-[auto_1fr] gap-2">
                                            <div className="flex gap-1">
                                                {(['GET', 'POST'] as const).map(m => (
                                                    <Button
                                                        key={m}
                                                        type="button"
                                                        size="sm"
                                                        variant={tool.method === m ? 'default' : 'outline'}
                                                        className="h-8 text-xs px-2"
                                                        onClick={() => updateTool(idx, { method: m })}
                                                    >
                                                        {m}
                                                    </Button>
                                                ))}
                                            </div>
                                            <Input
                                                value={tool.urlTemplate}
                                                onChange={e => updateTool(idx, { urlTemplate: e.target.value })}
                                                placeholder="https://api.example.com/claims/{claim_number}"
                                                className={cn(
                                                    'h-8 text-sm font-mono',
                                                    tool.name.trim() && !tool.urlTemplate.trim() && 'border-destructive',
                                                )}
                                            />
                                        </div>
                                        {tool.name.trim() && !tool.urlTemplate.trim() && (
                                            <p className="text-xs text-destructive">{t('Endpoint is required before this tool can be saved.')}</p>
                                        )}
                                    </div>

                                    <div className="space-y-1.5">
                                        <Label className="text-xs">{t('Headers')}</Label>
                                        <IntentToolKVEditor
                                            rows={tool.headers}
                                            onChange={rows => updateTool(idx, { headers: rows })}
                                            addLabel="Add header"
                                        />
                                    </div>

                                    {tool.method === 'POST' && (
                                        <div className="space-y-1.5">
                                            <Label className="text-xs">{t('Body')}</Label>
                                            <IntentToolBodyParameterEditor
                                                rows={tool.body}
                                                onChange={rows => updateTool(idx, { body: rows })}
                                                parameters={inputParameterKeys}
                                            />
                                        </div>
                                    )}
                                </div>

                                <div className="space-y-3 rounded-md border p-3">
                                    <div className="flex items-center justify-between gap-3">
                                        <div>
                                            <Label className="text-xs">{t('Tool returns file')}</Label>
                                            <p className="mt-1 text-xs text-muted-foreground">
                                                {t('Extract a base64 file from the JSON response and make it available to the final ticket composer.')}
                                            </p>
                                        </div>
                                        <Switch
                                            checked={tool.expectsFile}
                                            onCheckedChange={checked => updateTool(idx, { expectsFile: checked })}
                                        />
                                    </div>

                                    {tool.expectsFile && (
                                        <div className="space-y-3">
                                            <div className="flex items-center justify-between gap-3 rounded-md bg-muted/40 p-2">
                                                <div>
                                                    <Label className="text-xs">{t('Make available to composer')}</Label>
                                                    <p className="mt-0.5 text-xs text-muted-foreground">
                                                        {t('Supply the generated file to the final ticket composer automatically.')}
                                                    </p>
                                                </div>
                                                <Switch
                                                    checked={tool.attachToResponse}
                                                    onCheckedChange={checked => updateTool(idx, { attachToResponse: checked })}
                                                />
                                            </div>
                                            <div className="grid gap-3 sm:grid-cols-3">
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs">{t('Filename path')}</Label>
                                                    <Input
                                                        value={tool.fileNamePath}
                                                        onChange={e => updateTool(idx, { fileNamePath: e.target.value })}
                                                        placeholder="document.filename"
                                                        className="h-8 font-mono text-sm"
                                                    />
                                                </div>
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs">{t('Content type path')}</Label>
                                                    <Input
                                                        value={tool.fileContentTypePath}
                                                        onChange={e => updateTool(idx, { fileContentTypePath: e.target.value })}
                                                        placeholder="document.contentType"
                                                        className="h-8 font-mono text-sm"
                                                    />
                                                </div>
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs">{t('Base64 path')}</Label>
                                                    <Input
                                                        value={tool.fileContentBase64Path}
                                                        onChange={e => updateTool(idx, { fileContentBase64Path: e.target.value })}
                                                        placeholder="document.contentBase64"
                                                        className="h-8 font-mono text-sm"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            <DialogFooter>
                                <Button
                                    type="button" variant="ghost" size="sm"
                                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                                    onClick={() => { removeTool(idx); setEditingToolIdx(null); }}
                                >
                                    <Trash2 className="size-3.5" /> {t('Remove tool')}
                                </Button>
                                <Button type="button" onClick={() => setEditingToolIdx(null)}>
                                    {t('Done')}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                );
            })()}
        </div>
    );
};
