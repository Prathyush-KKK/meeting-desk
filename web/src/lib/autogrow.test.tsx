import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useAutoGrow } from "./autogrow";

// jsdom has no layout, so scrollHeight is given the only thing that matters here: 20 px a line.
const LINE = 20;
let restore: PropertyDescriptor | undefined;
beforeEach(() => {
  restore = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "scrollHeight");
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return Math.max(2, this.value.split("\n").length) * LINE;
    },
  });
});
afterEach(() => {
  if (restore) Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", restore);
  else delete (HTMLTextAreaElement.prototype as { scrollHeight?: number }).scrollHeight;
});

function Box({ max }: { max: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  useAutoGrow(ref, value, max);
  return <textarea aria-label="paste" ref={ref} rows={2} value={value} onChange={(e) => setValue(e.target.value)} />;
}

describe("useAutoGrow", () => {
  it("grows the box with each pasted line instead of scrolling it", () => {
    render(<Box max={200} />);
    const box = screen.getByLabelText("paste") as HTMLTextAreaElement;
    expect(box.style.height).toBe("40px");
    fireEvent.change(box, { target: { value: "a\nb\nc\nd\ne" } });
    expect(box.style.height).toBe("100px");
    expect(box.style.overflowY).toBe("hidden");
  });

  it("stops at the cap and scrolls from there", () => {
    render(<Box max={120} />);
    const box = screen.getByLabelText("paste") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n") } });
    expect(box.style.height).toBe("120px");
    expect(box.style.overflowY).toBe("auto");
  });

  it("shrinks back when the text goes", () => {
    render(<Box max={200} />);
    const box = screen.getByLabelText("paste") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "a\nb\nc\nd" } });
    fireEvent.change(box, { target: { value: "" } });
    expect(box.style.height).toBe("40px");
  });
});
