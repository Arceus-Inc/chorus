---
name: forms-and-validation
description: How to build accessible forms that validate well — labels tied to inputs, inline error messaging wired to the control, required/invalid state exposed to assistive tech, and a submit flow that guards against double-submits.
when_to_use: Read for any surface with inputs. It specializes semantic-html-and-aria for form controls and models the input lifecycle as a small state machine (see state-driven-ui).
---

# Forms & Validation

Forms are where accessibility and correctness meet: a mislabeled input or an error message that only
appears visually locks out keyboard and screen-reader users, and weak validation ships bad data. Good
forms tie every message to its control and expose state programmatically.

## The one rule

**Every input has an associated label, and every validation message is programmatically tied to its
input — so the person filling the form always knows what's wrong and where.**

## Label and structure

- Associate a `<label for="id">` with each input's `id` (or wrap the input in the label). Placeholder
  text is **not** a label — it vanishes on input and often fails contrast.
- Group related controls with `<fieldset>`/`<legend>` (e.g. a set of radios). Mark required fields with
  `required` and make the requirement visible in the label, not by color alone.

## Validate and message accessibly

- On invalid input, set `aria-invalid="true"` on the control and link the message with
  `aria-describedby="err-id"`, so assistive tech announces the error for that field.
- Put the error text next to the field, not only in a distant summary. If you also show a summary, move
  focus to it (or to the first invalid field) on submit.
- Validate on submit at minimum; validating on blur can help but don't yell at users mid-typing.

## Submit flow

- Prevent the default submit and handle it in JS; disable the submit button while the request is
  in-flight to stop double-submits, and re-enable on completion (success or error).
- Model the states — `editing`, `submitting`, `error`, `success` — and render from them (see
  state-driven-ui) rather than toggling bits of DOM ad hoc.

## Before you finish

1. Does every input have a real associated label (not a placeholder)?
2. Is each error `aria-describedby`-linked and its control `aria-invalid` when wrong?
3. Is focus moved to the first error (or summary) on a failed submit?
4. Is double-submit prevented, and are all input states rendered from state?
