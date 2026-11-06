# Hook

The hook is a text card on screen from 0 to 3 seconds (`hook.duration_seconds`). It is not burned into the spoken audio. Captions keep running underneath, lower in the frame.

## How you choose the line

The script suggests one line and up to two alternates from the **kept** transcript (fillers already gone), in the clip's language. You may replace it. Rules:

1. Same language as the clip. Never translate the hook.
2. Skip a pure greeting: `hola`, `hey`, `hello`, `buenas`, `buenos días` when that is the whole sentence.
3. Skip fillers. They are already out of the kept transcript.
4. Prefer, in order: a number, a result (`ahorrar`, `truco`, `fastest`, `never`, `gratis`, `error`), then the earliest sentence that says something concrete.
5. Stay inside 8 words and 42 characters (`hook.max_words`, `hook.max_chars`). The safe zone is narrow.
6. Do not end on a dangling `y`, `and`, `de`, `que`, `to`, or `the`.
7. Show the user the line, why it won, and one alternate. Wait for a yes unless they already waived the checkpoint.

The `reason` field is `number`, `result_word`, `early_claim`, `fallback_opening`, or `user` when they typed the line. The summary translates that reason.

Pass the winner with `--hook` on the render step. Do not re-transcribe just to change the hook.
