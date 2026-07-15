import { createContext, useContext } from 'react';

/** Lets child routes inject breadcrumb and action buttons into the top bar. */
export interface TopBarContextValue {
    setBreadcrumb: (node: React.ReactNode | null) => void;
    setActions: (node: React.ReactNode | null) => void;
}

export const TopBarContext = createContext<TopBarContextValue>({
    setBreadcrumb: () => {},
    setActions: () => {},
});

export const useTopBar = () => useContext(TopBarContext);
