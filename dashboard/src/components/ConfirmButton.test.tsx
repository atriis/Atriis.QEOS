import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfirmButton from "./ConfirmButton";

function setup() {
  const onConfirm = vi.fn();
  render(
    <ConfirmButton
      label="Revoke"
      ariaLabel="Revoke key ci"
      question="Revoke key ci? Uploads using it stop working immediately."
      confirmLabel="Revoke"
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

test("the first click only asks; the confirm button takes focus", async () => {
  const onConfirm = setup();
  await userEvent.click(screen.getByRole("button", { name: "Revoke key ci" }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(screen.getByText(/uploads using it stop working/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Revoke" })).toHaveFocus();
});

test("confirming runs the action once", async () => {
  const onConfirm = setup();
  await userEvent.click(screen.getByRole("button", { name: "Revoke key ci" }));
  await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

test("cancel and Escape back out and return focus to the trigger", async () => {
  const onConfirm = setup();
  await userEvent.click(screen.getByRole("button", { name: "Revoke key ci" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Revoke key ci" })).toHaveFocus();

  await userEvent.click(screen.getByRole("button", { name: "Revoke key ci" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "Revoke key ci" })).toHaveFocus();
  expect(onConfirm).not.toHaveBeenCalled();
});

test("inside a form, no button of the confirm flow submits it", async () => {
  const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
  render(
    <form onSubmit={onSubmit}>
      <ConfirmButton label="Delete" question="Delete it?" confirmLabel="Yes, delete" onConfirm={() => {}} />
    </form>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onSubmit).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
  expect(onSubmit).not.toHaveBeenCalled();
});

test("a consequential save can confirm in primary, with its own back-out word", async () => {
  render(
    <ConfirmButton label="Save" triggerClassName="primary" question="Everyone sees this." confirmLabel="Save for everyone"
      confirmClassName="primary" cancelLabel="Back" onConfirm={() => {}} />,
  );
  expect(screen.getByRole("button", { name: "Save" })).toHaveClass("primary");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("button", { name: "Save for everyone" })).toHaveClass("primary");
  expect(screen.getByRole("button", { name: "Save for everyone" })).not.toHaveClass("danger");
  expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
});
