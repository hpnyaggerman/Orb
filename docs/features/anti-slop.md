# Anti-slop

Remove overused words, phrases, and the rhetorical patterns commonly seen in LLM outputs.

- The user maintains a Slop Phrase Bank of words and phrases they're allergic to.
- The final Editor pass checks the output for those phrases and prompts the Agent model to surgically rewrite only the sentences where they're found.

## Slop Phrase Bank

A user-editable list of banned words and phrases. Entries can be literal variants or regex patterns, and matching is fuzzy enough to catch close paraphrases while staying contained to a single sentence so rewrites are surgical.

## Contrastive negation ("Not X; but Y")

Detect the `Not X; but Y` rhetorical pattern (and its kin, like `isn't X, it's Y`) and ask for a rewrite. Only works within a single sentence boundary.

## Anti-echo

Detect the habit some models have of parroting the user's own dialogue straight back as an incredulous question:

> **H:** "I have absolutely no money."
> **A:** "Absolutely no money?" she repeats.

Unlike the other scanners (which look only at the assistant's text), anti-echo compares the draft against the user's immediately-preceding message. It flags a question in the draft — quoted *or* unquoted, ending in `?` — when its words are an **exact contiguous copy** of a run in the user's **dialogue**. The comparison pool is only what the character *said*: text inside the user's quote spans, with `[OOC: …]` asides removed first (their contents, inner quotes included, are directives rather than speech). The user's narration and out-of-character notes are therefore never echo bait, and a message with no quoted dialogue produces no flags. A content-word floor keeps bare function-word questions ("You?", "What?") from triggering, and a coverage check ignores longer questions that merely reuse one of the user's nouns. The flagged echo is added to the Editor audit report so the rewrite loop can recast it.

For repeated structure, sentence openers, and phrase reuse, see [Anti-repetition](anti-repetition.md).
