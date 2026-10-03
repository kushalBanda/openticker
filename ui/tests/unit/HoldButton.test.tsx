import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { HoldButton } from "../../src/components/HoldButton";

describe("HoldButton", () => {
  test("holding for the whole duration confirms once", async () => {
    const confirm = vi.fn(() => Promise.resolve());
    render(<HoldButton label="Hold to close all positions" onConfirm={confirm} durationMs={60} />);
    const button = screen.getByRole("button", { name: /Hold to close all positions/ });

    fireEvent.pointerDown(button);
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  });

  test("letting go early does nothing", async () => {
    const confirm = vi.fn(() => Promise.resolve());
    render(<HoldButton label="Hold to kill" onConfirm={confirm} durationMs={200} />);
    const button = screen.getByRole("button", { name: /Hold to kill/ });

    fireEvent.pointerDown(button);
    await new Promise((done) => setTimeout(done, 50));
    fireEvent.pointerUp(button);
    await new Promise((done) => setTimeout(done, 250));
    expect(confirm).not.toHaveBeenCalled();
  });

  test("space holds like the pointer", async () => {
    const confirm = vi.fn(() => Promise.resolve());
    render(<HoldButton label="Hold to kill" onConfirm={confirm} durationMs={60} />);
    const button = screen.getByRole("button", { name: /Hold to kill/ });

    fireEvent.keyDown(button, { key: " " });
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  });
});
