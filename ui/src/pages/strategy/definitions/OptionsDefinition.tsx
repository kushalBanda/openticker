import { CopyLine } from "../../../components/CopyLine";
import { changePrompt, type OptionsDefinition, optionsLines } from "../../../lib/strategies";
import { DefinitionLines } from "./SignalDefinition";

/** An options strategy's rules: legs chosen relative to the market (ADR 20). */
export function OptionsDefinitionCard({
  definition,
  strategy,
}: {
  definition: OptionsDefinition;
  strategy: { name: string; strategy_id: string };
}) {
  return (
    <div className="tile" data-testid="definition">
      <h2 className="tile-title">Definition</h2>
      <DefinitionLines lines={optionsLines(definition)} />
      <div style={{ marginTop: 16 }}>
        <CopyLine text={changePrompt(strategy)} label="Copy the request for your agent" />
      </div>
      <p className="note" style={{ margin: "6px 0 0" }}>
        Edits happen through your agent. Copy this and tell it what to change.
      </p>
    </div>
  );
}
