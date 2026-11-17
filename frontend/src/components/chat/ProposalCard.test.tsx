// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import ProposalCard from "./ProposalCard";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function render(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(node);
    await Promise.resolve();
  });
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
});

const commitProposal = {
  action: "github_commit_files",
  system: "github",
  description: "Commit 2 files",
  params: {
    repo_id: "acme/shop",
    branch: "feat/cart",
    message: "feat: add cart",
    files: [
      { path: "src/cart.ts", content: "export const a = 1;\nexport const b = 2;" },
      { path: "src/util.ts", content: "export {};" },
    ],
  },
};

const noop = () => {};

describe("ProposalCard", () => {
  it("renders a files table with commit context and closed code", async () => {
    await render(
      <ProposalCard proposal={commitProposal} onApprove={noop} onReject={noop} isLoading={false} />,
    );
    const heads = Array.from(container.querySelectorAll("th")).map((t) => t.textContent);
    // No review summaries yet, so the "What it does" column is hidden.
    expect(heads).toEqual(["File path", "Lines"]);
    expect(container.textContent).not.toContain("What it does");
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelectorAll("td")).toHaveLength(2);
    expect(rows[0].textContent).toContain("src/cart.ts");
    expect(rows[0].querySelectorAll("td")[1].textContent).toBe("2");
    expect(container.textContent).toContain("Repo: acme/shop");
    expect(container.textContent).toContain("Branch: feat/cart");
    expect(container.textContent).toContain("Commit message: feat: add cart");
    const details = container.querySelectorAll("details");
    expect(details).toHaveLength(2);
    details.forEach((d) => expect(d.open).toBe(false));
    expect(container.querySelector("details pre")?.textContent).toContain("export const a");
    expect(container.querySelector("details pre")?.className).toContain("max-h-96");
  });

  it("shows the review summary by path and a dash when missing", async () => {
    await render(
      <ProposalCard
        proposal={commitProposal}
        onApprove={noop}
        onReject={noop}
        isLoading={false}
        fileSummaries={[{ path: "src/cart.ts", summary: "Adds the cart reducer" }]}
      />,
    );
    const heads = Array.from(container.querySelectorAll("th")).map((t) => t.textContent);
    expect(heads).toEqual(["File path", "Lines", "What it does"]);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].querySelectorAll("td")[2].textContent).toBe("Adds the cart reducer");
    expect(rows[1].querySelectorAll("td")[2].textContent).toBe("—");
  });

  it("hides the summary column when the summaries match none of the files", async () => {
    await render(
      <ProposalCard
        proposal={commitProposal}
        onApprove={noop}
        onReject={noop}
        isLoading={false}
        fileSummaries={[{ path: "somewhere/else.ts", summary: "Unrelated" }]}
      />,
    );
    const heads = Array.from(container.querySelectorAll("th")).map((t) => t.textContent);
    expect(heads).toEqual(["File path", "Lines"]);
    expect(container.textContent).not.toContain("Unrelated");
  });

  it("omits context lines that are absent", async () => {
    const p = { ...commitProposal, params: { files: commitProposal.params.files } };
    await render(<ProposalCard proposal={p} onApprove={noop} onReject={noop} isLoading={false} />);
    expect(container.textContent).not.toContain("Repo:");
    expect(container.textContent).not.toContain("Branch:");
    expect(container.textContent).not.toContain("Commit message:");
  });

  it("keeps key/value rendering for non-file proposals", async () => {
    const p = {
      action: "jira_create_issue",
      system: "jira",
      description: "Create issue",
      params: { project: "ABC", summary: "Fix login" },
    };
    await render(<ProposalCard proposal={p} onApprove={noop} onReject={noop} isLoading={false} />);
    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain("project: ABC");
    expect(container.textContent).toContain("summary: Fix login");
  });

  it("still wires approve and reject, and shows the result message", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    await render(
      <ProposalCard proposal={commitProposal} onApprove={onApprove} onReject={onReject} isLoading={false} />,
    );
    const buttons = Array.from(container.querySelectorAll("button"));
    await act(async () => {
      buttons.find((b) => b.textContent === "Approve")!.click();
      buttons.find((b) => b.textContent === "Reject")!.click();
    });
    expect(onApprove).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();

    act(() => root.unmount());
    container.remove();
    await render(
      <ProposalCard
        proposal={commitProposal}
        onApprove={noop}
        onReject={noop}
        isLoading={false}
        result={{ success: true, message: "Committed" }}
      />,
    );
    expect(container.textContent).toBe("Committed");
  });
});
