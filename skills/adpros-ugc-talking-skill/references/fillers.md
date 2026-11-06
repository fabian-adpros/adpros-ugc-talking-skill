# Fillers

Fillers are removed from `words.json` after transcription. The lists are `assets/fillers.json`. Edit that file to add a phrase. Each entry is tokens plus `standalone`.

A token is the word lowercased, with punctuation stripped (`¿me` and `entiendes?` match `me` + `entiendes`).

## Conservative (default)

Removes clear fillers.

Always, even inside a sentence:

- EN: `um`, `uh`, `erm`, `hmm`, `mm`, `mmm`
- ES: `eh`, `eee`, `mmm`, `mm`

Only when the phrase sits in its own gap (about 0.18s of air on both sides, or punctuation, or the start/end of the clip):

- EN: `you know`, `i mean`
- ES: `este`, `o sea`, `pues`, `bueno`, `digamos`, `tipo`, `me entiendes`

`este producto`, `I like this`, and `tipo de` stay. `like` is not in the conservative list at all.

## Aggressive

Pass `--mode aggressive` only when the user asks.

Also removes, still only when standalone: `like`, `basically`, `actually`, `literally`, `so`, `right`, `kind of`, `sort of`, `sabes`, `entonces`, `verdad`, `la verdad`.

Removes even mid-sentence: `you know`, `i mean`, `o sea`, `me entiendes`, `digamos`.

`digamos` in aggressive mode will eat a real "let's say". Say that when you offer the mode. `este`, `pues`, `bueno`, `tipo`, and `like` stay standalone-only so the cut does not eat content words.

## What the cut sounds like

The filler interval is removed. A breath shorter than 0.12s on either side is swallowed so you do not hear a click. Neighboring real words are not trimmed. If every word would be classified as a filler, nothing is removed.

## Honest limit

If Whisper never wrote the filler, it cannot be cut. See [transcription.md](transcription.md). The plan warning is the source of truth. `plan.json` → `fillers.items` lists only words that were present and removed.
