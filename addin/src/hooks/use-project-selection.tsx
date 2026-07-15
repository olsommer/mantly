/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type ProjectSummary } from "@/api/endpoints";
import { applyTenantBranding } from "@/lib/tenant-branding";

const ACTIVE_PROJECT_KEY = "addin_active_project_id";

interface ProjectSelectionContextValue {
    projects: ProjectSummary[];
    selectedProjectId: string | null;
    selectedProject: ProjectSummary | null;
    loading: boolean;
    setSelectedProjectId: (projectId: string) => void;
    refreshProjects: () => Promise<string | null>;
    resolveProjectId: () => Promise<string | null>;
}

const ProjectSelectionContext = createContext<ProjectSelectionContextValue | undefined>(undefined);

const readStoredProjectId = () => localStorage.getItem(ACTIVE_PROJECT_KEY) || null;

const chooseProjectId = (
    projects: ProjectSummary[],
    preferredProjectId?: string | null,
    defaultProjectId?: string | null,
) => {
    const preferred = preferredProjectId && projects.some((project) => project.id === preferredProjectId)
        ? preferredProjectId
        : null;
    if (preferred) return preferred;

    const defaultProject = defaultProjectId && projects.some((project) => project.id === defaultProjectId)
        ? defaultProjectId
        : null;
    if (defaultProject) return defaultProject;

    return projects[0]?.id ?? null;
};

export function ProjectSelectionProvider({ children }: { children: ReactNode }) {
    const [projects, setProjects] = useState<ProjectSummary[]>([]);
    const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(() => readStoredProjectId());
    const [loading, setLoading] = useState(false);

    const applyProjectId = useCallback((projectId: string | null) => {
        setSelectedProjectIdState(projectId);
        if (projectId) {
            localStorage.setItem(ACTIVE_PROJECT_KEY, projectId);
        } else {
            localStorage.removeItem(ACTIVE_PROJECT_KEY);
        }
    }, []);

    const refreshProjects = useCallback(async () => {
        if (!localStorage.getItem("auth_token") && !localStorage.getItem("admin_auth_token")) {
            setProjects([]);
            applyProjectId(null);
            applyTenantBranding(null);
            return null;
        }

        setLoading(true);
        try {
            const response = await api.getMe();
            if (response.error || !response.data) {
                return readStoredProjectId();
            }

            applyTenantBranding(response.data.branding);
            const nextProjects = response.data.projects ?? [];
            setProjects(nextProjects);
            const nextProjectId = chooseProjectId(
                nextProjects,
                readStoredProjectId(),
                response.data.defaultProject,
            );
            applyProjectId(nextProjectId);
            return nextProjectId;
        } finally {
            setLoading(false);
        }
    }, [applyProjectId]);

    const setSelectedProjectId = useCallback((projectId: string) => {
        applyProjectId(projectId);
    }, [applyProjectId]);

    const resolveProjectId = useCallback(async () => {
        const storedProjectId = readStoredProjectId();
        if (storedProjectId && (projects.length === 0 || projects.some((project) => project.id === storedProjectId))) {
            return storedProjectId;
        }
        return refreshProjects();
    }, [projects, refreshProjects]);

    useEffect(() => {
        void refreshProjects();

        const syncSession = () => void refreshProjects();
        window.addEventListener("auth:session-changed", syncSession);
        window.addEventListener("storage", syncSession);
        return () => {
            window.removeEventListener("auth:session-changed", syncSession);
            window.removeEventListener("storage", syncSession);
        };
    }, [refreshProjects]);

    const selectedProject = useMemo(
        () => projects.find((project) => project.id === selectedProjectId) ?? null,
        [projects, selectedProjectId],
    );

    const value = useMemo<ProjectSelectionContextValue>(() => ({
        projects,
        selectedProjectId,
        selectedProject,
        loading,
        setSelectedProjectId,
        refreshProjects,
        resolveProjectId,
    }), [projects, selectedProjectId, selectedProject, loading, setSelectedProjectId, refreshProjects, resolveProjectId]);

    return (
        <ProjectSelectionContext.Provider value={value}>
            {children}
        </ProjectSelectionContext.Provider>
    );
}

export function useProjectSelection(): ProjectSelectionContextValue {
    const context = useContext(ProjectSelectionContext);
    if (!context) {
        throw new Error("useProjectSelection must be used within ProjectSelectionProvider");
    }
    return context;
}
