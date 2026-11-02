// Vitest runs in UTC (vite.config.ts); note times must still show in America/New_York.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RequestNotes } from "./RequestNotes";

describe("notes on the request detail", () => {
  it("lists each note oldest first with who, when, the text and an urgent marker", () => {
    render(
      <RequestNotes
        notes={[
          {
            at: "2026-11-01T20:04:00Z",
            author_type: "agent",
            author: null,
            text: "use the north gate",
            urgent: false,
          },
          {
            at: "2026-11-01T20:06:00Z",
            author_type: "staff",
            author: "Pat Lee",
            text: "need an answer today",
            urgent: true,
          },
        ]}
      />,
    );

    const items = within(screen.getByRole("list", { name: "Notes" })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("use the north gate");
    expect(items[0]).toHaveTextContent("Agent");
    expect(items[0]).toHaveTextContent("Sun, Nov 1, 3:04 PM");
    expect(within(items[0]).queryByText("Urgent")).toBeNull();
    expect(items[1]).toHaveTextContent("need an answer today");
    expect(items[1]).toHaveTextContent("Pat Lee");
    expect(within(items[1]).getByText("Urgent")).toBeInTheDocument();
  });

  it("says there are none", () => {
    render(<RequestNotes notes={[]} />);

    expect(screen.getByText("No notes.")).toBeInTheDocument();
  });
});
