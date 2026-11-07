Evaluation protocol (no performance results yet)

1. Review the fictional product and Hindi-English scripts with both team members.
2. Create 6–8 synthetic responses per clause, including paraphrases, misconceptions, omissions, agreement-only, counter-questions and off-topic answers. Keep a held-out subset.
3. Both reviewers independently annotate fact indices, misconceptions and verdicts without seeing scorer output. Reconcile disagreements; version the rubric before testing.
4. Run the affirmative-only baseline FIRST: mark explicit agreement as accepted, with the exact same transcripts used for HMH. Preserve per-answer predictions and labels. Do not equate scripted fixtures with human-labelled data.
5. Run the semantic scorer once per held-out answer and save raw outputs, failures, model identifier, prompt, pack hash, timestamps, latency and usage where returned.
6. Report false acceptance among human-labelled misunderstood/no_evidence cases, false rejection among understood cases, abstentions, extra turns and denominators. Report scorer-only results separately from complete-session results. No accuracy claim is supported by the policy tests.
7. Confidence threshold 0.85 is provisional and must be tuned only on development responses. Self-reported confidence is not calibrated probability.
8. Voice evaluation must compare human transcripts with Prisma transcripts and track end-to-end errors separately. Synthetic audio only; report at least one failure.

Runner usage:

```sh
python -m eval.run baseline reviewed.jsonl results/baseline.jsonl
python -m eval.run hmh reviewed.jsonl results/hmh.jsonl --baseline results/baseline.jsonl
python -m eval.summarize results/hmh.jsonl
```

`labels.example.jsonl` is deliberately unreviewed and will be rejected by the runner. Create independently reviewed rows with `label_status: reconciled` and two distinct reviewer names only after the actual review. The affirmative-only comparator accepts only whole-answer agreement phrases; document this restricted baseline when reporting results. It is not a competitive comprehension model.
