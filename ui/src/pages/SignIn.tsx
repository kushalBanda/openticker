import { Check, Copy } from "lucide-react";
import { useState } from "react";

const COMMAND = "openticker-serve ui login";

/** Shown when this browser isn't signed in: how to get a sign-in link. */
export function SignIn() {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(COMMAND);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="grid min-h-screen place-items-center">
      <div className="tile w-[440px]">
        <div className="wordmark mb-5">OpenTicker</div>
        <h1 className="m-0 mb-2.5 font-display text-[28px] leading-[34px] font-semibold tracking-[-0.025em]">
          Sign in with a link from your terminal
        </h1>
        <p className="m-0 mb-4 text-ink-muted">
          openticker-serve prints a sign-in link when it starts. It works once, for 10 minutes. For
          a fresh one, run:
        </p>
        <div className="command-line">
          <span className="flex-1">{COMMAND}</span>
          <button
            type="button"
            className="bar-button"
            onClick={copy}
            aria-label={copied ? "Copied" : "Copy command"}
          >
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          </button>
        </div>
        <p className="m-0 mt-4 text-[12.5px] leading-[18px] text-ink-muted">
          OpenTicker only listens on this computer. Nobody else on your network can open it.
        </p>
      </div>
    </div>
  );
}
