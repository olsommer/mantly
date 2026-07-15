import pipeline from '@demo/pipelines/insurance-claim.json';
import type { InputSchemaField, ToolConfig } from '@/api/endpoints';

export const DEMO_CRM_TOOL: ToolConfig = {
    ...pipeline.tool,
    inputSchema: pipeline.tool.inputSchema.map((field) => ({
        ...field,
        type: field.type as InputSchemaField['type'],
    })),
};
export const DEMO_INTENT_NAME = pipeline.intent.name;
export const DEMO_INTENT_YAML = pipeline.intent.contentLines.join('\n');
