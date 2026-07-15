import { MDXEditor, headingsPlugin, listsPlugin, thematicBreakPlugin, markdownShortcutPlugin, linkPlugin, linkDialogPlugin, tablePlugin } from '@mdxeditor/editor';
import '@mdxeditor/editor/style.css'

type Props = {
    markdown: string;
    setMarkdown: (markdown: string) => void;
    readOnly?: boolean;
}

export const Editor = ({ markdown, setMarkdown, readOnly = false }: Props) => {
    // Ensure markdown is always a string
    const safeMarkdown = typeof markdown === 'string' ? markdown : '';

    const plugins = [
        headingsPlugin(),
        listsPlugin(),
        thematicBreakPlugin(),
        markdownShortcutPlugin(),
        linkPlugin(),
        linkDialogPlugin(),
        tablePlugin(),
    ];

    return (
        <MDXEditor
            markdown={safeMarkdown}
            onChange={setMarkdown}
            plugins={plugins}
            contentEditableClassName="prose prose-sm max-w-none !px-0 !py-0 text-xs leading-relaxed"
            readOnly={readOnly}
            className="[&_.mdxeditor-toolbar]:static [&_.mdxeditor-toolbar]:top-auto"
        />
    );
}
