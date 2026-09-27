import { type ReactNode, useEffect, useRef, useState } from "react";
import { useBarTitle } from "../shell/title";

const BAR_HEIGHT = 44;

/**
 * A page: its large title (which settles into the bar on scroll), then its
 * content. `count` follows the title, Kite's way: Positions (5).
 */
export function Page({
  title,
  count,
  actions,
  children,
}: {
  title: string;
  count?: number;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [tucked, setTucked] = useState(false);
  const { set } = useBarTitle();

  useEffect(() => {
    document.title = `${title} · OpenTicker`;
  }, [title]);

  useEffect(() => {
    const element = heading.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        const under =
          entry !== undefined && !entry.isIntersecting && entry.boundingClientRect.top < BAR_HEIGHT;
        setTucked(under);
        set(title, under);
      },
      { rootMargin: `-${BAR_HEIGHT}px 0px 0px 0px` },
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      set("", false);
    };
  }, [title, set]);

  return (
    <main className="page">
      <div className="page-head">
        <h1 ref={heading} className="page-title" data-tucked={tucked}>
          {title}
          {count !== undefined && <span className="count"> ({count})</span>}
        </h1>
        <span className="flex-1" />
        {actions}
      </div>
      {children}
    </main>
  );
}
