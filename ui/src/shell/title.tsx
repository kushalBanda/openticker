import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

// apple.com's large title: the page's 34px title, once it scrolls under the
// glass bar, shows in the bar instead (DESIGN.md, Scroll effects).

interface BarTitle {
  title: string;
  shown: boolean;
  set: (title: string, shown: boolean) => void;
}

const BarTitleContext = createContext<BarTitle>({ title: "", shown: false, set: () => undefined });

export function BarTitleProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState({ title: "", shown: false });
  const set = useCallback((title: string, shown: boolean) => setState({ title, shown }), []);
  return <BarTitleContext.Provider value={{ ...state, set }}>{children}</BarTitleContext.Provider>;
}

export function useBarTitle(): BarTitle {
  return useContext(BarTitleContext);
}
