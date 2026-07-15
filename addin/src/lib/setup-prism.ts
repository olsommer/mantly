// @lexical/code (transitive dep of MDXEditor) expects Prism on globalThis.
import Prism from 'prismjs';

(globalThis as Record<string, unknown>).Prism = Prism;
