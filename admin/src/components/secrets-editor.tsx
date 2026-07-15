import { useCallback, useEffect, useState } from 'react';
import { Eye, EyeOff, Loader, Plus, Save, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ApiResponse } from '@/api/client';
import { useI18n } from '@/lib/i18n-context';

// ── Types ─────────────────────────────────────────────────────────────────────

interface SecretRow {
    key: string;
    value: string;
    isNew: boolean;
}

interface SecretsEditorProps {
    title: string;
    description: string;
    /** Fetches the current (masked) secrets from the API. */
    load: () => Promise<ApiResponse<Record<string, string>>>;
    /** Saves updated secrets to the API. Returns the updated (masked) values. */
    save: (secrets: Record<string, string>) => Promise<ApiResponse<Record<string, string>>>;
}

// ── Component ─────────────────────────────────────────────────────────────────

export const SecretsEditor = ({ title, description, load, save }: SecretsEditorProps) => {
    const [rows, setRows] = useState<SecretRow[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());
    const { t } = useI18n();

    const refresh = useCallback(() => {
        void load().then(res => {
            if (res.data) {
                setRows(
                    Object.entries(res.data).map(([key, value]) => ({
                        key,
                        value,
                        isNew: false,
                    })),
                );
            }
            setLoading(false);
        });
    }, [load]);

    useEffect(() => {
        refresh();
    }, [refresh]);

    const updateRow = (i: number, field: 'key' | 'value', val: string) => {
        setRows(prev =>
            prev.map((r, idx) =>
                idx === i ? { ...r, [field]: field === 'key' ? val.toUpperCase().replace(/\s+/g, '_') : val } : r,
            ),
        );
    };

    const removeRow = (i: number) => {
        const removed = rows[i];
        setRows(prev => prev.filter((_, idx) => idx !== i));
        setVisibleKeys(prev => {
            const next = new Set(prev);
            next.delete(removed.key);
            return next;
        });
    };

    const addRow = () => {
        setRows(prev => [...prev, { key: '', value: '', isNew: true }]);
    };

    const toggleVisibility = (key: string) => {
        setVisibleKeys(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const handleSave = async () => {
        // Validate: no empty keys, no duplicate keys
        const keys = rows.map(r => r.key).filter(Boolean);
        if (keys.length !== new Set(keys).size) {
            toast.error(t('Duplicate keys are not allowed'));
            return;
        }
        if (rows.some(r => !r.key.trim())) {
            toast.error(t('All secrets must have a key'));
            return;
        }

        setSaving(true);
        const payload: Record<string, string> = {};
        for (const row of rows) {
            if (row.key.trim()) payload[row.key] = row.value;
        }
        const res = await save(payload);
        if (res.error) {
            toast.error(t('Failed to save secrets: {error}', { error: res.error }));
        } else {
            toast.success(t('Secrets saved'));
            if (res.data) {
                setRows(
                    Object.entries(res.data).map(([key, value]) => ({
                        key,
                        value,
                        isNew: false,
                    })),
                );
            }
            setVisibleKeys(new Set());
        }
        setSaving(false);
    };

    if (loading) {
        return (
            <Card>
                <CardHeader>
                    <h3 className="text-base font-semibold">{title}</h3>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader className="size-4 animate-spin" /> {t('Loading')}...
                    </div>
                </CardContent>
            </Card>
        );
    }

    return (
        <Card>
            <CardHeader>
                <h3 className="text-base font-semibold">{title}</h3>
                <p className="text-sm text-muted-foreground">{description}</p>
            </CardHeader>
            <CardContent className="space-y-3">
                {rows.length === 0 && (
                    <p className="text-sm text-muted-foreground italic">{t('No secrets configured.')}</p>
                )}

                {rows.map((row, i) => (
                    <div key={i} className="flex gap-2 items-center">
                        <div className="space-y-1 flex-1">
                            {i === 0 && <Label className="text-xs text-muted-foreground">{t('Key')}</Label>}
                            <Input
                                value={row.key}
                                onChange={e => updateRow(i, 'key', e.target.value)}
                                placeholder="MY_API_KEY"
                                className="font-mono text-sm"
                                disabled={!row.isNew}
                            />
                        </div>
                        <div className="space-y-1 flex-[2]">
                            {i === 0 && <Label className="text-xs text-muted-foreground">{t('Value')}</Label>}
                            <div className="flex gap-1">
                                <Input
                                    type={visibleKeys.has(row.key) || row.isNew ? 'text' : 'password'}
                                    value={row.value}
                                    onChange={e => updateRow(i, 'value', e.target.value)}
                                    placeholder={t('secret value')}
                                    className="flex-1 font-mono text-sm"
                                />
                                {!row.isNew && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="shrink-0"
                                        onClick={() => toggleVisibility(row.key)}
                                    >
                                        {visibleKeys.has(row.key) ? (
                                            <EyeOff className="size-4" />
                                        ) : (
                                            <Eye className="size-4" />
                                        )}
                                    </Button>
                                )}
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="shrink-0 text-muted-foreground hover:text-destructive"
                                    onClick={() => removeRow(i)}
                                >
                                    <Trash2 className="size-4" />
                                </Button>
                            </div>
                        </div>
                    </div>
                ))}

                <div className="flex items-center gap-2 pt-1">
                    <Button variant="outline" size="sm" onClick={addRow} type="button">
                        <Plus className="size-4" /> {t('Add secret')}
                    </Button>
                    {rows.length > 0 && (
                        <Button size="sm" onClick={handleSave} disabled={saving}>
                            {saving ? <Loader className="size-4 animate-spin" /> : <Save className="size-4" />}
                            {t('Save secrets')}
                        </Button>
                    )}
                </div>

                <p className="text-xs text-muted-foreground">
                    {t('Reference secrets in tool headers, body, or URL as')}{' '}
                    <code className="bg-muted px-1 rounded">{'{KEY_NAME}'}</code>.
                    {' '}{t('Saved values are masked for security.')}
                </p>
            </CardContent>
        </Card>
    );
};
