import { normalizeRepo, repoError } from "./ciTargetFields";

test.each([
  ["acme/obt", "acme/obt"],
  ["  acme/obt  ", "acme/obt"],
  ["acme / obt", "acme/obt"],
  ["https://github.com/acme/obt", "acme/obt"],
  ["https://github.com/acme/obt.git", "acme/obt"],
  ["https://www.github.com/acme/obt/", "acme/obt"],
  ["http://github.com/acme/obt/tree/main/src", "acme/obt"],
  ["github.com/acme/obt", "acme/obt"],
  ["git@github.com:acme/obt.git", "acme/obt"],
  ["acme/obt.git", "acme/obt"],
  ["acme/my.repo", "acme/my.repo"],
])("normalizeRepo(%j) is %j", (input, expected) => {
  expect(normalizeRepo(input)).toBe(expected);
});

test("other hosts and odd input are left for the validator to refuse", () => {
  expect(normalizeRepo("https://gitlab.com/acme/obt")).toBe("https://gitlab.com/acme/obt");
  expect(repoError(normalizeRepo("https://gitlab.com/acme/obt"))).not.toBeNull();
  expect(normalizeRepo("acme\\obt")).toBe("acme\\obt");
});

test("an owner alone asks for the repository name", () => {
  expect(repoError("acme")).toBe("Add the repository name after the owner: owner/name");
  expect(repoError(normalizeRepo("https://github.com/acme"))).toBe("Add the repository name after the owner: owner/name");
});

test("empty and malformed values get their own messages", () => {
  expect(repoError("")).toBe("Enter the repository as owner/name");
  expect(repoError("acme/obt/extra")).toBe("Use owner/name, as in the repository's github.com address");
  expect(repoError("ac me/obt")).toBe("Use owner/name, as in the repository's github.com address");
  expect(repoError("acme/obt")).toBeNull();
});
