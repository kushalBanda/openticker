import { python } from "@codemirror/lang-python";
import { syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { classHighlighter } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { useEffect, useRef } from "react";

// Read-only code and logs (DESIGN.md: @uiw/react-codemirror, read-only).
// Loaded with the first page that shows one, not with the app.

const theme = EditorView.theme({
  "&": {
    color: "var(--ink)",
    backgroundColor: "var(--bg)",
    font: "400 12.5px / 19px var(--font-code)",
    height: "100%",
  },
  ".cm-scroller": { fontFamily: "var(--font-code)", lineHeight: "19px" },
  ".cm-content": { padding: "12px 0", caretColor: "transparent" },
  ".cm-gutters": {
    backgroundColor: "var(--bg)",
    color: "var(--ink-muted)",
    border: "none",
  },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "none" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "var(--surface-hover)",
  },
  ".tok-keyword": { color: "var(--link)" },
  ".tok-string, .tok-string2": { color: "var(--up)" },
  ".tok-comment": { color: "var(--ink-muted)", fontStyle: "italic" },
  ".tok-number": { color: "var(--warn)" },
});

const setup = {
  lineNumbers: true,
  foldGutter: false,
  highlightActiveLine: false,
  highlightActiveLineGutter: false,
  highlightSelectionMatches: false,
  autocompletion: false,
  syntaxHighlighting: false, // colours come from our tokens, below
  searchKeymap: true,
};

/**
 * Text nobody edits here. `follow`: a log still growing keeps its end in
 * view, unless the reader has scrolled up to read.
 */
export function CodeView({
  text,
  language,
  follow = false,
  label,
}: {
  text: string;
  language: "python" | "log";
  follow?: boolean;
  label: string;
}) {
  const view = useRef<EditorView | null>(null);
  const atEnd = useRef(true);

  useEffect(() => {
    const editor = view.current;
    if (!follow || !editor || !atEnd.current || !text) return;
    editor.dispatch({ effects: EditorView.scrollIntoView(editor.state.doc.length, { y: "end" }) });
  }, [text, follow]);

  return (
    <div className="code-view" data-testid={`code-${language}`}>
      <CodeMirror
        value={text}
        readOnly
        editable={false}
        style={{ height: "100%" }}
        basicSetup={setup}
        theme="none"
        extensions={[
          theme,
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ "aria-label": label }),
          EditorView.domEventHandlers({
            scroll: (_, editor) => {
              const box = editor.scrollDOM;
              atEnd.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
            },
          }),
          ...(language === "python" ? [python(), syntaxHighlighting(classHighlighter)] : []),
        ]}
        onCreateEditor={(editor) => {
          view.current = editor;
        }}
        height="100%"
      />
    </div>
  );
}
