import { FolderKanban } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProjectSelection } from "@/hooks/use-project-selection";
import { t } from "@/lib/i18n";

export function AddinProjectSelector() {
    const { projects, selectedProjectId, setSelectedProjectId, loading } = useProjectSelection();

    if (projects.length <= 1) {
        return null;
    }

    return (
        <div className="flex min-w-0 items-center gap-1.5">
            <FolderKanban className="size-3.5 shrink-0 text-muted-foreground" />
            <Select
                value={selectedProjectId ?? undefined}
                onValueChange={setSelectedProjectId}
                disabled={loading}
            >
                <SelectTrigger className="h-8 w-[9.5rem] px-2 text-xs">
                    <SelectValue placeholder={t('pipeline.project')} />
                </SelectTrigger>
                <SelectContent align="end" side="top">
                    {projects.map((project) => (
                        <SelectItem key={project.id} value={project.id}>
                            {project.name}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
}
