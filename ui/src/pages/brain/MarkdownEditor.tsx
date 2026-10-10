import { markdown } from "@codemirror/lang-markdown";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";

// The user's own note, as markdown. Loaded with the first editor opened, not
// with the app.

const theme = EditorView.theme({
  "&": {
    color: "var(--ink)",
    backgroundColor: "var(--bg)",
    font: "400 13px / 20px var(--font-code)",
    borderRadius: "var(--radius-md)",
  },
  ".cm-scroller": { fontFamily: "var(--font-code)", lineHeight: "20px" },
  ".cm-content": { padding: "10px 12px", caretColor: "var(--ink)", minHeight: "120px" },
  "&.cm-focused": { outline: "2px solid var(--focus)", outlineOffset: "1px" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "var(--surface-hover)",
  },
  ".cm-placeholder": { color: "var(--ink-muted)" },
});

const setup = {
  lineNumbers: false,
  foldGutter: false,
  highlightActiveLine: false,
  highlightActiveLineGutter: false,
  highlightSelectionMatches: false,
  autocompletion: false,
  searchKeymap: true,
};

export function MarkdownEditor({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (text: string) => void;
  label: string;
}) {
  return (
    <div className="markdown-editor">
      <CodeMirror
        value={value}
        onChange={onChange}
        autoFocus
        basicSetup={setup}
        theme="none"
        placeholder="What you saw, what you'd do differently. [[day:2026-10-05]] links a day."
        extensions={[
          theme,
          markdown(),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ "aria-label": label }),
        ]}
      />
    </div>
  );
}
