import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup); // vitest runs without globals, so Testing Library can't do it itself

// jsdom lays nothing out: a list keeping its active row in view has nothing to scroll.
Element.prototype.scrollIntoView ??= () => {};
