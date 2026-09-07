// Validator fixtures for frontend/validate.js. Pure functions, no DOM.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  fragmentIdKey,
  validate,
  validateChatInput,
  validateConversationTitle,
  validateEditMessage,
} from "../../frontend/validate.js";

test("fragmentIdKey folds case and separators so near-duplicate ids compare equal", () => {
  assert.equal(fragmentIdKey("User-Intent_Hypothesis"), "userintenthypothesis");
  assert.equal(fragmentIdKey("user-intent"), fragmentIdKey("user_intent"));
  assert.notEqual(fragmentIdKey("user-intent"), fragmentIdKey("user-intents"));
  assert.equal(fragmentIdKey(null), "");
  assert.equal(validate.fragmentIdKey, fragmentIdKey);
});

test("validateChatInput rejects empty / whitespace", () => {
  assert.equal(validateChatInput("").valid, false);
  assert.equal(validateChatInput("   ").valid, false);
});

test("validateChatInput accepts normal text", () => {
  assert.equal(validateChatInput("hello").valid, true);
});

test("validateChatInput rejects over-limit input", () => {
  assert.equal(validateChatInput("x".repeat(100001)).valid, false);
  assert.equal(validateChatInput("x".repeat(100000)).valid, true);
});

test("validateEditMessage is the exact same implementation as validateChatInput (alias)", () => {
  // The dedupe: one function, two names. Identity check guards against a future
  // divergent copy sneaking back in.
  assert.equal(validateEditMessage, validateChatInput);
  assert.equal(validate.validateEditMessage, validateChatInput);
});

test("validateConversationTitle rejects empty and over-limit", () => {
  assert.equal(validateConversationTitle("").valid, false);
  assert.equal(validateConversationTitle("A nice title").valid, true);
  assert.equal(validateConversationTitle("x".repeat(101)).valid, false);
});

test("the validate barrel exposes the domain validators", () => {
  for (const name of ["validateChatInput", "validateEditMessage", "validateCharacterName", "validateConversationTitle"]) {
    assert.equal(typeof validate[name], "function", `validate.${name} missing`);
  }
});
