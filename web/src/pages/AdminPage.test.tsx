// A member's Admin page used to show the three admin sections anyway - empty lists,
// a disabled field, and a live "Connect an account" link (an anchor ignores `disabled`) that led to
// a 403. A member gets the notice; an admin gets the page.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AdminPage } from "@/pages/AdminPage";
import type { Me } from "@/api/types";

vi.mock("@/api/hooks", () => ({
  useConnections: () => ({ data: { connections: [], warning: "", banner: "" }, isLoading: false }),
  useAllowList: () => ({ data: [] }),
  useActivity: () => ({ data: [] }),
  useAddAllowEntry: () => ({ mutateAsync: vi.fn() }),
  useRemoveAllowEntry: () => ({ mutate: vi.fn() }),
}));

const person = (role: "admin" | "member"): Me => ({
  id: "u-1",
  email: role === "admin" ? "daniel.okafor@example.com" : "noah.s@example.com",
  name: "Somebody",
  role,
  is_admin: role === "admin",
});

describe("AdminPage", () => {
  it("gives a member the notice and nothing they cannot use", () => {
    render(<AdminPage me={person("member")} />);
    expect(screen.getByTestId("admin-members-notice")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect an account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Allow-list" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Activity" })).not.toBeInTheDocument();
  });

  it("gives an admin the three sections", () => {
    render(<AdminPage me={person("admin")} />);
    expect(screen.queryByTestId("admin-members-notice")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect an account" })).toBeInTheDocument();
    for (const name of ["Google connections", "Allow-list", "Activity"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
  });
});
