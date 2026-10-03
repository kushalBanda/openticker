import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { OrderDialog } from "../components/OrderDialog";
import type { Order, OrderDraft } from "../lib/orders";
import { useLive } from "../stream/StreamProvider";
import { CommandPalette } from "./CommandPalette";
import { useToast } from "./toasts";

interface Actions {
  /** Opens the order window with this order filled in. */
  order(draft: OrderDraft): void;
  /** Opens the order window on a resting order, to change it. */
  modify(order: Order): void;
  /** Opens ⌘K. */
  search(): void;
  /** Says how something went, in a toast. */
  notify(message: string): void;
}

const ActionsContext = createContext<Actions | null>(null);

export function useActions(): Actions {
  const actions = useContext(ActionsContext);
  if (actions === null) throw new Error("useActions needs an ActionsProvider");
  return actions;
}

interface Open {
  draft: OrderDraft;
  orderId?: string;
  id: number;
}

const draftOf = (order: Order): OrderDraft => ({
  symbol: order.symbol,
  exchange: order.exchange,
  side: order.side,
  quantity: order.quantity,
  product: order.product,
  orderType: order.order_type,
  price: order.price ?? undefined,
  triggerPrice: order.trigger_price ?? undefined,
});

/** The app-wide ways to trade: the order window, ⌘K, and the toast that says how it went. */
export function ActionsProvider({ children }: { children: ReactNode }) {
  const { status } = useLive();
  const [searching, setSearching] = useState(false);
  const [dialog, setDialog] = useState<Open | null>(null);
  const toast = useToast();
  const opened = useRef(0);
  // Kept after closing, so the dialog can leave the way it came.
  const last = useRef<Open | null>(null);
  if (dialog) last.current = dialog;

  const notify = useCallback((text: string) => toast({ text }), [toast]);
  const actions = useMemo<Actions>(
    () => ({
      order: (draft) => setDialog({ draft, id: ++opened.current }),
      modify: (order) =>
        setDialog({ draft: draftOf(order), orderId: order.order_id, id: ++opened.current }),
      search: () => setSearching(true),
      notify,
    }),
    [notify],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearching((was) => !was);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const shown = last.current;
  const close = useCallback(() => setDialog(null), []);
  const done = useCallback(
    (text: string) => {
      setDialog(null);
      notify(text);
    },
    [notify],
  );

  return (
    <ActionsContext.Provider value={actions}>
      {children}
      <CommandPalette
        open={searching}
        onClose={() => setSearching(false)}
        onOrder={actions.order}
      />
      {shown && status && (
        <OrderDialog
          key={shown.id}
          open={dialog !== null}
          draft={shown.draft}
          orderId={shown.orderId}
          broker={status.broker}
          marketOpen={status.market_open}
          onClose={close}
          onDone={done}
        />
      )}
    </ActionsContext.Provider>
  );
}
