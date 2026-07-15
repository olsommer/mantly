import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
    getStoredLocale,
    LOCALE_EVENT,
    normalizeLocale,
    STORAGE_KEY,
    translate,
    type Locale,
} from './i18n-core';
import { I18nContext, type I18nContextValue } from './i18n-context';

export function I18nProvider({ children }: { children: ReactNode }) {
    const [locale, setLocaleState] = useState<Locale>(() => getStoredLocale());

    const setLocale = useCallback((next: Locale) => {
        setLocaleState(next);
        localStorage.setItem(STORAGE_KEY, next);
        window.dispatchEvent(new CustomEvent(LOCALE_EVENT, { detail: next }));
    }, []);

    useEffect(() => {
        const handleStorage = (event: StorageEvent) => {
            if (event.key === STORAGE_KEY) {
                setLocaleState(normalizeLocale(event.newValue));
            }
        };
        const handleLocale = (event: Event) => {
            const detail = (event as CustomEvent<unknown>).detail;
            setLocaleState(normalizeLocale(detail));
        };
        window.addEventListener('storage', handleStorage);
        window.addEventListener(LOCALE_EVENT, handleLocale);
        return () => {
            window.removeEventListener('storage', handleStorage);
            window.removeEventListener(LOCALE_EVENT, handleLocale);
        };
    }, []);

    const value = useMemo<I18nContextValue>(() => ({
        locale,
        setLocale,
        t: (key, values) => translate(locale, key, values),
    }), [locale, setLocale]);

    return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
