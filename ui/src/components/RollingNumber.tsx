import NumberFlow from "@number-flow/react";
import { type ComponentProps, useEffect, useState } from "react";

/**
 * A figure whose digits roll to each new value (NumberFlow), drawn afresh
 * whenever the tab comes back into view. A background tab holds the browser's
 * animations pending until it is shown again, and NumberFlow's rolls started
 * before it was hidden then resume against digits that changed meanwhile,
 * leaving old and new digits half-rolled over each other until a reload.
 */
export function RollingNumber(props: ComponentProps<typeof NumberFlow>) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const onChange = () => {
      if (document.visibilityState === "visible") setShown((n) => n + 1);
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return <NumberFlow key={shown} {...props} />;
}
